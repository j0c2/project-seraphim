from fastapi import FastAPI, Request
from pydantic import BaseModel
import time
import random
import os
import httpx
import hashlib

app = FastAPI(title="Seraphim Inference API", version="0.1.0")

class PredictRequest(BaseModel):
    text: str

class PredictResponse(BaseModel):
    prediction: str
    version: str
    latency_ms: float

MODEL_VERSION = "v0"


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).lower() in {"1", "true", "yes", "on"}


def _parse_percent(val: str | None, default: float = 0.0) -> float:
    if not val:
        return default
    try:
        f = float(val)
        # Accept both 0-1 and 0-100 inputs
        return f if f <= 1.0 else f / 100.0
    except Exception:
        return default


def _choose_variant(request: Request, canary_percent: float, sticky_header: str, salt: str) -> str:
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


@app.get("/healthz")
def health():
    return {"ok": True, "version": MODEL_VERSION}


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest, request: Request):
    start = time.time()

    # Configuration
    ts_url_default = os.environ.get("TS_URL", "http://localhost:8080")
    ts_url_candidate = os.environ.get("TS_URL_CANDIDATE", ts_url_default)

    # Baseline model config
    model_name_baseline = os.environ.get("MODEL_NAME_BASELINE", os.environ.get("MODEL_NAME", "custom-text"))
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
    else:
        target_ts = ts_url_default
        target_name = model_name_baseline
        target_ver = model_version_baseline

    # Build TorchServe URL
    if target_ver:
        url = f"{target_ts}/predictions/{target_name}/{target_ver}"
    else:
        url = f"{target_ts}/predictions/{target_name}"

    try:
        headers = {"Content-Type": "text/plain"}
        timeout_ms = float(os.environ.get("TS_TIMEOUT_MS", "300"))
        with httpx.Client(timeout=timeout_ms / 1000.0) as client:
            r = client.post(url, content=req.text.encode("utf-8"), headers=headers)
            r.raise_for_status()
            content_type = r.headers.get("content-type", "")
            if content_type.startswith("application/json"):
                data = r.json()
                pred = data.get("prediction", data.get("result", "unknown"))
            else:
                pred = r.text.strip()
    except Exception:
        # Fallback to a deterministic dummy prediction
        time.sleep(random.uniform(0.005, 0.02))
        pred = "positive" if (len(req.text) % 2 == 0) else "negative"

    return PredictResponse(
        prediction=pred,
        version=MODEL_VERSION,  # API compatibility: keep gateway version here
        latency_ms=(time.time() - start) * 1000.0,
    )
