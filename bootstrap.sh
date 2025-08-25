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
  # ensure_file <path> <here-doc label>
  local path="$1"; shift
  local label="$1"; shift
  if [[ ! -f "$path" ]]; then
    mkdir -p "$(dirname "$path")"
    cat > "$path" << "$label"
$*
$label
  fi
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

ensure_file config/__init__.py EOF_INIT_CONFIG
__all__ = ['reliability']
EOF_INIT_CONFIG

ensure_file config/reliability/__init__.py EOF_INIT_RELIABILITY
__all__ = ['drift','canary','chaos']
EOF_INIT_RELIABILITY

# Empty package markers (idempotent)
ensure_file config/reliability/drift/__init__.py EOF_EMPTY
EOF_EMPTY
ensure_file config/reliability/canary/__init__.py EOF_EMPTY
EOF_EMPTY
ensure_file config/reliability/chaos/__init__.py EOF_EMPTY
EOF_EMPTY

# Optional: baseline detector implementation (only if missing)
if [[ ! -f config/reliability/drift/detector.py ]]; then
  ensure_file config/reliability/drift/detector.py EOF_DETECTOR
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
ensure_file tests/conftest.py EOF_CONFTEST
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
ensure_file deploy/k8s/namespace.yaml EOF_NS
apiVersion: v1
kind: Namespace
metadata:
  name: seraphim
EOF_NS

ensure_dir deploy/environment/dev
# Dev overlay kustomization with namespace, labels, and prefix for clear scoping
ensure_file deploy/environment/dev/kustomization.yaml EOF_KUSTO_DEV
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
ensure_file docs/playbooks/rollback.md EOF_ROLLBACK
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
ensure_file tests/unit/test_detector.py EOF_T_DETECTOR
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
ensure_file tests/e2e/locustfile.py EOF_LOCUST
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
ensure_file requirements-dev.txt EOF_REQ_DEV
pytest
numpy
locust
black
isort
flake8
EOF_REQ_DEV

echo "Scaffold ensured in $(pwd)"

