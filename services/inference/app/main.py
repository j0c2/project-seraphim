import hashlib
import logging
import os
import random
import sys
import time
from enum import Enum
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import (CONTENT_TYPE_LATEST, Counter, Histogram,
                               generate_latest)
from pydantic import BaseModel, Field

from shared.observability import (
    setup_logging, setup_tracing, instrument_fastapi, instrument_httpx,
    trace_operation, add_span_attributes, get_correlation_id, sanitize_for_json_logging
)

# Initialize observability
SERVICE_NAME = "seraphim-inference"
SERVICE_VERSION = os.environ.get("SERVICE_VERSION", "0.1.0")

logger = setup_logging(SERVICE_NAME)
tracer = setup_tracing(SERVICE_NAME, SERVICE_VERSION)

# Configure uvicorn loggers to use our JSON formatter
def configure_uvicorn_logging():
    """Configure uvicorn's access and error loggers to use JSON format."""
    # Get our JSON formatter
    json_handler = logging.root.handlers[0] if logging.root.handlers else None
    if json_handler:
        # Configure uvicorn access logger
        uvicorn_access_logger = logging.getLogger("uvicorn.access")
        uvicorn_access_logger.handlers.clear()
        uvicorn_access_logger.addHandler(json_handler)
        uvicorn_access_logger.propagate = False
        
        # Configure uvicorn error logger
        uvicorn_error_logger = logging.getLogger("uvicorn.error")
        uvicorn_error_logger.handlers.clear()
        uvicorn_error_logger.addHandler(json_handler)
        uvicorn_error_logger.propagate = False
        
        # Configure uvicorn main logger
        uvicorn_logger = logging.getLogger("uvicorn")
        uvicorn_logger.handlers.clear()
        uvicorn_logger.addHandler(json_handler)
        uvicorn_logger.propagate = False

configure_uvicorn_logging()

app = FastAPI(
    title="Seraphim Inference API",
    version="0.1.0",
    description="Gateway service with canary routing for ML model inference",
)

# Instrument FastAPI and HTTP clients
instrument_fastapi(app, SERVICE_NAME)
instrument_httpx()


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


@app.get("/observability/health", tags=["observability"])
def observability_health() -> Dict[str, Any]:
    """Check observability stack health."""
    health_status = {
        "logging": {"status": "healthy", "level": logging.root.level},
        "tracing": {"status": "healthy", "service_name": SERVICE_NAME},
        "correlation_id": get_correlation_id(),
    }
    
    # Test trace creation
    try:
        with trace_operation("health_check_test"):
            pass
        health_status["tracing"]["test_span"] = "success"
    except Exception as e:
        health_status["tracing"]["test_span"] = f"failed: {e}"
        health_status["tracing"]["status"] = "degraded"
    
    logger.info("Observability health check performed", extra=health_status)
    return health_status


@app.get("/observability/config", tags=["observability"])
def observability_config() -> Dict[str, Any]:
    """Get current observability configuration."""
    config = {
        "service": {
            "name": SERVICE_NAME,
            "version": SERVICE_VERSION,
        },
        "logging": {
            "level": logging.getLevelName(logging.root.level),
            "handlers": [type(h).__name__ for h in logging.root.handlers],
        },
        "tracing": {
            "jaeger_agent_host": os.environ.get("JAEGER_AGENT_HOST", "not_set"),
            "jaeger_agent_port": os.environ.get("JAEGER_AGENT_PORT", "not_set"),
            "otlp_endpoint": os.environ.get("OTLP_ENDPOINT", "not_set"),
            "trace_console": os.environ.get("TRACE_CONSOLE", "false"),
        },
        "environment": {
            "ts_url": os.environ.get("TS_URL"),
            "canary_percent": os.environ.get("CANARY_PERCENT"),
            "log_level": os.environ.get("LOG_LEVEL"),
        }
    }
    return config


@app.post("/observability/log-level", tags=["observability"])
def set_log_level(level: str) -> Dict[str, Any]:
    """Dynamically change log level."""
    try:
        numeric_level = getattr(logging, level.upper())
        logging.root.setLevel(numeric_level)
        
        logger.info(
            "Log level changed",
            extra={
                "old_level": logging.getLevelName(logging.root.level),
                "new_level": level.upper(),
                "correlation_id": get_correlation_id()
            }
        )
        
        return {
            "success": True,
            "old_level": logging.getLevelName(logging.root.level),
            "new_level": level.upper()
        }
    except AttributeError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid log level: {level}. Valid levels: DEBUG, INFO, WARNING, ERROR, CRITICAL"
        )


@app.get("/observability/trace/{correlation_id}", tags=["observability"])
def get_trace_info(correlation_id: str) -> Dict[str, Any]:
    """Get trace information for a correlation ID."""
    with trace_operation("trace_lookup", correlation_id=correlation_id):
        logger.info(
            "Trace information requested",
            extra={
                "requested_correlation_id": correlation_id,
                "current_correlation_id": get_correlation_id()
            }
        )
        
        return {
            "correlation_id": correlation_id,
            "service_name": SERVICE_NAME,
            "jaeger_ui": f"http://localhost:16686/search?service={SERVICE_NAME}",
            "current_trace_id": get_correlation_id(),
            "note": "Use Jaeger UI to view full trace details"
        }


@app.post("/predict", response_model=PredictResponse, tags=["inference"])
async def predict(req: PredictRequest, request: Request) -> PredictResponse:
    """Main prediction endpoint with canary routing."""
    correlation_id = get_correlation_id()
    
    # Add span attributes for request context
    add_span_attributes(
        text_length=len(req.text),
        correlation_id=correlation_id or "none"
    )
    
    logger.info(
        "Processing prediction request", 
        extra={
            "text_length": len(req.text),
            "correlation_id": correlation_id
        }
    )
    
    start = time.time()

    with trace_operation("canary_routing") as routing_span:
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
        
        # Add routing attributes to span
        routing_span.set_attribute("canary.variant", variant)
        routing_span.set_attribute("canary.percent", str(canary_percent))

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
            
        # Add model attributes to span
        routing_span.set_attribute("model.variant", used_variant.value)
        routing_span.set_attribute("model.name", target_name)
        routing_span.set_attribute("model.version", target_ver or "default")
        routing_span.set_attribute("torchserve.url", url)

        logger.info(
            "Routing decision made",
            extra={
                "variant": used_variant.value,
                "model_name": target_name,
                "model_version": target_ver or "default",
                "url": url,
                "canary_percent": canary_percent,
                "correlation_id": correlation_id
            }
        )

    with trace_operation("model_inference", 
                        model_name=target_name,
                        model_version=target_ver or "default",
                        variant=used_variant.value) as inference_span:
        try:
            headers = {"Content-Type": "text/plain"}
            timeout_ms = float(os.environ.get("TS_TIMEOUT_MS", "3000"))
            
            # Add inference attributes to span
            inference_span.set_attribute("inference.timeout_ms", str(timeout_ms))
            inference_span.set_attribute("inference.url", url)

            async with httpx.AsyncClient(timeout=timeout_ms / 1000.0) as client:
                response = await client.post(
                    url, content=req.text.encode("utf-8"), headers=headers
                )
                response.raise_for_status()
                
                # Add response attributes to span
                inference_span.set_attribute("http.response.status_code", response.status_code)
                inference_span.set_attribute("http.response.content_type", 
                                           response.headers.get("content-type", "unknown"))

                content_type = response.headers.get("content-type", "")
                if content_type.startswith("application/json"):
                    data = response.json()
                    pred = data.get("prediction", data.get("result", "unknown"))
                else:
                    pred = response.text.strip()
                
                inference_span.set_attribute("inference.prediction", pred)
                inference_span.set_attribute("inference.outcome", "success")

                logger.info(
                    "Model inference completed successfully",
                    extra={
                        "variant": used_variant.value,
                        "model_name": target_name,
                        "model_version": target_ver or "default",
                        "prediction": sanitize_for_json_logging(pred),
                        "response_time_ms": (time.time() - start) * 1000,
                        "correlation_id": correlation_id
                    }
                )
                REQUEST_COUNT.labels(variant=used_variant.value, outcome="success").inc()

        except httpx.TimeoutException as e:
            inference_span.set_attribute("inference.outcome", "timeout")
            inference_span.record_exception(e)
            
            logger.warning(
                "Model inference timeout",
                extra={
                    "variant": used_variant.value,
                    "url": url,
                    "timeout_ms": timeout_ms,
                    "error": str(e),
                    "correlation_id": correlation_id
                }
            )
            # Fallback to dummy prediction
            pred = "positive" if (len(req.text) % 2 == 0) else "negative"
            logger.info(
                "Using fallback prediction",
                extra={
                    "reason": "timeout",
                    "fallback_prediction": sanitize_for_json_logging(pred),
                    "correlation_id": correlation_id
                }
            )
            REQUEST_COUNT.labels(variant=used_variant.value, outcome="timeout").inc()
            
        except httpx.HTTPStatusError as e:
            inference_span.set_attribute("inference.outcome", "http_error")
            inference_span.set_attribute("http.response.status_code", e.response.status_code)
            inference_span.record_exception(e)
            
            logger.warning(
                "Model inference HTTP error",
                extra={
                    "variant": used_variant.value,
                    "url": url,
                    "status_code": e.response.status_code,
                    "error": str(e),
                    "correlation_id": correlation_id
                }
            )
            # Fallback to dummy prediction
            pred = "positive" if (len(req.text) % 2 == 0) else "negative"
            logger.info(
                "Using fallback prediction",
                extra={
                    "reason": "http_error",
                    "fallback_prediction": sanitize_for_json_logging(pred),
                    "correlation_id": correlation_id
                }
            )
            REQUEST_COUNT.labels(variant=used_variant.value, outcome="http_error").inc()
            
        except Exception as e:
            inference_span.set_attribute("inference.outcome", "error")
            inference_span.record_exception(e)
            
            logger.error(
                "Model inference unexpected error",
                extra={
                    "variant": used_variant.value,
                    "url": url,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "correlation_id": correlation_id
                }
            )
            # Fallback to dummy prediction
            pred = "positive" if (len(req.text) % 2 == 0) else "negative"
            logger.info(
                "Using fallback prediction",
                extra={
                    "reason": "error",
                    "fallback_prediction": sanitize_for_json_logging(pred),
                    "correlation_id": correlation_id
                }
            )
            REQUEST_COUNT.labels(variant=used_variant.value, outcome="error").inc()

    # Observe latency
    final_latency = time.time() - start
    LATENCY_HIST.labels(variant=used_variant.value).observe(final_latency)
    
    # Add final span attributes
    add_span_attributes(
        latency_ms=final_latency * 1000,
        prediction=pred,
        outcome="success" if "error" not in locals() else "error"
    )
    
    logger.info(
        "Prediction request completed",
        extra={
            "total_latency_ms": final_latency * 1000,
            "prediction": sanitize_for_json_logging(pred),
            "variant": used_variant.value,
            "correlation_id": correlation_id
        }
    )

    return PredictResponse(
        prediction=pred,
        version=MODEL_VERSION,
        latency_ms=final_latency * 1000.0,
        model_variant=used_variant.value,
        model_version=target_ver if target_ver else "default",
    )
