# 🛡️ Project Seraphim

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI/CD](https://github.com/yourhandle/project-seraphim/actions/workflows/ci.yml/badge.svg)](https://github.com/yourhandle/project-seraphim/actions)
[![Made with Python](https://img.shields.io/badge/Python-3.10+-yellow.svg)](https://www.python.org/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.29+-brightgreen.svg)](https://kubernetes.io/)

---

**Project-Seraphim** is an **AI reliability engineering monorepo**.  
It demonstrates how to run ML/LLM inference with production-grade guardrails:

- ✅ **SLO enforcement** for latency, availability, and error rates  
- 🔄 **Canary & rollback workflows** for safe model releases  
- 📈 **Drift detection** using embeddings and prediction distributions  
- 🔧 **Auto-scaling** on GPU/CPU usage and request throughput  
- 🧪 **Failure injection** and chaos experiments to validate resilience  

---

## 🚀 Quick Start

### Using Docker Compose (Recommended for Local Dev)

```bash
# Clone repo
git clone https://github.com/yourhandle/project-seraphim.git
cd project-seraphim

# Start services with Docker Compose
docker compose up -d --build

# Verify services are running
curl http://localhost:8088/healthz  # Gateway health
curl http://localhost:9081/models   # TorchServe models

# Test inference (10% canary to v2.0, 90% to v1.0)
curl -X POST http://localhost:8088/predict \
  -H "Content-Type: application/json" \
  -d '{"text": "hello world"}'

# Force specific model version
curl -X POST http://localhost:8088/predict \
  -H "Content-Type: application/json" \
  -H "X-Canary: candidate" \
  -d '{"text": "test canary"}'
```

### Using Kubernetes

```bash
# Bootstrap cluster + observability stack
make infra-apply

# Deploy inference service + monitoring
make deploy

# Run load test + watch dashboards  
make load-test

👉 View Grafana dashboards at http://localhost:3000 and track SLOs in real time.
```

---

## 🏗️ Architecture

```mermaid
graph TB
    Client[Client] --> GW[FastAPI Gateway]
    GW --> |90%| TS1[TorchServe v1.0]
    GW --> |10%| TS2[TorchServe v2.0]
    GW --> Metrics[Prometheus]
    Metrics --> Grafana
    GW -.Fallback.-> Cache[Fallback Logic]
```

### Components

- **FastAPI Gateway** (`services/inference/`): Handles routing, canary logic, and fallback
- **TorchServe** (`services/model-server/`): Serves ML models with versioning support
- **Observability** (`config/observe/`): Prometheus metrics and Grafana dashboards
- **Reliability** (`config/reliability/`): Canary evaluation, chaos testing, drift detection

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|  
| `TS_URL` | TorchServe URL for baseline | `http://localhost:8080` |
| `TS_URL_CANDIDATE` | TorchServe URL for candidate | Same as `TS_URL` |
| `MODEL_NAME_BASELINE` | Baseline model name | `custom-text` |
| `MODEL_VERSION_BASELINE` | Baseline version | `1.0` |
| `MODEL_NAME_CANDIDATE` | Candidate model name | `custom-text` |
| `MODEL_VERSION_CANDIDATE` | Candidate version | `2.0` |
| `CANARY_PERCENT` | % traffic to candidate (0-100) | `10` |
| `CANARY_STICKY_HEADER` | Header for sticky routing | `X-User-Id` |
| `TS_TIMEOUT_MS` | Timeout for TorchServe calls | `3000` |

### Canary Routing

The gateway supports three routing modes:

1. **Random**: Default behavior, routes based on `CANARY_PERCENT`
2. **Sticky**: Uses hash of `X-User-Id` header for consistent routing
3. **Force**: Override with `X-Canary: candidate` or `X-Canary: baseline`

## 🧪 Testing

```bash
# Run unit tests
pytest tests/unit/

# Run canary routing tests
pytest tests/unit/test_canary_routing.py -v

# Run load tests
locust -f tests/e2e/locustfile.py --host http://localhost:8088
```

## 📊 Monitoring

- **Metrics**: Exposed at `/metrics` on both gateway and TorchServe
- **Dashboards**: Pre-configured Grafana dashboards in `config/observe/grafana/`
- **Alerts**: Prometheus rules in `config/observe/prometheus/`

## 🚢 Deployment

### Docker (Apple Silicon / M1)

The TorchServe image uses `linux/amd64` platform to ensure compatibility:

```yaml
services:
  model-server:
    platform: linux/amd64
    build:
      platforms:
        - linux/amd64
```

### Kubernetes

```bash
# Deploy to specific environment
helm upgrade --install seraphim-inference \
  config/infra/helm/seraphim-inference \
  -f config/infra/helm/seraphim-inference/values-${ENV}.yaml
```

---

## 📖 About the Name

Derived from Seraphim — guardians and watchers - this project acts as a guardian for AI systems, ensuring reliability, trust, and resilience in production ML.
