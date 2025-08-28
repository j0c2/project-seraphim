# E2E Observability Test Suite

This comprehensive end-to-end (E2E) test suite validates the observability stack for the Seraphim ML inference platform. It ensures that metrics, logs, and distributed traces work together correctly across all services and provide complete visibility into system behavior.

## 🎯 Overview

The test suite validates:
- **Metrics collection and querying** via Prometheus
- **Distributed tracing** via Jaeger/OpenTelemetry
- **Log aggregation and correlation** via Loki/Promtail
- **Dashboard integration** via Grafana
- **Cross-service correlation** using correlation IDs
- **Performance impact** of observability overhead
- **Error handling and propagation**

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Inference      │    │  Prometheus     │    │  Jaeger         │
│  Service        │───▶│  (Metrics)      │    │  (Traces)       │
│                 │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                                              ▲
         ▼                                              │
┌─────────────────┐    ┌─────────────────┐             │
│  Promtail       │───▶│  Loki           │             │
│  (Log Ship)     │    │  (Logs)         │             │
└─────────────────┘    └─────────────────┘             │
                                │                      │
                                ▼                      │
                    ┌─────────────────┐                │
                    │  Grafana        │                │
                    │  (Dashboards)   │────────────────┘
                    └─────────────────┘
                              │
                    ┌─────────────────┐
                    │  Test Runner    │
                    │  (E2E Tests)    │
                    └─────────────────┘
```

## 📁 Structure

```
tests/e2e/
├── conftest.py                          # Test fixtures and configuration
├── test_observability_metrics.py        # Metrics collection tests
├── test_observability_tracing.py        # Distributed tracing tests  
├── test_observability_logs.py           # Log aggregation tests
├── test_observability_integration.py    # Cross-component integration tests
├── fixtures/                           # Test utilities and fixtures
│   ├── __init__.py
│   ├── clients.py                      # API clients for services
│   ├── observability_validator.py     # Observability data validation
│   └── test_data.py                   # Test data generators
├── config/                            # Test-specific configurations
│   ├── prometheus-test.yml            # Prometheus config
│   ├── loki-test.yml                 # Loki config
│   └── promtail-test.yml             # Promtail config
├── docker-compose.test.yml           # Docker compose for testing
├── Dockerfile.test                   # Test runner container
├── requirements-e2e.txt              # Test dependencies
├── Makefile                         # Test automation
└── README.md                        # This file
```

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+
- curl, jq (recommended)

### Run All Tests

```bash
cd tests/e2e
make test
```

This will:
1. Build Docker images
2. Start the observability stack
3. Wait for services to be healthy
4. Generate baseline data
5. Run all E2E tests
6. Clean up resources

### Run Specific Test Categories

```bash
# Metrics tests only
make test-metrics

# Distributed tracing tests
make test-traces

# Log aggregation tests
make test-logs

# Dashboard integration tests
make test-dashboards

# Quick smoke tests
make test-quick

# Integration tests
make test-integration
```

### Run Specific Test Patterns

```bash
# Run tests matching a specific pattern
make test TEST_PATTERN="test_correlation"

# Run with debug logging
make test LOG_LEVEL=DEBUG

# Combine options
make test TEST_PATTERN="TestMetrics" LOG_LEVEL=DEBUG
```

## 🔧 Development Workflow

### Local Development

1. **Setup development environment:**
   ```bash
   make dev-setup
   ```

2. **Start services for development:**
   ```bash
   make start
   ```

3. **Run tests locally (faster iteration):**
   ```bash
   make test-local
   ```

4. **Debug mode (services running, manual testing):**
   ```bash
   make debug
   ```

### Service Endpoints

When running locally, services are available at:

- **Inference Service**: http://localhost:8080
- **Prometheus**: http://localhost:9090
- **Jaeger UI**: http://localhost:16686
- **Loki**: http://localhost:3100
- **Grafana**: http://localhost:3000 (admin/admin)

### Debugging Tests

```bash
# View all service logs
make logs

# View specific service logs
make logs-service SERVICE=inference

# Check service status
make status

# Verify endpoints are responding
make verify-endpoints

# Open shell in test runner
make shell-test-runner

# Open shell in inference service
make shell-inference
```

## 🧪 Test Categories

### 1. Metrics Tests (`test_observability_metrics.py`)

**Purpose**: Validate Prometheus metrics collection and querying

**Key Tests**:
- `test_metrics_collection`: Basic metric ingestion
- `test_request_rate_metrics`: Request rate tracking
- `test_latency_histogram_metrics`: P95/P99 latency metrics
- `test_error_rate_metrics`: Error rate calculation
- `test_canary_deployment_metrics`: Canary routing metrics
- `test_custom_business_metrics`: Application-specific metrics

### 2. Distributed Tracing Tests (`test_observability_tracing.py`)

**Purpose**: Validate OpenTelemetry tracing and Jaeger integration

**Key Tests**:
- `test_basic_tracing`: Span creation and collection
- `test_trace_correlation_with_logs`: Trace-log correlation
- `test_distributed_tracing_across_services`: Multi-service traces
- `test_trace_sampling_configuration`: Sampling rates
- `test_trace_error_handling`: Error span attributes
- `test_trace_performance_impact`: Tracing overhead

### 3. Log Aggregation Tests (`test_observability_logs.py`)

**Purpose**: Validate structured logging and Loki integration

**Key Tests**:
- `test_log_aggregation`: Log collection in Loki
- `test_structured_logging_format`: JSON log structure
- `test_log_correlation_with_traces`: Log-trace correlation
- `test_log_filtering_and_querying`: LogQL queries
- `test_log_retention_policies`: Log retention behavior
- `test_sensitive_data_redaction`: PII/secret redaction

### 4. Integration Tests (`test_observability_integration.py`)

**Purpose**: Validate cross-component integration and end-to-end workflows

**Key Tests**:
- `test_end_to_end_correlation`: Single request across all observability
- `test_multi_service_observability`: Multiple service coordination
- `test_error_propagation_observability`: Error handling visibility
- `test_performance_impact_validation`: Observability overhead
- `test_canary_deployment_observability`: A/B testing visibility
- `test_dashboard_integration`: Grafana dashboard queries
- `test_alert_rule_validation`: Prometheus alerting rules

## ⚙️ Configuration

### Environment Variables

The test suite uses these environment variables:

```bash
# Service URLs (set automatically by Makefile)
TEST_INFERENCE_URL=http://localhost:8080
TEST_PROMETHEUS_URL=http://localhost:9090
TEST_JAEGER_URL=http://localhost:16686
TEST_LOKI_URL=http://localhost:3100
TEST_GRAFANA_URL=http://localhost:3000

# Test configuration
TEST_TIMEOUT=300                 # Test timeout in seconds
LOG_LEVEL=INFO                   # Test log level
PYTHONPATH=/path/to/project      # Python path for imports
```

## 🚀 CI/CD Integration

### GitHub Actions

The test suite runs automatically in GitHub Actions:

```yaml
# .github/workflows/e2e-observability.yml
name: E2E Observability Tests
on:
  push: [main, develop]
  pull_request: [main, develop]
  schedule: [cron: '0 2 * * *']  # Daily at 2 AM UTC
```

**Triggers**:
- **Push/PR**: On changes to services, tests, or configs
- **Schedule**: Daily to catch environment drift
- **Manual**: Via workflow dispatch

**Artifacts**:
- Test results and logs
- Service logs on failure
- Prometheus/Jaeger/Loki query results
- Performance metrics

## 🔧 Troubleshooting

### Common Issues

1. **Services not starting**:
   ```bash
   make logs-service SERVICE=<service_name>
   docker system prune -f
   make reset
   ```

2. **Tests timing out**:
   ```bash
   # Increase timeout
   make test TEST_TIMEOUT=600
   
   # Check service health
   make status
   make verify-endpoints
   ```

3. **Missing observability data**:
   ```bash
   # Generate baseline data manually
   make generate-baseline-data
   
   # Check data propagation
   curl "http://localhost:9090/api/v1/query?query=up"
   curl "http://localhost:16686/api/services"
   ```

### Debug Mode

```bash
# Start services without running tests
make debug

# Then manually investigate
make verify-endpoints
make logs
curl http://localhost:8080/health
```

## 📈 Extending the Test Suite

### Adding New Service Tests

1. **Update service configurations** in `conftest.py`
2. **Add service to Docker Compose** configuration
3. **Update test patterns** and add service-specific tests
4. **Update Makefile** targets for convenience

### Adding New Test Scenarios

1. **Create test file**: `test_observability_<scenario>.py`
2. **Add fixtures**: In `fixtures/` if reusable
3. **Update Makefile**: Add new test target
4. **Document**: Update this README

## 📝 Best Practices

### Test Design
- **Idempotent**: Tests should not interfere with each other
- **Fast**: Use timeouts and efficient queries
- **Resilient**: Handle transient failures gracefully
- **Comprehensive**: Cover happy path, error cases, and edge cases

### Observability Testing
- **Use correlation IDs**: For tracing requests across services
- **Validate data structure**: Not just presence, but format
- **Test at boundaries**: Service interfaces and integrations
- **Monitor test performance**: Observability overhead should be minimal

## 🤝 Contributing

1. **Follow test patterns**: Use existing fixtures and utilities
2. **Add documentation**: Update README for new features
3. **Test locally**: Use `make test` before submitting
4. **Consider CI**: Ensure tests work in GitHub Actions environment
