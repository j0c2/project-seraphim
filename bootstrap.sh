#!/usr/bin/env bash
# bootstrap.sh — generate initial file structure and starter code for project-seraphim
# Usage:
#   bash bootstrap.sh [--repo-root PATH] [--require-k8s]
#   bash bootstrap.sh project-seraphim

set -euo pipefail
set -x   # Enable debug logging so users see each command executed

REPO_ROOT="project-seraphim"
REQUIRE_K8S=0

# Simple arg parsing (supports positional repo-root or --repo-root flag)
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="${2:-$REPO_ROOT}"; shift 2 ;;
    --require-k8s)
      REQUIRE_K8S=1; shift ;;
    *)
      REPO_ROOT="$1"; shift ;;
  esac
done

preflight() {
  # Always require python3 and pip (via python3 -m pip)
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: required tool 'python3' is not installed or not in PATH" >&2
    exit 1
  fi
  if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "Error: python3 -m pip not available; please install pip for python3" >&2
    exit 1
  fi

  if [[ "$REQUIRE_K8S" -eq 1 ]]; then
    for cmd in helm kubectl jq docker; do
      if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: required tool '$cmd' is not installed or not in PATH" >&2
        exit 1
      fi
    done
  fi
}

ensure_dir() {
  mkdir -p "$1"
}

ensure_file() {
  # ensure_file <path> ; content is provided via stdin (heredoc)
  local path="$1"; shift || true
  if [[ -f "$path" ]]; then
    return 0
  fi
  mkdir -p "$(dirname "$path")"
  cat > "$path"
}

preflight

ensure_dir "$REPO_ROOT"
cd "$REPO_ROOT"

################################################################################
# Ensure Python package layout so 'from config....' imports work in tests
################################################################################
ensure_dir config/reliability/drift
ensure_dir config/reliability/canary
ensure_dir config/reliability/chaos

ensure_file config/__init__.py << 'EOF_INIT_CONFIG'
__all__ = ['reliability']
EOF_INIT_CONFIG

ensure_file config/reliability/__init__.py << 'EOF_INIT_RELIABILITY'
__all__ = ['drift','canary','chaos']
EOF_INIT_RELIABILITY

# Empty package markers (idempotent)
ensure_file config/reliability/drift/__init__.py << 'EOF_EMPTY'
EOF_EMPTY
ensure_file config/reliability/canary/__init__.py << 'EOF_EMPTY'
EOF_EMPTY
ensure_file config/reliability/chaos/__init__.py << 'EOF_EMPTY'
EOF_EMPTY

# Optional: baseline detector implementation (only if missing)
if [[ ! -f config/reliability/drift/detector.py ]]; then
ensure_file config/reliability/drift/detector.py << 'EOF_DETECTOR'
"""Simple drift detection utilities.

- Embedding cosine distance threshold
- Probability distribution KL divergence
"""
from typing import List
import numpy as np

def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    a_n = a / (np.linalg.norm(a) + 1e-9)
    b_n = b / (np.linalg.norm(b) + 1e-9)
    return 1.0 - float(np.dot(a_n, b_n))

def kl_divergence(p: np.ndarray, q: np.ndarray) -> float:
    eps = 1e-9
    p = np.clip(p, eps, 1)
    q = np.clip(q, eps, 1)
    return float(np.sum(p * (np.log(p) - np.log(q))))

def is_drifted_cosine(ref: List[np.ndarray], cur: List[np.ndarray], threshold: float = 0.15) -> bool:
    dists = [cosine_distance(r, c) for r, c in zip(ref, cur)]
    return float(np.percentile(dists, 95)) > threshold
EOF_DETECTOR
fi

# Pytest path helper so local package resolves without install
ensure_dir tests
ensure_file tests/conftest.py << 'EOF_CONFTEST'
# Ensure repository root is importable for tests
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
EOF_CONFTEST

################################################################################
# deploy
################################################################################
ensure_dir deploy/k8s
ensure_file deploy/k8s/namespace.yaml << 'EOF_NS'
apiVersion: v1
kind: Namespace
metadata:
  name: seraphim
EOF_NS

ensure_dir deploy/environment/dev
# Dev overlay kustomization with namespace, labels, and prefix for clear scoping
ensure_file deploy/environment/dev/kustomization.yaml << 'EOF_KUSTO_DEV'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: seraphim
namePrefix: dev-

commonLabels:
  app: seraphim
  env: dev

resources:
  - ../../k8s/namespace.yaml
EOF_KUSTO_DEV

################################################################################
# docs
################################################################################
ensure_dir docs/playbooks
ensure_file docs/playbooks/rollback.md << 'EOF_ROLLBACK'
# Rollback Playbook

1. Freeze deploys.
2. Compare baseline vs. candidate canary metrics.
3. If SLO breached or canary fails, execute Helm rollback to the previous revision:
   ```bash
   helm rollback seraphim-inference --to-revision $(helm history -n seraphim seraphim-inference -o json | jq -r '.[-2].revision')
   ```
   > Alternatively, run `helm history seraphim-inference -n seraphim` and choose a valid revision number manually.
4. Verify health and SLOs on Grafana.
5. Post-mortem notes in docs/playbooks/.
EOF_ROLLBACK

################################################################################
# tests: unit + e2e
################################################################################
ensure_dir tests/unit
ensure_file tests/unit/test_detector.py << 'EOF_T_DETECTOR'
import numpy as np
from config.reliability.drift.detector import cosine_distance, is_drifted_cosine

def test_cosine_distance_bounds():
    a = np.array([1.0, 0.0])
    b = np.array([1.0, 0.0])
    assert abs(cosine_distance(a, b)) < 1e-6

def test_is_drifted_cosine():
    ref = [np.array([1.0, 0.0]) for _ in range(10)]
    cur = [np.array([0.0, 1.0]) for _ in range(10)]
    assert is_drifted_cosine(ref, cur, threshold=0.1) is True
EOF_T_DETECTOR

ensure_dir tests/e2e
ensure_file tests/e2e/locustfile.py << 'EOF_LOCUST'
import os
from locust import HttpUser, task, between, tag

SLO_P95_MS = int(os.getenv("SLO_P95_MS", "100"))  # default 100ms
BASE_HOST = os.getenv("LOCUST_HOST")  # allow runtime override

class InferenceUser(HttpUser):
    wait_time = between(0.01, 0.1)
    if BASE_HOST:
        host = BASE_HOST

    @tag("predict")
    @task
    def predict(self):
        # Use catch_response to record failures on non-200 or slow responses
        with self.client.post("/predict", json={"text": "hello world"}, name="predict", catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"non-200 status: {r.status_code}")
                return
            latency_ms = r.elapsed.total_seconds() * 1000.0
            if latency_ms > SLO_P95_MS:
                r.failure(f"latency {latency_ms:.1f}ms > SLO {SLO_P95_MS}ms")
            else:
                r.success()
EOF_LOCUST

################################################################################
# dev requirements for local + CI installs
################################################################################
ensure_file requirements-dev.txt << 'EOF_REQ_DEV'
pytest
numpy
locust
black
isort
flake8
EOF_REQ_DEV

################################################################################
# TorchServe model-server scaffold (idempotent)
################################################################################
ensure_dir services/model-server/model-store
ensure_dir services/model-server/scripts

# TorchServe config.properties — bind to all interfaces inside the container
ensure_file services/model-server/config.properties << 'EOF_MS_CONF'
inference_address=http://0.0.0.0:8080
management_address=http://0.0.0.0:8081
metrics_address=http://0.0.0.0:8082
model_store=/home/model-server/model-store
number_of_netty_threads=4
EOF_MS_CONF

# TorchServe entrypoint with optional sample model registration
ensure_file services/model-server/scripts/start.sh << 'EOF_MS_START'
#!/usr/bin/env bash
set -euo pipefail
trap 'torchserve --stop || true' EXIT

SAMPLE_MODEL=${SAMPLE_MODEL:-false}
MODEL_NAME=${MODEL_NAME:-squeezenet}
MODEL_URL=${MODEL_URL:-https://torchserve.pytorch.org/mar_files/squeezenet1_1.mar}

# Start TorchServe
torchserve --start --model-store /home/model-server/model-store \
  --ts-config /home/model-server/config.properties

# Wait for management API to be ready
for i in {1..50}; do
  if curl -sf --max-time 0.3 http://127.0.0.1:8081/ping >/dev/null; then
    break
  fi
  sleep 0.2
done

if [[ "$SAMPLE_MODEL" == "true" ]]; then
  echo "Downloading sample model: $MODEL_NAME"
  curl -fsSL "$MODEL_URL" -o "/home/model-server/model-store/${MODEL_NAME}.mar"
  curl -fsSL -X POST \
    "http://127.0.0.1:8081/models?url=${MODEL_NAME}.mar&model_name=${MODEL_NAME}&initial_workers=1"
fi

# Stream logs
exec tail -F /home/model-server/logs/ts_log.log
EOF_MS_START

# TorchServe Dockerfile (pinned version, installs curl for health/registration)
ensure_file services/model-server/Dockerfile << 'EOF_MS_DOCKER'
FROM pytorch/torchserve:0.11.0-cpu

USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /home/model-server
COPY config.properties /home/model-server/config.properties
COPY scripts/start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh
RUN mkdir -p /home/model-server/model-store

EXPOSE 8080 8081 8082
CMD ["/usr/local/bin/start.sh"]
EOF_MS_DOCKER

################################################################################
# services: inference (FastAPI) scaffold if missing (idempotent)
################################################################################
ensure_dir services/inference/app
ensure_file services/inference/app/main.py << 'EOF_INF_MAIN'
from fastapi import FastAPI
from pydantic import BaseModel
import time, random

app = FastAPI(title="Seraphim Inference API", version="0.1.0")

class PredictRequest(BaseModel):
    text: str

class PredictResponse(BaseModel):
    prediction: str
    version: str
    latency_ms: float

MODEL_VERSION = "v0"

@app.get("/healthz")
def health():
    return {"ok": True, "version": MODEL_VERSION}

@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    start = time.time()
    time.sleep(random.uniform(0.005, 0.02))
    pred = "positive" if (len(req.text) % 2 == 0) else "negative"
    return PredictResponse(prediction=pred, version=MODEL_VERSION, latency_ms=(time.time() - start) * 1000.0)
EOF_INF_MAIN

ensure_file services/inference/requirements.txt << 'EOF_INF_REQ'
fastapi==0.111.0
uvicorn[standard]==0.30.0
pydantic==2.7.1
prometheus-client==0.20.0
EOF_INF_REQ

ensure_file services/inference/Dockerfile << 'EOF_INF_DOCKER'
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
EOF_INF_DOCKER

################################################################################
# Helm charts: inference + TorchServe (idempotent)
################################################################################
# Inference chart
ensure_dir config/infra/helm/seraphim-inference/templates
ensure_file config/infra/helm/seraphim-inference/Chart.yaml << 'EOF_INF_CHART'
apiVersion: v2
name: seraphim-inference
version: 0.1.0
appVersion: "0.1.0"
description: Inference service with SLOs for Project-Seraphim
EOF_INF_CHART

ensure_file config/infra/helm/seraphim-inference/values.yaml << 'EOF_INF_VALUES'
image:
  repository: seraphim-inference
  tag: dev
  pullPolicy: IfNotPresent
replicaCount: 2
service:
  type: ClusterIP
  port: 80
hpa:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi
EOF_INF_VALUES

ensure_file config/infra/helm/seraphim-inference/templates/deployment.yaml << 'EOF_INF_DEPLOY'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: seraphim-inference
  labels:
    app: seraphim-inference
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app: seraphim-inference
  template:
    metadata:
      labels:
        app: seraphim-inference
    spec:
      containers:
        - name: app
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - containerPort: 8080
          readinessProbe:
            httpGet: { path: /healthz, port: 8080 }
            initialDelaySeconds: 3
            periodSeconds: 5
          livenessProbe:
            httpGet: { path: /healthz, port: 8080 }
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
{{- toYaml .Values.resources | nindent 12 }}
---
apiVersion: v1
kind: Service
metadata:
  name: seraphim-inference
spec:
  type: {{ .Values.service.type }}
  selector:
    app: seraphim-inference
  ports:
    - name: http
      port: {{ .Values.service.port }}
      targetPort: 8080
---
{{- if .Values.hpa.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: seraphim-inference
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: seraphim-inference
  minReplicas: {{ .Values.hpa.minReplicas }}
  maxReplicas: {{ .Values.hpa.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.hpa.targetCPUUtilizationPercentage }}
{{- end }}
EOF_INF_DEPLOY

# Model-server chart
ensure_dir config/infra/helm/seraphim-model-server/templates
ensure_file config/infra/helm/seraphim-model-server/Chart.yaml << 'EOF_MS_CHART'
apiVersion: v2
name: seraphim-model-server
version: 0.1.0
appVersion: "0.1.0"
description: TorchServe model server for Project-Seraphim
EOF_MS_CHART

ensure_file config/infra/helm/seraphim-model-server/values.yaml << 'EOF_MS_VALUES'
image:
  repository: seraphim-model-server
  tag: dev
  pullPolicy: IfNotPresent
replicaCount: 1
service:
  type: ClusterIP
  ports:
    inference: 8080
    management: 8081
    metrics: 8082
env:
  SAMPLE_MODEL: "true"
resources:
  requests:
    cpu: 500m
    memory: 1Gi
  limits:
    cpu: 2000m
    memory: 4Gi
EOF_MS_VALUES

ensure_file config/infra/helm/seraphim-model-server/templates/deployment.yaml << 'EOF_MS_DEPLOY'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: seraphim-model-server
  labels:
    app: seraphim-model-server
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app: seraphim-model-server
  template:
    metadata:
      labels:
        app: seraphim-model-server
    spec:
      containers:
        - name: torchserve
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          env:
            - name: SAMPLE_MODEL
              value: {{ .Values.env.SAMPLE_MODEL | quote }}
          ports:
            - containerPort: {{ .Values.service.ports.inference }}
            - containerPort: {{ .Values.service.ports.management }}
            - containerPort: {{ .Values.service.ports.metrics }}
---
apiVersion: v1
kind: Service
metadata:
  name: seraphim-model-server
spec:
  selector:
    app: seraphim-model-server
  type: {{ .Values.service.type }}
  ports:
    - name: inference
      port: {{ .Values.service.ports.inference }}
      targetPort: {{ .Values.service.ports.inference }}
    - name: management
      port: {{ .Values.service.ports.management }}
      targetPort: {{ .Values.service.ports.management }}
    - name: metrics
      port: {{ .Values.service.ports.metrics }}
      targetPort: {{ .Values.service.ports.metrics }}
EOF_MS_DEPLOY

################################################################################
# CI: extend as needed to build model-server image too
################################################################################

echo "Scaffold ensured in $(pwd)"

