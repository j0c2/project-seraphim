SHELL := /bin/bash

.PHONY: help infra-apply deploy load-test lint test docker-build docker-push

help:
	@echo "Targets: infra-apply, deploy, load-test, lint, test"

infra-apply:
	@echo "TODO: provision cluster & base infra via Terraform/Helm"

deploy:
	helm upgrade --install seraphim-inference config/infra/helm/seraphim-inference -n seraphim --create-namespace

load-test:
	locust -f tests/e2e/locustfile.py --headless -u 100 -r 10 -H http://localhost:8080 || true

lint:
	black services/ || true
	isort services/ || true
	flake8 services/ || true

unit:
	pytest -q tests/unit

test: unit

docker-build:
	docker build -t seraphim-inference:dev services/inference

docker-push:
	@echo "TODO: docker push to your registry"
