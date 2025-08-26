---
title: Playbooks
icon: fas fa-book
order: 4
---

# Operational Playbooks

This section contains step-by-step operational playbooks for common scenarios in managing the Project Seraphim ML inference platform.

## Available Playbooks

### [Rollback Procedures]({{ site.baseurl }}/playbooks/rollback.html)

Safe model rollback strategies when issues are detected:

1. Freeze deploys
2. Compare baseline vs. candidate canary metrics
3. Execute Helm rollback to previous revision:
   ```bash
   helm rollback seraphim-inference --to-revision $(helm history -n seraphim seraphim-inference -o json | jq -r '.[-2].revision')
   ```
4. Verify health and SLOs on Grafana
5. Post-mortem documentation

## Playbook Structure

Each playbook follows a consistent format:

1. **Situation Assessment** - When to use this playbook
2. **Prerequisites** - Required access, tools, and preparation
3. **Step-by-Step Procedures** - Detailed execution steps
4. **Verification** - How to confirm successful completion
5. **Rollback/Recovery** - What to do if things go wrong
6. **Post-Action** - Documentation and follow-up tasks

## Quick Health Check Script

For routine operations, use our automated health check:

```bash
# Run comprehensive health check
./scripts/health_check.sh

# Example output:
# 🛡️  Project Seraphim Health Check
# ==================================
# 
# === Docker Services ===
# ✓ All Docker services running
# 
# === Service Endpoints ===
# ✓ Gateway Health
# ✓ TorchServe Inference  
# ✓ TorchServe Management
# ✓ Prometheus
# ✓ Grafana
# 
# === Metrics Collection ===
# ✓ Gateway metrics
# ✓ Prometheus targets (4/4 healthy)
# 
# === Functional Tests ===
# ✓ Inference endpoint
# 
# 🚀 Platform is ready for inference requests
# 📊 Monitoring: http://localhost:3000
# 📈 Metrics: http://localhost:9090
# 🔍 API: http://localhost:8000
```

## Common Operations

### Emergency Response

**Service Down:**
```bash
# Quick restart
docker-compose restart [service-name]

# Check logs
docker-compose logs --tail 50 [service-name]

# Full system restart if needed
docker-compose down && docker-compose up -d
```

**High Error Rate:**
```bash
# Check current metrics
curl 'http://localhost:9090/api/v1/query?query=rate(seraphim_inference_requests_total{outcome!="success"}[5m])'

# Rollback canary if needed
# Update CANARY_PERCENT to 0 in docker-compose.yml
docker-compose up -d gateway
```

### Model Management

**Deploy New Model:**
```bash
# 1. Test model locally
# 2. Create model archive
# 3. Register with TorchServe
curl -X POST "http://localhost:8081/models?url=new_model.mar"

# 4. Update gateway configuration
# Edit docker-compose.yml with new model details
docker-compose up -d gateway
```

**Monitor Canary Deployment:**
```bash
# Check traffic split
curl 'http://localhost:9090/api/v1/query?query=sum by (variant) (rate(seraphim_inference_requests_total[1m]))'

# Monitor error rates by variant
curl 'http://localhost:9090/api/v1/query?query=sum by (variant) (rate(seraphim_inference_requests_total{outcome!="success"}[5m]))'
```

## Contributing

When creating new playbooks:

- Use clear, numbered steps
- Include specific commands and expected outputs
- Add verification steps after each major action
- Document any prerequisites or dependencies
- Test procedures in a non-production environment first

## Resources

- **[Operations Guide]({{ site.baseurl }}/tabs/operations)** - Complete operational procedures
- **[Observability Guide]({{ site.baseurl }}/tabs/observability)** - Monitoring and alerting setup
- **[GitHub Repository](https://github.com/j0c2/project-seraphim)** - Source code and issues
