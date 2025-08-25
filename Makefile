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
	@($(PY) -m uvicorn services.inference.app.main:app --host 127.0.0.1 --port 8080 >/tmp/seraphim_uvicorn.log 2>&1 & echo $$! > /tmp/seraphim_uvicorn.pid)
	@echo "Waiting for http://127.0.0.1:8080/healthz ..."
	@bash -lc 'for i in {1..50}; do if curl -sf --max-time 0.3 http://127.0.0.1:8080/healthz >/dev/null; then echo READY; exit 0; fi; sleep 0.1; done; echo NOT READY; exit 1'
	$(PY) -m locust -f tests/e2e/locustfile.py --headless -u 10 -r 5 -t 10s --only-summary --host http://127.0.0.1:8080
	- kill $$(cat /tmp/seraphim_uvicorn.pid) || true; rm -f /tmp/seraphim_uvicorn.pid
lint: dev-deps
	black services/ || true
	isort services/ || true
	flake8 services/ || true

unit: dev-deps
	$(PY) -m pytest -q tests/unit

test: unit

run: dev-deps
	$(PY) -m uvicorn services.inference.app.main:app --host 127.0.0.1 --port 8080

docker-build:
	docker build -t seraphim-inference:dev services/inference

docker-push:
	@echo "TODO: docker push to your registry"
