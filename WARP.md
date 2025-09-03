# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Development Commands

### Core Development
```bash
# Create Python virtual environment and install dependencies
make dev-deps

# Run the inference service locally
make run  # Starts FastAPI on localhost:8080

# Run unit tests
make unit
# or
pytest tests/unit -v

# Run specific test file
pytest tests/unit/test_canary_routing.py -v

# Linting and formatting
make lint
# or individually:
black services/ tests/ config/
isort services/ tests/ config/
flake8 services/ tests/ config/
```

### Docker and Services
```bash
# Full stack with Docker Compose (recommended for development)
docker compose up -d --build

# Build TorchServe model server
make ts-build

# Build model archive (MAR file)
make ts-build-mar

# Run end-to-end test with TorchServe
make e2e-ts

# Load testing
make load-test  # Uses Locust
make e2e-local  # Local E2E with uvicorn
```

### Deployment
```bash
# Deploy to Kubernetes (requires cluster setup)
make deploy ENV=dev
make deploy ENV=stage
make deploy ENV=prod

# Build and push Docker images
make docker-build
make docker-push
```

## High-Level Architecture

This is an **AI reliability engineering monorepo** demonstrating production-grade ML inference with canary routing and observability.

### Core Components

1. **FastAPI Gateway (`services/inference/`)**: The main entry point that handles:
   - Canary routing between model versions (baseline vs candidate)
   - Health checks and metrics exposure
   - Fallback logic when TorchServe is unavailable
   - Distributed tracing and structured logging

2. **TorchServe Model Server (`services/model-server/`)**: 
   - Serves ML models with versioning support
   - Custom handler for text processing
   - Management API for dynamic model loading

3. **Shared Observability (`services/shared/`)**: 
   - Common utilities for logging and tracing
   - OpenTelemetry integration with Jaeger
   - JSON structured logging with correlation IDs

4. **Infrastructure as Code (`config/infra/`)**:
   - Helm charts for Kubernetes deployment
   - Terraform configurations (referenced but not fully implemented)

5. **Observability Stack (`config/observe/`)**:
   - Prometheus metrics and alerting rules
   - Grafana dashboards
   - Loki for log aggregation
   - Jaeger for distributed tracing

### Canary Routing Logic

The gateway implements sophisticated routing with three strategies:
1. **Random**: Based on `CANARY_PERCENT` (0-100)
2. **Sticky**: Consistent routing per user using `X-User-Id` header hash
3. **Force**: Override with `X-Canary: candidate|baseline` header

### Key Environment Variables

- `TS_URL`: TorchServe baseline URL
- `TS_URL_CANDIDATE`: TorchServe candidate URL  
- `MODEL_NAME_BASELINE/CANDIDATE`: Model names
- `MODEL_VERSION_BASELINE/CANDIDATE`: Model versions
- `CANARY_PERCENT`: Traffic split (0-100)
- `TS_TIMEOUT_MS`: Request timeout
- `LOG_LEVEL`: Logging verbosity

### Testing Strategy

- **Unit Tests**: Focus on routing logic, percentage parsing, endpoint behavior
- **E2E Tests**: Full service testing with mocked TorchServe using `respx`
- **Load Tests**: Locust-based performance testing with SLO validation
- **Integration Tests**: Docker Compose stack testing

### CI/CD Workflows

The project uses GitHub Actions with:
- **CI Pipeline** (`.github/workflows/ci.yml`): Multi-Python version testing, Docker builds, security scanning
- **CD Pipeline** (`.github/workflows/cd.yml`): Staged deployments with approval gates
- Change detection to optimize workflow execution
- Artifact management and rollback capabilities

### Observability Features

- **Metrics**: Prometheus metrics for request counts, latency, error rates per variant
- **Logging**: Structured JSON logs with correlation IDs
- **Tracing**: Distributed traces across service boundaries
- **Dashboards**: Pre-configured Grafana dashboards for SLO monitoring

### Service Endpoints

- `/predict`: Main inference endpoint
- `/healthz`: Basic health check
- `/readyz`: Readiness check (validates TorchServe connectivity)
- `/metrics`: Prometheus metrics
- `/observability/*`: Observability management endpoints

### Development Tips

- The codebase uses `black` with 88-character line length
- Tests are organized in `tests/unit/` and `tests/e2e/`
- All services share the observability library for consistent logging/tracing
- Docker Compose provides full local development environment
- Makefile provides convenient development commands
- TorchServe uses a dummy text classification handler for demonstration
