SHELL := /bin/bash

# Variables
LOCUST_HOST ?= http://localhost:8080
ENV ?= dev
CHART := config/infra/helm/seraphim-inference
HELM_RELEASE := seraphim-inference
NAMESPACE_dev := seraphim
NAMESPACE_stage := seraphim-stage
NAMESPACE_prod := seraphim-prod
VALUES_FILE := $(CHART)/values-$(ENV).yaml

.PHONY: help infra-apply deploy load-test lint test unit docker-build docker-push dev-deps e2e run

help:
	@echo "Targets: dev-deps, unit, e2e, load-test, run, deploy, infra-apply, lint, test"
	@echo "Variables: ENV={dev|stage|prod} (default: dev), LOCUST_HOST=$(LOCUST_HOST)"

infra-apply:
	@echo "TODO: provision cluster & base infra via Terraform/Helm"

dev-deps:
	python3 -m pip install -r services/inference/requirements.txt -r requirements-dev.txt

deploy:
	helm upgrade --install $(HELM_RELEASE) $(CHART) -n $(NAMESPACE_$(ENV)) --create-namespace -f $(VALUES_FILE)

load-test: dev-deps
	locust -f tests/e2e/locustfile.py --headless -u 100 -r 10 -H $(LOCUST_HOST) || true

e2e: dev-deps
	locust -f tests/e2e/locustfile.py --headless -u 10 -r 5 -H $(LOCUST_HOST) || true

lint: dev-deps
	black services/ || true
	isort services/ || true
	flake8 services/ || true

unit: dev-deps
	pytest -q tests/unit

test: unit

run: dev-deps
	python3 -m uvicorn services.inference.app.main:app --host 0.0.0.0 --port 8080

docker-build:
	docker build -t seraphim-inference:dev services/inference

docker-push:
	@echo "TODO: docker push to your registry"
