import hashlib
import logging
import os
import random
import time
from enum import Enum
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import (CONTENT_TYPE_LATEST, Counter, Histogram,
                               generate_latest)
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Seraphim Inference API",
    version="0.1.0",
    description="Gateway service with canary routing for ML model inference",
)


class ModelVariant(str, Enum):
    BASELINE = "baseline"
    CANDIDATE = "candidate"


class PredictRequest(BaseModel):
    text: str = Field(
        ..., min_length=1, max_length=10000, description="Text to predict"
    )


class PredictResponse(BaseModel):
    prediction: str = Field(..., description="Model prediction result")
    version: str = Field(..., description="API version")
    latency_ms: float = Field(..., description="Request latency in milliseconds")
    model_variant: Optional[str] = Field(
        None, description="Which model variant was used"
    )
    model_version: Optional[str] = Field(
        None, description="Specific model version used"
    )


MODEL_VERSION = "v0"

# Prometheus metrics
REQUEST_COUNT = Counter(
    "seraphim_inference_requests_total",
    "Total number of inference requests",
    labelnames=["variant", "outcome"],
)
LATENCY_HIST = Histogram(
    "seraphim_inference_latency_seconds",
    "Inference latency in seconds",
    labelnames=["variant"],
)


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).lower() in {"1", "true", "yes", "on"}


def _parse_percent(val: Optional[str], default: float = 0.0) -> float:
    if not val:
        return default
    try:
        f = float(val)
        # Accept both 0-1 and 0-100 inputs
        return f if f <= 1.0 else f / 100.0
    except Exception:
        return default


def _choose_variant(
    request: Request, canary_percent: float, sticky_header: str, salt: str
) -> str:
    # Explicit override header if present
    force = request.headers.get(os.environ.get("CANARY_FORCE_HEADER", "X-Canary"))
    if force:
        force_l = force.lower()
        if force_l in {"candidate", "canary", "v2"}:
            return "candidate"
        if force_l in {"baseline", "control", "v1"}:
            return "baseline"

    # Sticky routing based on a header (e.g., user id)
    key = request.headers.get(sticky_header)
    if key:
        h = hashlib.sha256((salt + ":" + key).encode("utf-8")).digest()
        bucket = int.from_bytes(h[:2], "big") % 10000  # 0..9999
        threshold = int(canary_percent * 10000)
        return "candidate" if bucket < threshold else "baseline"

    # Fallback to random sampling
    return "candidate" if random.random() < canary_percent else "baseline"


@app.get("/healthz", tags=["health"])
def health() -> Dict[str, Any]:
    """Health check endpoint for Kubernetes probes."""
    return {"ok": True, "version": MODEL_VERSION}


@app.get("/metrics", tags=["metrics"])
def metrics() -> Response:
    payload = generate_latest()
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)


@app.get("/readyz", tags=["health"])
async def ready() -> Dict[str, Any]:
    """Readiness check - verify TorchServe connectivity."""
    ts_url = os.environ.get("TS_URL", "http://localhost:8080")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{ts_url}/ping")
            response.raise_for_status()
            return {"ready": True, "torchserve": "healthy"}
    except Exception as e:
        logger.warning(f"TorchServe health check failed: {e}")
        raise HTTPException(status_code=503, detail="TorchServe not ready")


@app.post("/predict", response_model=PredictResponse, tags=["inference"])
async def predict(req: PredictRequest, request: Request) -> PredictResponse:
    """Main prediction endpoint with canary routing."""
    start = time.time()

    # Configuration
    ts_url_default = os.environ.get("TS_URL", "http://localhost:8080")
    ts_url_candidate = os.environ.get("TS_URL_CANDIDATE", ts_url_default)

    # Baseline model config
    model_name_baseline = os.environ.get(
        "MODEL_NAME_BASELINE", os.environ.get("MODEL_NAME", "custom-text")
    )
    model_version_baseline = os.environ.get("MODEL_VERSION_BASELINE", "")

    # Candidate model config
    model_name_candidate = os.environ.get("MODEL_NAME_CANDIDATE", model_name_baseline)
    model_version_candidate = os.environ.get("MODEL_VERSION_CANDIDATE", "")

    # Canary routing
    canary_percent = _parse_percent(os.environ.get("CANARY_PERCENT", "0"), 0.0)
    sticky_header = os.environ.get("CANARY_STICKY_HEADER", "X-User-Id")
    salt = os.environ.get("CANARY_STICKY_SALT", "seraphim")

    variant = _choose_variant(request, canary_percent, sticky_header, salt)

    # Resolve target
    if variant == "candidate":
        target_ts = ts_url_candidate
        target_name = model_name_candidate
        target_ver = model_version_candidate
        used_variant = ModelVariant.CANDIDATE
    else:
        target_ts = ts_url_default
        target_name = model_name_baseline
        target_ver = model_version_baseline
        used_variant = ModelVariant.BASELINE

    # Build TorchServe URL
    if target_ver:
        url = f"{target_ts}/predictions/{target_name}/{target_ver}"
    else:
        url = f"{target_ts}/predictions/{target_name}"

    logger.info(f"Routing to {used_variant.value}: {url}")

    try:
        headers = {"Content-Type": "text/plain"}
        timeout_ms = float(os.environ.get("TS_TIMEOUT_MS", "3000"))

        async with httpx.AsyncClient(timeout=timeout_ms / 1000.0) as client:
            response = await client.post(
                url, content=req.text.encode("utf-8"), headers=headers
            )
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if content_type.startswith("application/json"):
                data = response.json()
                pred = data.get("prediction", data.get("result", "unknown"))
            else:
                pred = response.text.strip()

            logger.info(f"Successfully got prediction from {used_variant.value}")
            REQUEST_COUNT.labels(variant=used_variant.value, outcome="success").inc()

    except httpx.TimeoutException as e:
        logger.warning(f"Timeout calling {url}: {e}")
        # Fallback to dummy prediction
        pred = "positive" if (len(req.text) % 2 == 0) else "negative"
        logger.info("Using fallback prediction due to timeout")
        REQUEST_COUNT.labels(variant=used_variant.value, outcome="timeout").inc()
    except httpx.HTTPStatusError as e:
        logger.warning(f"HTTP error from {url}: {e.response.status_code}")
        # Fallback to dummy prediction
        pred = "positive" if (len(req.text) % 2 == 0) else "negative"
        logger.info("Using fallback prediction due to HTTP error")
        REQUEST_COUNT.labels(variant=used_variant.value, outcome="http_error").inc()
    except Exception as e:
        logger.error(f"Unexpected error calling {url}: {e}")
        # Fallback to dummy prediction
        pred = "positive" if (len(req.text) % 2 == 0) else "negative"
        logger.info("Using fallback prediction due to error")
        REQUEST_COUNT.labels(variant=used_variant.value, outcome="error").inc()

    # Observe latency
    LATENCY_HIST.labels(variant=used_variant.value).observe(time.time() - start)

    return PredictResponse(
        prediction=pred,
        version=MODEL_VERSION,
        latency_ms=(time.time() - start) * 1000.0,
        model_variant=used_variant.value,
        model_version=target_ver if target_ver else "default",
    )
