---
layout: default
title: Operations Guide
description: Deployment, troubleshooting, and maintenance procedures for Project Seraphim
nav_order: 3
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

### Database Operations

**Connect to PostgreSQL:**
```bash
# Using docker
docker-compose exec postgres psql -U seraphim -d seraphim

# Using local client
psql -h localhost -p 5432 -U seraphim -d seraphim
```

**Backup Database:**
```bash
# Create backup
docker-compose exec postgres pg_dump -U seraphim seraphim > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore from backup
docker-compose exec -T postgres psql -U seraphim -d seraphim < backup.sql
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

#### Performance Issues
```bash
# Check resource usage
docker stats

# Check system resources
top
df -h
free -m

# Check network connectivity
ping model-server
telnet model-server 8080
```

### Debugging Steps

1. **Check Service Status:**
   ```bash
   docker-compose ps
   ```

2. **Review Logs:**
   ```bash
   docker-compose logs --tail 50 [service-name]
   ```

3. **Verify Network Connectivity:**
   ```bash
   docker network ls
   docker network inspect seraphim_default
   ```

4. **Check Resource Usage:**
   ```bash
   docker stats
   ```

5. **Test Individual Components:**
   ```bash
   # Test each service endpoint individually
   curl http://localhost:8000/health
   curl http://localhost:8080/ping
   curl http://localhost:5432  # Should fail but confirm port is open
   ```

## Model Management

### Model Deployment

**Deploy New Model:**
```bash
# 1. Prepare model archive (.mar file)
torch-model-archiver --model-name new_model \
  --version 1.0 \
  --model-file model.py \
  --serialized-file model.pth \
  --handler image_classifier

# 2. Copy to model store
cp new_model.mar models/

# 3. Register with TorchServe
curl -X POST "http://localhost:8081/models?url=new_model.mar"

# 4. Verify deployment
curl http://localhost:8081/models/new_model
```

**Model Rollback:**
```bash
# 1. Unregister current version
curl -X DELETE "http://localhost:8081/models/problematic_model"

# 2. Register previous version
curl -X POST "http://localhost:8081/models?url=previous_model_v1.mar&model_name=model"

# 3. Update gateway configuration if needed
# Edit docker-compose.yml or environment variables
```

### A/B Testing & Canary Deployment

**Setup Canary:**
```bash
# Register canary version
curl -X POST "http://localhost:8081/models?url=model_v2_canary.mar&model_name=model_v2"

# Configure routing in gateway (update environment variables)
# CANARY_MODEL=model_v2
# CANARY_PERCENTAGE=10
```

**Monitor Canary:**
```bash
# Check metrics in Grafana
# - Request distribution by variant
# - Error rates by model version
# - Latency comparison

# Or query Prometheus directly
curl 'http://localhost:9090/api/v1/query?query=inference_requests_total{variant="canary"}'
```

## Monitoring & Alerting

### Key Metrics to Monitor

1. **Request Rate:** `rate(inference_requests_total[5m])`
2. **Error Rate:** `rate(inference_requests_total{outcome="error"}[5m])`
3. **Latency:** `histogram_quantile(0.95, inference_request_duration_seconds_bucket)`
4. **Model Server Health:** `up{job="torchserve"}`

### Setting Up Alerts

Create `prometheus/alerts.yml`:
```yaml
groups:
- name: inference.rules
  rules:
  - alert: HighErrorRate
    expr: rate(inference_requests_total{outcome="error"}[5m]) > 0.1
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "High error rate detected"
      description: "Error rate is {{ $value }} errors per second"

  - alert: ServiceDown
    expr: up{job="gateway"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Gateway service is down"
```

### Prometheus Queries

**Useful queries for operations:**
```promql
# Request rate by model
rate(inference_requests_total[5m])

# Error percentage
100 * rate(inference_requests_total{outcome="error"}[5m]) / rate(inference_requests_total[5m])

# Average response time
rate(inference_request_duration_seconds_sum[5m]) / rate(inference_request_duration_seconds_count[5m])

# Memory usage
container_memory_usage_bytes{name="seraphim_gateway_1"}

# CPU usage
rate(container_cpu_usage_seconds_total{name="seraphim_gateway_1"}[5m])
```

## Performance Tuning

### Gateway Optimization

**Environment Variables:**
```bash
# In docker-compose.yml
environment:
  - WORKERS=4                    # Increase for more concurrent requests
  - MAX_CONNECTIONS=1000         # Database connection pool
  - TIMEOUT=30                   # Request timeout
  - LOG_LEVEL=WARNING            # Reduce logging overhead
```

**Database Connection Pooling:**
```python
# In services/gateway/database.py
SQLALCHEMY_DATABASE_URL = "postgresql://user:pass@host/db?pool_size=20&max_overflow=30"
```

### Model Server Optimization

**TorchServe Configuration:**
```properties
# In config/torchserve.properties
default_workers_per_model=4
max_workers=8
max_response_size=655360000
model_store=/opt/ml/model
```

**Resource Allocation:**
```yaml
# In docker-compose.yml for model-server
deploy:
  resources:
    limits:
      cpus: '4.0'
      memory: 8G
    reservations:
      cpus: '2.0'
      memory: 4G
```

### Database Optimization

**PostgreSQL Configuration:**
```bash
# Connect to postgres
docker-compose exec postgres psql -U seraphim

# Optimize for read-heavy workloads
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';
SELECT pg_reload_conf();
```

## Maintenance Procedures

### Regular Maintenance Tasks

**Daily:**
```bash
# Check service health
./scripts/health_check.sh

# Review error logs
docker-compose logs --since="24h" | grep ERROR

# Check disk usage
docker system df
```

**Weekly:**
```bash
# Clean up old containers and images
docker system prune -f

# Backup database
./scripts/backup_db.sh

# Review performance metrics
# - Check Grafana dashboards
# - Analyze slow queries
# - Review resource utilization
```

**Monthly:**
```bash
# Update dependencies
docker-compose pull

# Security audit
# - Review access logs
# - Update passwords/tokens
# - Check for security updates

# Performance review
# - Analyze traffic patterns
# - Plan capacity adjustments
# - Review SLA metrics
```

### Log Management

**Log Rotation:**
```bash
# Configure in docker-compose.yml
logging:
  driver: "json-file"
  options:
    max-size: "100m"
    max-file: "3"
```

**Log Analysis:**
```bash
# Find errors in the last hour
docker-compose logs --since="1h" | grep -i error

# Analyze request patterns
docker-compose logs gateway | grep "POST /api/v1/predict" | tail -100

# Check slow requests
docker-compose logs gateway | grep "duration" | awk '{print $NF}' | sort -n | tail -10
```

## Incident Response

### Incident Classification

**P0 - Critical:** Service completely down, data loss
**P1 - High:** Significant performance degradation, partial outage
**P2 - Medium:** Minor issues, workaround available
**P3 - Low:** Cosmetic issues, no user impact

### Response Procedures

**P0/P1 Response:**
1. **Immediate Actions:**
   ```bash
   # Check overall system status
   docker-compose ps
   
   # Quick restart if needed
   docker-compose restart [failing-service]
   
   # Check resource usage
   docker stats
   ```

2. **Investigation:**
   ```bash
   # Collect logs
   docker-compose logs --since="1h" > incident_logs_$(date +%s).txt
   
   # Check metrics
   curl http://localhost:9090/api/v1/query?query=up
   ```

3. **Escalation:**
   - Notify relevant team members
   - Create incident ticket
   - Begin detailed investigation

### Recovery Procedures

**Service Recovery:**
```bash
# Full system restart
docker-compose down
docker-compose up -d

# Database recovery
docker-compose exec postgres pg_ctl restart

# Model server recovery
docker-compose restart model-server
curl -X POST "http://localhost:8081/models?url=resnet18.mar"
```

**Data Recovery:**
```bash
# Restore from backup
docker-compose down
docker volume rm seraphim_postgres_data
docker-compose up -d postgres
# Wait for postgres to be ready
docker-compose exec -T postgres psql -U seraphim -d seraphim < backup.sql
docker-compose up -d
```

## Backup & Recovery

### Automated Backup Script

Create `scripts/backup.sh`:
```bash
#!/bin/bash
BACKUP_DIR="/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# Database backup
docker-compose exec -T postgres pg_dump -U seraphim seraphim | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"

# Model files backup
tar -czf "$BACKUP_DIR/models_$DATE.tar.gz" models/

# Configuration backup
tar -czf "$BACKUP_DIR/config_$DATE.tar.gz" config/ docker-compose.yml

# Cleanup old backups (keep last 7 days)
find $BACKUP_DIR -name "*.gz" -mtime +7 -delete

echo "Backup completed: $DATE"
```

### Disaster Recovery

**Complete System Recovery:**
1. **Restore Infrastructure:**
   ```bash
   git clone <repository>
   cd project-seraphim
   ```

2. **Restore Data:**
   ```bash
   # Restore database
   docker-compose up -d postgres
   gunzip -c backup_db.sql.gz | docker-compose exec -T postgres psql -U seraphim -d seraphim
   
   # Restore models
   tar -xzf backup_models.tar.gz
   
   # Restore configuration
   tar -xzf backup_config.tar.gz
   ```

3. **Start Services:**
   ```bash
   docker-compose up -d
   ```

4. **Verify Recovery:**
   ```bash
   # Test all endpoints
   curl http://localhost:8000/health
   curl http://localhost:8080/ping
   
   # Test inference
   curl -X POST http://localhost:8000/api/v1/predict -H "Content-Type: application/json" -d '{"model":"resnet18","input":{}}'
   ```

### Recovery Testing

**Monthly Recovery Drill:**
```bash
# 1. Create test backup
./scripts/backup.sh

# 2. Destroy test environment
docker-compose down -v

# 3. Restore from backup
./scripts/restore.sh latest

# 4. Verify functionality
./scripts/health_check.sh
```

## Security Considerations

### Access Control
- Change default passwords
- Use environment variables for secrets
- Implement API authentication
- Regular security updates

### Network Security
- Use HTTPS in production
- Implement rate limiting
- Monitor access logs
- Network segmentation

### Data Protection
- Encrypt sensitive data
- Regular backups
- Access logging
- Data retention policies

---

For additional help:
- Check the [Observability Guide](observability.md)
- Review [README](../README.md) for setup instructions
- Contact the development team for complex issues
