from fastapi import FastAPI
from pydantic import BaseModel
import time
import random

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
    # TODO: replace with real model inference (TorchServe/Triton)
    time.sleep(random.uniform(0.005, 0.02))
    pred = "positive" if (len(req.text) % 2 == 0) else "negative"
    return PredictResponse(
        prediction=pred,
        version=MODEL_VERSION,
        latency_ms=(time.time() - start) * 1000.0,
    )
