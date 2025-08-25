import os
import json
import respx
from httpx import Response
from fastapi.testclient import TestClient

# Wire app import from the real file
from services.inference.app.main import app


def test_predict_calls_torchserve_success(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("TS_URL", "http://ts:8080")
    monkeypatch.setenv("MODEL_NAME", "custom-text")

    with respx.mock(base_url="http://ts:8080") as mock:
        mock.post("/predictions/custom-text").respond(
            200,
            json={"prediction": "positive"},
            headers={"content-type": "application/json"},
        )
        r = client.post("/predict", json={"text": "abcd"})
        assert r.status_code == 200
        body = r.json()
        assert body["prediction"] == "positive"


def test_predict_fallback_on_error(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("TS_URL", "http://ts:8080")
    monkeypatch.setenv("MODEL_NAME", "custom-text")

    with respx.mock(base_url="http://ts:8080") as mock:
        mock.post("/predictions/custom-text").respond(500, text="boom")
        r = client.post("/predict", json={"text": "abc"})  # odd length -> negative fallback
        assert r.status_code == 200
        body = r.json()
        assert body["prediction"] in ("negative", "positive")

