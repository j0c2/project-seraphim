---
layout: page
title: Observability
icon: fas fa-chart-line
---

# Observability Guide

This guide explains the local observability stack (Prometheus + Grafana), the metrics exposed by the gateway and TorchServe, useful PromQL queries, dashboard usage, and troubleshooting tips. It also includes notes for running in Kubernetes.

## Stack Overview

- FastAPI Gateway (services/inference)
  - Exposes /metrics with Prometheus counters and histograms
  - Custom metrics:
    - seraphim_inference_requests_total{variant, outcome}
      - variant: baseline|candidate
      - outcome: success|timeout|http_error|error
    - seraphim_inference_latency_seconds_bucket/sum/count{variant}
- TorchServe (services/model-server)
  - Metrics endpoint at 9082/metrics (Prometheus format enabled)
  - Note: depending on the upstream image, some named metrics may be sparse; health still shows "up" in Prometheus
- Prometheus (config/observe/prometheus)
  - Scrapes the gateway and TorchServe endpoints
- Grafana (config/observe/grafana)
  - Provisioned Prometheus datasource
  - Auto-provisioned dashboard: Seraphim Inference Overview

## Local Endpoints and Ports

- Gateway (FastAPI)
  - http://localhost:8088/healthz, /readyz, /metrics, /predict
- TorchServe
  - Inference: http://localhost:9080
  - Management: http://localhost:9081
  - Metrics: http://localhost:9082/metrics
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (default admin/admin)

## Bring It Up Locally

```bash
# From repo root
docker compose up -d --build

# Check Prometheus targets
curl -s 'http://localhost:9090/api/v1/targets' | jq '.data.activeTargets | map({job: .labels.job, health: .health})'

# Generate traffic so metrics appear
for i in {1..100}; do \
  curl -s -X POST http://localhost:8088/predict -H 'Content-Type: application/json' -d '{"text": "load'$i'"}' >/dev/null; \
  sleep 0.05; \
done
```

Open Grafana at http://localhost:3000 and select the "Seraphim Inference Overview" dashboard.

## PromQL Cookbook

- RPS (1 minute rate)

```promql
sum(rate(seraphim_inference_requests_total[1m]))
```

- Error percentage over 5 minutes

```promql
(
  sum(rate(seraphim_inference_requests_total{outcome!="success"}[5m]))
  /
  sum(rate(seraphim_inference_requests_total[5m]))
) * 100
```

- p95 latency (milliseconds)

```promql
histogram_quantile(
  0.95,
  sum by (le) (rate(seraphim_inference_latency_seconds_bucket[5m]))
) * 1000
```

- Requests by variant (baseline vs candidate)

```promql
sum by (variant) (rate(seraphim_inference_requests_total[1m]))
```

- Requests by outcome (success, timeout, http_error, error)

```promql
sum by (outcome) (rate(seraphim_inference_requests_total[1m]))
```

- TorchServe RPS (if metrics are present)

```promql
sum(rate(ts_inference_requests_total[1m]))
```

## Dashboard Details

The dashboard at config/observe/grafana/dashboards/seraphim.json includes:

- RPS (1m) – total request rate
- Error % (5m) – rolling percentage of non-success outcomes
- Latency p95 (ms) – SLO-oriented high percentile
- Requests by Variant (1m) – canary split visibility
- Requests by Outcome (1m) – error mode visibility
- TorchServe Inference RPS (1m) – optional depending on TorchServe export

Panels use the PromQL queries listed above. You can customize the dashboard in Grafana or update the JSON.

## Troubleshooting

- "No data" in Grafana
  - Ensure you sent traffic to /predict; without traffic, only default Python/process metrics are present
  - Confirm Prometheus targets are "up": http://localhost:9090 -> Status -> Targets
- TorchServe metrics empty
  - The endpoint may respond 200 but not emit named series in some images/configs
  - Metric job health still shows up; rely on gateway metrics for most views
  - Ensure metrics are enabled: metrics_format=prometheus in TorchServe config
- Timeouts/HTTP errors
  - To simulate timeouts, reduce gateway TS_TIMEOUT_MS (e.g., 50) and send traffic
  - To simulate HTTP errors, stop TorchServe temporarily: `docker compose stop model-server`
- Grafana login
  - Default local credentials are admin/admin; change via env vars GF_SECURITY_ADMIN_USER/PASSWORD

## Kubernetes Notes

- Charts for gateway and TorchServe are at config/infra/helm
- For Prometheus/Grafana in-cluster, consider kube-prometheus-stack or your organization's stack
- Gateway env variables are configured via Helm values (see values.yaml)
- Multi-arch clusters: you can use nodeSelector to schedule TorchServe on amd64 nodes if needed

## Example Alerts (Prometheus rules file)

The local compose rules file is empty (config/observe/prometheus/rules.yml). Example alerts:

```yaml
# config/observe/prometheus/rules.yml
# An example of file-based rules (not the Operator CRD format)
groups:
  - name: seraphim.rules
    rules:
      - alert: HighErrorRate
        expr: (
          sum(rate(seraphim_inference_requests_total{outcome!="success"}[5m]))
          /
          sum(rate(seraphim_inference_requests_total[5m]))
        ) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate (>5%)"

      - alert: HighLatencyP95
        expr: histogram_quantile(0.95, sum by (le) (rate(seraphim_inference_latency_seconds_bucket[5m]))) > 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High p95 latency (>500ms)"
```

## Security & Production Considerations

- Don't expose Prometheus and Grafana publicly without authentication
- Configure Grafana auth and SSL when deploying outside local dev
- Use scrape labels and relabeling if you add more services
- Consider remote_write to a centralized Prometheus/TSDB if needed

## Extending Metrics

- Gateway metrics can be extended with more labels (e.g., route, tenant)
- Add panels for p50, p99, per-variant latencies:
  - p50: histogram_quantile(0.50, …)
  - p99: histogram_quantile(0.99, …)
- Add TS model/version dimensions if TorchServe exposes them

---

For questions or enhancements, see the code under services/inference/app/main.py and the observability configs in config/observe/.
