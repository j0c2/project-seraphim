# Makefile for E2E Observability Tests
SHELL := /bin/bash

# Docker Compose files
COMPOSE_FILE := ../../docker-compose.yml
COMPOSE_OVERRIDE := docker-compose.test.yml
COMPOSE_CMD := docker-compose -f $(COMPOSE_FILE) -f $(COMPOSE_OVERRIDE)

# Test configuration
PYTEST_ARGS ?= tests/e2e/ -v --tb=short
TEST_PATTERN ?= ""
LOG_LEVEL ?= INFO
TEST_TIMEOUT ?= 300

# Service URLs for local testing
export TEST_INFERENCE_URL := http://localhost:8080
export TEST_PROMETHEUS_URL := http://localhost:9090
export TEST_JAEGER_URL := http://localhost:16686
export TEST_LOKI_URL := http://localhost:3100
export TEST_GRAFANA_URL := http://localhost:3000
export TEST_TIMEOUT := $(TEST_TIMEOUT)
export LOG_LEVEL := $(LOG_LEVEL)
export PYTHONPATH := $(shell pwd)/../..

# Colors for output
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
BLUE := \033[0;34m
NC := \033[0m # No Color

.PHONY: help build start stop test test-quick test-integration test-metrics test-logs test-traces test-dashboards status logs clean setup check-deps all

help: ## Show this help message
	@echo "E2E Observability Test Suite"
	@echo ""
	@echo "Usage: make [target] [OPTIONS]"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  $(BLUE)%-20s$(NC) %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Options:"
	@echo "  $(BLUE)TEST_PATTERN$(NC)   Pytest pattern to run (e.g., test_metrics)"
	@echo "  $(BLUE)LOG_LEVEL$(NC)      Log level: DEBUG, INFO, WARNING, ERROR"
	@echo "  $(BLUE)TEST_TIMEOUT$(NC)   Test timeout in seconds (default: 300)"
	@echo ""
	@echo "Examples:"
	@echo "  make test                              # Run all tests"
	@echo "  make test TEST_PATTERN=test_metrics   # Run only metrics tests"
	@echo "  make test LOG_LEVEL=DEBUG             # Run with debug logging"

setup: ## Install test dependencies
	@echo "$(BLUE)Installing test dependencies...$(NC)"
	@pip install -r requirements-e2e.txt
	@echo "$(GREEN)Dependencies installed successfully!$(NC)"

check-deps: ## Check if required tools are installed
	@echo "$(BLUE)Checking dependencies...$(NC)"
	@command -v docker >/dev/null 2>&1 || { echo "$(RED)Error: docker is required but not installed.$(NC)" >&2; exit 1; }
	@command -v docker-compose >/dev/null 2>&1 || { echo "$(RED)Error: docker-compose is required but not installed.$(NC)" >&2; exit 1; }
	@command -v python3 >/dev/null 2>&1 || { echo "$(RED)Error: python3 is required but not installed.$(NC)" >&2; exit 1; }
	@command -v curl >/dev/null 2>&1 || { echo "$(RED)Error: curl is required but not installed.$(NC)" >&2; exit 1; }
	@command -v jq >/dev/null 2>&1 || echo "$(YELLOW)Warning: jq not installed (recommended for JSON parsing).$(NC)"
	@echo "$(GREEN)All dependencies are available!$(NC)"

build: check-deps ## Build Docker images
	@echo "$(BLUE)Building Docker images...$(NC)"
	$(COMPOSE_CMD) build inference test-runner
	@echo "$(GREEN)Images built successfully!$(NC)"

start: build ## Start observability stack
	@echo "$(BLUE)Starting observability stack...$(NC)"
	$(COMPOSE_CMD) up -d inference prometheus jaeger loki promtail grafana
	@echo "$(YELLOW)Waiting for services to become healthy...$(NC)"
	@$(MAKE) --no-print-directory wait-for-health
	@echo "$(GREEN)All services are running and healthy!$(NC)"
	@$(MAKE) --no-print-directory status

wait-for-health: ## Wait for all services to be healthy
	@echo "$(BLUE)Checking service health...$(NC)"
	@timeout 300 bash -c 'until $(COMPOSE_CMD) ps inference | grep -q "healthy"; do echo "Waiting for inference..."; sleep 5; done' || { echo "$(RED)Inference service failed to start$(NC)"; exit 1; }
	@timeout 300 bash -c 'until $(COMPOSE_CMD) ps prometheus | grep -q "healthy"; do echo "Waiting for Prometheus..."; sleep 5; done' || { echo "$(RED)Prometheus service failed to start$(NC)"; exit 1; }
	@timeout 300 bash -c 'until $(COMPOSE_CMD) ps jaeger | grep -q "healthy"; do echo "Waiting for Jaeger..."; sleep 5; done' || { echo "$(RED)Jaeger service failed to start$(NC)"; exit 1; }
	@timeout 300 bash -c 'until $(COMPOSE_CMD) ps loki | grep -q "healthy"; do echo "Waiting for Loki..."; sleep 5; done' || { echo "$(RED)Loki service failed to start$(NC)"; exit 1; }
	@timeout 300 bash -c 'until $(COMPOSE_CMD) ps grafana | grep -q "healthy"; do echo "Waiting for Grafana..."; sleep 5; done' || { echo "$(RED)Grafana service failed to start$(NC)"; exit 1; }

status: ## Show service status
	@echo "$(BLUE)Service Status:$(NC)"
	@$(COMPOSE_CMD) ps
	@echo ""
	@echo "$(BLUE)Service Endpoints:$(NC)"
	@echo "  Inference:  $(TEST_INFERENCE_URL)"
	@echo "  Prometheus: $(TEST_PROMETHEUS_URL)"
	@echo "  Jaeger:     $(TEST_JAEGER_URL)"
	@echo "  Loki:       $(TEST_LOKI_URL)"
	@echo "  Grafana:    $(TEST_GRAFANA_URL) (admin/admin)"

verify-endpoints: ## Verify that all endpoints are responding
	@echo "$(BLUE)Verifying service endpoints...$(NC)"
	@curl -sf $(TEST_INFERENCE_URL)/health > /dev/null && echo "$(GREEN)✅ Inference service is responding$(NC)" || echo "$(RED)❌ Inference service is not responding$(NC)"
	@curl -sf $(TEST_PROMETHEUS_URL)/-/ready > /dev/null && echo "$(GREEN)✅ Prometheus is responding$(NC)" || echo "$(RED)❌ Prometheus is not responding$(NC)"
	@curl -sf $(TEST_JAEGER_URL)/api/services > /dev/null && echo "$(GREEN)✅ Jaeger is responding$(NC)" || echo "$(RED)❌ Jaeger is not responding$(NC)"
	@curl -sf $(TEST_LOKI_URL)/ready > /dev/null && echo "$(GREEN)✅ Loki is responding$(NC)" || echo "$(RED)❌ Loki is not responding$(NC)"
	@curl -sf $(TEST_GRAFANA_URL)/api/health > /dev/null && echo "$(GREEN)✅ Grafana is responding$(NC)" || echo "$(RED)❌ Grafana is not responding$(NC)"

generate-baseline-data: ## Generate baseline observability data
	@echo "$(BLUE)Generating baseline observability data...$(NC)"
	@for i in {1..10}; do \
		echo "Making request $$i..."; \
		curl -s -X POST $(TEST_INFERENCE_URL)/predict \
			-H "Content-Type: application/json" \
			-d '{"text": "Baseline test '$$i'", "model": "primary"}' > /dev/null || true; \
		sleep 0.5; \
	done
	@echo "$(YELLOW)Waiting for data to propagate...$(NC)"
	@sleep 10
	@echo "$(GREEN)Baseline data generated!$(NC)"

test: start verify-endpoints generate-baseline-data ## Run all E2E observability tests
	@echo "$(BLUE)Running E2E observability tests...$(NC)"
	@if [ -n "$(TEST_PATTERN)" ]; then \
		echo "$(YELLOW)Running tests matching pattern: $(TEST_PATTERN)$(NC)"; \
		PYTEST_ARGS_FINAL="$(PYTEST_ARGS) -k $(TEST_PATTERN)"; \
	else \
		PYTEST_ARGS_FINAL="$(PYTEST_ARGS)"; \
	fi; \
	$(COMPOSE_CMD) run --rm --name e2e-test-runner test-runner pytest $$PYTEST_ARGS_FINAL || (echo "$(RED)Tests failed! Check logs above.$(NC)" && exit 1)
	@echo "$(GREEN)All tests passed successfully!$(NC)"

test-quick: ## Run quick smoke tests only
	@$(MAKE) test TEST_PATTERN="test_health or test_metrics_collection or test_basic_tracing"

test-integration: ## Run integration tests
	@$(MAKE) test TEST_PATTERN="TestObservabilityIntegration"

test-metrics: ## Run metrics-related tests
	@$(MAKE) test TEST_PATTERN="test_metrics or TestMetrics"

test-logs: ## Run log aggregation tests
	@$(MAKE) test TEST_PATTERN="test_log or TestLogs"

test-traces: ## Run distributed tracing tests
	@$(MAKE) test TEST_PATTERN="test_trac or TestTracing"

test-dashboards: ## Run dashboard integration tests
	@$(MAKE) test TEST_PATTERN="TestDashboard"

test-performance: ## Run performance impact tests
	@$(MAKE) test TEST_PATTERN="test_performance"

test-local: setup check-deps ## Run tests locally (without Docker)
	@echo "$(BLUE)Running tests locally...$(NC)"
	@echo "$(YELLOW)Note: Ensure observability stack is running first with 'make start'$(NC)"
	@if [ -n "$(TEST_PATTERN)" ]; then \
		PYTEST_ARGS_FINAL="$(PYTEST_ARGS) -k $(TEST_PATTERN)"; \
	else \
		PYTEST_ARGS_FINAL="$(PYTEST_ARGS)"; \
	fi; \
	cd ../.. && python -m pytest $$PYTEST_ARGS_FINAL

logs: ## Show logs from all services
	@echo "$(BLUE)Recent logs from all services:$(NC)"
	$(COMPOSE_CMD) logs --tail=50 --follow

logs-service: ## Show logs from specific service (usage: make logs-service SERVICE=inference)
	@if [ -z "$(SERVICE)" ]; then \
		echo "$(RED)Error: SERVICE parameter is required. Usage: make logs-service SERVICE=inference$(NC)"; \
		exit 1; \
	fi
	@echo "$(BLUE)Logs from $(SERVICE):$(NC)"
	$(COMPOSE_CMD) logs --tail=100 --follow $(SERVICE)

stop: ## Stop all services
	@echo "$(YELLOW)Stopping observability stack...$(NC)"
	$(COMPOSE_CMD) down
	@echo "$(GREEN)All services stopped.$(NC)"

clean: stop ## Stop services and remove volumes/networks
	@echo "$(YELLOW)Cleaning up observability stack...$(NC)"
	$(COMPOSE_CMD) down -v --remove-orphans
	@docker system prune -f
	@echo "$(GREEN)Cleanup completed.$(NC)"

reset: clean ## Full reset - clean and rebuild everything
	@echo "$(YELLOW)Performing full reset...$(NC)"
	$(COMPOSE_CMD) down -v --rmi all --remove-orphans
	@$(MAKE) build
	@echo "$(GREEN)Reset completed. Run 'make start' to begin.$(NC)"

shell-test-runner: ## Open shell in test runner container
	$(COMPOSE_CMD) run --rm test-runner /bin/bash

shell-inference: ## Open shell in inference service container
	$(COMPOSE_CMD) exec inference /bin/bash

debug: start ## Start services and run in debug mode
	@echo "$(BLUE)Debug mode - services started, run tests manually$(NC)"
	@echo "Available commands:"
	@echo "  make test-local                    # Run tests locally"
	@echo "  make shell-test-runner             # Open test container shell"
	@echo "  make logs                          # View all service logs"
	@echo "  make verify-endpoints              # Check service health"
	@echo ""
	@echo "Service URLs:"
	@echo "  Inference:  $(TEST_INFERENCE_URL)"
	@echo "  Prometheus: $(TEST_PROMETHEUS_URL)"
	@echo "  Jaeger:     $(TEST_JAEGER_URL)"
	@echo "  Loki:       $(TEST_LOKI_URL)"
	@echo "  Grafana:    $(TEST_GRAFANA_URL) (admin/admin)"

all: clean build test ## Full test cycle - clean, build, and test

# CI/CD targets
ci-test: ## Run tests in CI mode (used by GitHub Actions)
	@echo "$(BLUE)Running tests in CI mode...$(NC)"
	@$(MAKE) test PYTEST_ARGS="$(PYTEST_ARGS) --maxfail=5 --tb=short"

ci-build: ## Build images for CI
	@echo "$(BLUE)Building images for CI...$(NC)"
	$(COMPOSE_CMD) build --parallel

# Development targets
dev-setup: ## Setup development environment
	@echo "$(BLUE)Setting up development environment...$(NC)"
	@$(MAKE) setup
	@$(MAKE) build
	@echo "$(GREEN)Development environment ready!$(NC)"
	@echo "Run 'make start' to begin testing."

dev-test-watch: ## Run tests and restart on file changes
	@echo "$(BLUE)Running tests in watch mode...$(NC)"
	@echo "$(YELLOW)Note: Install 'entr' for file watching: apt-get install entr$(NC)"
	@find ../../tests/e2e ../../services -name "*.py" | entr -r make test-local

info: ## Show environment information
	@echo "$(BLUE)E2E Test Environment Information:$(NC)"
	@echo "  Docker version: $$(docker --version)"
	@echo "  Docker Compose version: $$(docker-compose --version)"
	@echo "  Python version: $$(python3 --version)"
	@echo "  Current directory: $$(pwd)"
	@echo "  Compose files: $(COMPOSE_FILE) $(COMPOSE_OVERRIDE)"
	@echo "  Test timeout: $(TEST_TIMEOUT)s"
	@echo "  Log level: $(LOG_LEVEL)"
	@if [ -n "$(TEST_PATTERN)" ]; then echo "  Test pattern: $(TEST_PATTERN)"; fi
