---
title: Operations
icon: fas fa-cogs
order: 3
---

# Operations Guide

This guide covers operational procedures, troubleshooting, and day-to-day management of the ML inference platform.

## Table of Contents

- [Quick Start](#quick-start)
- [Service Management](#service-management)
- [Health Checks](#health-checks)
- [Troubleshooting](#troubleshooting)
- [Model Management](#model-management)
- [Monitoring & Alerting](#monitoring--alerting)
- [Performance Tuning](#performance-tuning)
- [Maintenance Procedures](#maintenance-procedures)
- [Incident Response](#incident-response)
- [Backup & Recovery](#backup--recovery)

## Quick Start

### Starting the Platform
```bash
# Start all services
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f gateway
docker-compose logs -f model-server
```

### Stopping the Platform
```bash
# Stop all services
docker-compose down

# Stop and remove volumes (WARNING: This removes data)
docker-compose down -v
```

## Service Management

### Gateway Service

**Start/Stop/Restart:**
```bash
docker-compose restart gateway
docker-compose stop gateway
docker-compose start gateway
```

**View Logs:**
```bash
# Follow logs
docker-compose logs -f gateway

# Last 100 lines
docker-compose logs --tail 100 gateway

# Logs from specific time
docker-compose logs --since "2024-01-01T12:00:00" gateway
```

**Scale Gateway:**
```bash
# Scale to 3 instances
docker-compose up -d --scale gateway=3
```

### Model Server (TorchServe)

**Restart Model Server:**
```bash
docker-compose restart model-server
```

**Check Model Status:**
```bash
# List all models
curl http://localhost:8081/models

# Get specific model details
curl http://localhost:8081/models/resnet18

# Check model health
curl http://localhost:8080/ping
```

**Model Lifecycle:**
```bash
# Register new model
curl -X POST "http://localhost:8081/models?url=model.mar&model_name=new_model"

# Scale model workers
curl -X PUT "http://localhost:8081/models/resnet18?min_worker=2&max_worker=4"

# Unregister model
curl -X DELETE "http://localhost:8081/models/resnet18"
```

## Health Checks

### Automated Health Checks

The platform includes built-in health checks accessible via HTTP endpoints:

```bash
# Gateway health
curl http://localhost:8000/health

# Model server health
curl http://localhost:8080/ping

# Database health (via gateway)
curl http://localhost:8000/health | jq '.database'
```

### Manual Health Verification

**End-to-End Test:**
```bash
# Test inference pipeline
curl -X POST http://localhost:8000/api/v1/predict \
  -H "Content-Type: application/json" \
  -d '{
    "model": "resnet18",
    "input": {
      "image_url": "https://example.com/test-image.jpg"
    }
  }'
```

**Component Tests:**
```bash
# Test Prometheus metrics
curl http://localhost:8000/metrics

# Test Grafana
curl http://localhost:3000/api/health

# Test Prometheus
curl http://localhost:9090/-/healthy
```

## Troubleshooting

### Common Issues

#### Gateway Not Starting
```bash
# Check logs for errors
docker-compose logs gateway

# Common fixes:
# 1. Port conflict
netstat -an | grep :8000

# 2. Database connection
docker-compose logs postgres

# 3. Resource constraints
docker system df
docker system prune -f
```

#### Model Server Issues
```bash
# Check TorchServe logs
docker-compose logs model-server

# Common fixes:
# 1. Model loading issues
curl http://localhost:8081/models

# 2. Memory issues
docker stats model-server

# 3. Restart with clean state
docker-compose down
docker volume rm $(docker volume ls -q | grep seraphim)
docker-compose up -d
```

For the complete operations guide including model management, monitoring & alerting, performance tuning, maintenance procedures, incident response, and backup & recovery, see the [full operations documentation](https://github.com/j0c2/project-seraphim/blob/main/docs/operations.md).
