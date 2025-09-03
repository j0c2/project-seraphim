SHELL := /bin/bash

# Variables
LOCUST_HOST ?= http://127.0.0.1:8080
ENV ?= dev
CHART := config/infra/helm/seraphim-inference
HELM_RELEASE := seraphim-inference
NAMESPACE_dev := seraphim
NAMESPACE_stage := seraphim-stage
NAMESPACE_prod := seraphim-prod
VALUES_FILE := $(CHART)/values-$(ENV).yaml

# Python virtual environment
VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(PY) -m pip

.PHONY: help infra-apply deploy load-test lint test unit docker-build docker-push dev-deps e2e e2e-local run venv

help:
	@echo "Targets: venv, dev-deps, unit, e2e, e2e-local, load-test, run, deploy, infra-apply, lint, test"
	@echo "Variables: ENV={dev|stage|prod} (default: dev), LOCUST_HOST=$(LOCUST_HOST)"

infra-apply:
	@echo "TODO: provision cluster & base infra via Terraform/Helm"

venv:
	@test -x $(PY) || python3 -m venv $(VENV)

dev-deps: venv
	$(PIP) install -U pip wheel
	$(PIP) install -r requirements-dev.txt

deploy:
	helm upgrade --install $(HELM_RELEASE) $(CHART) -n $(NAMESPACE_$(ENV)) --create-namespace -f $(VALUES_FILE)

load-test: dev-deps
	$(PY) -m locust -f tests/e2e/locustfile.py --headless -u 100 -r 10 -H $(LOCUST_HOST) --only-summary || true

e2e: dev-deps
	$(PY) -m locust -f tests/e2e/locustfile.py --headless -u 10 -r 5 -H $(LOCUST_HOST) --only-summary || true

e2e-local: dev-deps
	@(PYTHONPATH=$(PWD)/services:$(PWD):$(PYTHONPATH) $(PY) -m uvicorn services.inference.app.main:app --host ********* --port 8080 >/tmp/seraphim_uvicorn.log 2>&1 & echo $$! > /tmp/seraphim_uvicorn.pid)
	@echo "Waiting for http://127.0.0.1:8080/healthz ..."
	@bash -lc 'for i in {1..50}; do if curl -sf --max-time 0.3 http://127.0.0.1:8080/healthz >/dev/null; then echo READY; exit 0; fi; sleep 0.1; done; echo NOT READY; exit 1'
	$(PY) -m locust -f tests/e2e/locustfile.py --headless -u 10 -r 5 -t 10s --only-summary --host http://127.0.0.1:8080
	- kill $$(cat /tmp/seraphim_uvicorn.pid) || true; rm -f /tmp/seraphim_uvicorn.pid
lint: dev-deps
	black services/ || true
	isort services/ || true
	flake8 services/ || true

unit: dev-deps
	PYTHONPATH=$(PWD)/services:$(PWD):$(PYTHONPATH) $(PY) -m pytest -q tests/unit

test: unit

run: dev-deps
	PYTHONPATH=$(PWD)/services:$(PWD):$(PYTHONPATH) $(PY) -m uvicorn services.inference.app.main:app --host ********* --port 8080

# TorchServe targets
TS_IMAGE ?= seraphim-model-server:dev
TS_DIR := services/model-server
TS_MAR_DIR := $(TS_DIR)/model-store
TS_HANDLER := $(TS_DIR)/handlers/custom_text_handler.py
TS_MODEL_NAME ?= custom-text
TS_MAR := $(TS_MAR_DIR)/$(TS_MODEL_NAME).mar
K8S_NS ?= seraphim

.PHONY: ts-build ts-run ts-run-dev ts-register ts-register-local-mar ts-register-k8s ts-build-mar

ts-build:
	docker build -t $(TS_IMAGE) $(TS_DIR)

ts-run:
	docker run --rm -p 8080:8080 -p 8081:8081 -p 8082:8082 -e SAMPLE_MODEL=true $(TS_IMAGE)

ts-run-dev:
	# Run TorchServe with local model-store volume mounted
	docker run --rm -p 8080:8080 -p 8081:8081 -p 8082:8082 \
	  -e SAMPLE_MODEL=false \
	  -v $(PWD)/$(TS_DIR)/model-store:/home/model-server/model-store \
	  $(TS_IMAGE)

ts-register:
	# Register a remote MAR into a running TorchServe mgmt API
	@if [ -z "$(MODEL_NAME)" ] || [ -z "$(URL)" ]; then \
		echo "Usage: make ts-register MODEL_NAME=name URL=url_to_mar" >&2; exit 2; \
	fi
	curl -fsSL -X POST "http://127.0.0.1:8081/models?url=$(URL)&model_name=$(MODEL_NAME)&initial_workers=1"

ts-register-local-mar:
	# Register a locally built MAR (requires ts-run-dev so the model-store is mounted)
	@if [ ! -f "$(TS_MAR)" ]; then \
		echo "MAR not found: $(TS_MAR). Build it with 'make ts-build-mar'" >&2; exit 2; \
	fi
	curl -fsSL -X POST "http://127.0.0.1:8081/models?url=$(TS_MODEL_NAME).mar&model_name=$(TS_MODEL_NAME)&initial_workers=1"

ts-register-k8s:
	# Port-forward the k8s Service to register a model by URL
	@if [ -z "$(MODEL_NAME)" ] || [ -z "$(URL)" ]; then \
		echo "Usage: make ts-register-k8s MODEL_NAME=name URL=url_to_mar [K8S_NS=seraphim]" >&2; exit 2; \
	fi
	- kubectl -n $(K8S_NS) port-forward svc/seraphim-model-server 18081:8081 >/tmp/ts_pf.log 2>&1 & echo $$! > /tmp/ts_pf.pid
	sleep 1
	curl -fsSL -X POST "http://127.0.0.1:18081/models?url=$(URL)&model_name=$(MODEL_NAME)&initial_workers=1"
	- kill $$(cat /tmp/ts_pf.pid) || true; rm -f /tmp/ts_pf.pid

ts-build-mar:
	# Build a MAR from the custom handler (no weights)
	mkdir -p $(TS_MAR_DIR)
	docker run --rm -v $(PWD)/$(TS_DIR):/ws -w /ws pytorch/torchserve:0.11.0-cpu \
	  torch-model-archiver --model-name $(TS_MODEL_NAME) --version 1.0 \
	  --handler handlers/custom_text_handler.py --export-path /ws/model-store --force

docker-build:
	docker build -t seraphim-inference:dev services/inference

docker-push:
	@echo "TODO: docker push to your registry"

# One-shot end-to-end demo: build TS, build MAR, run TS detached, register, run inference, predict, and cleanup
.PHONY: e2e-ts
E2E_TS_CONTAINER ?= seraphim-ts-e2e
E2E_MODEL_NAME ?= custom-text
E2E_PREDICT_TEXT ?= hello world

e2e-ts: ts-build ts-build-mar
	- docker rm -f $(E2E_TS_CONTAINER) >/dev/null 2>&1 || true
	docker run -d --name $(E2E_TS_CONTAINER) \
	  -p 8080:8080 -p 8081:8081 -p 8082:8082 \
	  -e SAMPLE_MODEL=false \
	  -v $(PWD)/$(TS_DIR)/model-store:/home/model-server/model-store \
	  $(TS_IMAGE)
	@echo "Waiting for TorchServe management to accept model registration..."
	@bash -lc 'for i in {1..50}; do \
	  curl -fsSL -X POST "http://127.0.0.1:8081/models?url=$(E2E_MODEL_NAME).mar&model_name=$(E2E_MODEL_NAME)&initial_workers=1" >/tmp/ts_reg.json 2>/dev/null && echo REGISTERED && break; \
	  sleep 0.4; done'
	@echo "Starting inference app on 8088..."
	@($(PY) -m uvicorn services.inference.app.main:app --host 127.0.0.1 --port 8088 >/tmp/seraphim_inf_e2e.log 2>&1 & echo $$! > /tmp/seraphim_inf_e2e.pid)
	@bash -lc 'for i in {1..50}; do curl -sf --max-time 0.3 http://127.0.0.1:8088/healthz >/dev/null && echo INF_READY && break; sleep 0.2; done'
	@echo "Calling /predict via inference app -> TorchServe..."
	@bash -lc 'TS_URL=http://127.0.0.1:8080 MODEL_NAME=$(E2E_MODEL_NAME) curl -s -X POST http://127.0.0.1:8088/predict -H "Content-Type: application/json" -d "{\"text\": \"$(E2E_PREDICT_TEXT)\"}"; echo'
	- kill $$(cat /tmp/seraphim_inf_e2e.pid) || true; rm -f /tmp/seraphim_inf_e2e.pid
	- docker rm -f $(E2E_TS_CONTAINER) >/dev/null 2>&1 || true
