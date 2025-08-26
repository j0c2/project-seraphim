"""Tests for canary routing logic in the inference gateway."""
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import httpx
import respx

# Import the app
from services.inference.app.main import app, _parse_percent, _choose_variant


class TestPercentParsing:
    """Test the percentage parsing utility."""
    
    def test_parse_percent_decimal(self):
        assert _parse_percent("0.1") == 0.1
        assert _parse_percent("0.5") == 0.5
        assert _parse_percent("1.0") == 1.0
        
    def test_parse_percent_whole_numbers(self):
        assert _parse_percent("10") == 0.1
        assert _parse_percent("50") == 0.5
        assert _parse_percent("100") == 1.0
        
    def test_parse_percent_invalid(self):
        assert _parse_percent("invalid") == 0.0
        assert _parse_percent("") == 0.0
        assert _parse_percent(None) == 0.0
        
    def test_parse_percent_with_default(self):
        assert _parse_percent("invalid", 0.25) == 0.25
        assert _parse_percent(None, 0.5) == 0.5


class TestCanaryRouting:
    """Test the canary variant selection logic."""
    
    def test_force_header_candidate(self):
        """Test forcing candidate variant via header."""
        request = MagicMock()
        request.headers.get.side_effect = lambda h: "candidate" if h == "X-Canary" else None
        assert _choose_variant(request, 0.0, "X-User-Id", "salt") == "candidate"
        
    def test_force_header_baseline(self):
        """Test forcing baseline variant via header."""
        request = MagicMock()
        request.headers.get.side_effect = lambda h: "baseline" if h == "X-Canary" else None
        assert _choose_variant(request, 1.0, "X-User-Id", "salt") == "baseline"
        
    def test_sticky_routing_deterministic(self):
        """Test that sticky routing is deterministic for the same user."""
        request = MagicMock()
        request.headers.get.side_effect = lambda h: "user123" if h == "X-User-Id" else None
        
        # Same user should always get same variant
        results = [_choose_variant(request, 0.5, "X-User-Id", "salt") for _ in range(10)]
        assert len(set(results)) == 1
        
    def test_sticky_routing_distribution(self):
        """Test that sticky routing distributes users roughly per canary percentage."""
        baseline_count = 0
        candidate_count = 0
        
        for i in range(1000):
            request = MagicMock()
            request.headers.get.side_effect = lambda h: f"user{i}" if h == "X-User-Id" else None
            variant = _choose_variant(request, 0.3, "X-User-Id", "salt")
            if variant == "candidate":
                candidate_count += 1
            else:
                baseline_count += 1
                
        # With 30% canary, we expect roughly 300 candidates out of 1000
        # Allow for some variance
        assert 250 < candidate_count < 350
        assert 650 < baseline_count < 750
        
    def test_random_routing_no_sticky_header(self):
        """Test random routing when no sticky header present."""
        request = MagicMock()
        request.headers.get.return_value = None
        
        # With 0% canary, should always be baseline
        results = [_choose_variant(request, 0.0, "X-User-Id", "salt") for _ in range(10)]
        assert all(r == "baseline" for r in results)
        
        # With 100% canary, should always be candidate
        results = [_choose_variant(request, 1.0, "X-User-Id", "salt") for _ in range(10)]
        assert all(r == "candidate" for r in results)


@pytest.mark.asyncio
class TestInferenceEndpoint:
    """Test the main inference endpoint with mocked TorchServe."""
    
    async def test_predict_baseline_routing(self, monkeypatch):
        """Test that baseline routing works correctly."""
        client = TestClient(app)
        monkeypatch.setenv("TS_URL", "http://torchserve:8080")
        monkeypatch.setenv("MODEL_NAME_BASELINE", "model")
        monkeypatch.setenv("MODEL_VERSION_BASELINE", "1.0")
        monkeypatch.setenv("CANARY_PERCENT", "0")  # All traffic to baseline
        
        with respx.mock:
            route = respx.post("http://torchserve:8080/predictions/model/1.0").mock(
                return_value=httpx.Response(
                    200,
                    json={"prediction": "baseline_result"},
                    headers={"content-type": "application/json"}
                )
            )
            
            response = client.post("/predict", json={"text": "test"})
            assert response.status_code == 200
            data = response.json()
            assert data["prediction"] == "baseline_result"
            assert data["model_variant"] == "baseline"
            assert data["model_version"] == "1.0"
            assert route.called
            
    async def test_predict_candidate_routing(self, monkeypatch):
        """Test that candidate routing works correctly."""
        client = TestClient(app)
        monkeypatch.setenv("TS_URL", "http://torchserve:8080")
        monkeypatch.setenv("MODEL_NAME_CANDIDATE", "model")
        monkeypatch.setenv("MODEL_VERSION_CANDIDATE", "2.0")
        monkeypatch.setenv("CANARY_PERCENT", "100")  # All traffic to candidate
        
        with respx.mock:
            route = respx.post("http://torchserve:8080/predictions/model/2.0").mock(
                return_value=httpx.Response(
                    200,
                    json={"prediction": "candidate_result"},
                    headers={"content-type": "application/json"}
                )
            )
            
            response = client.post("/predict", json={"text": "test"})
            assert response.status_code == 200
            data = response.json()
            assert data["prediction"] == "candidate_result"
            assert data["model_variant"] == "candidate"
            assert data["model_version"] == "2.0"
            assert route.called
            
    async def test_predict_force_header(self, monkeypatch):
        """Test forcing specific variant via header."""
        client = TestClient(app)
        monkeypatch.setenv("TS_URL", "http://torchserve:8080")
        monkeypatch.setenv("MODEL_NAME_BASELINE", "model")
        monkeypatch.setenv("MODEL_VERSION_BASELINE", "1.0")
        monkeypatch.setenv("MODEL_NAME_CANDIDATE", "model")
        monkeypatch.setenv("MODEL_VERSION_CANDIDATE", "2.0")
        monkeypatch.setenv("CANARY_PERCENT", "0")  # Default to baseline
        
        with respx.mock:
            candidate_route = respx.post("http://torchserve:8080/predictions/model/2.0").mock(
                return_value=httpx.Response(
                    200,
                    json={"prediction": "forced_candidate"},
                    headers={"content-type": "application/json"}
                )
            )
            
            # Force candidate via header despite 0% canary
            response = client.post(
                "/predict",
                json={"text": "test"},
                headers={"X-Canary": "candidate"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["prediction"] == "forced_candidate"
            assert data["model_variant"] == "candidate"
            assert candidate_route.called
            
    async def test_predict_fallback_on_error(self, monkeypatch):
        """Test fallback to dummy prediction on TorchServe error."""
        client = TestClient(app)
        monkeypatch.setenv("TS_URL", "http://torchserve:8080")
        monkeypatch.setenv("MODEL_NAME_BASELINE", "model")
        monkeypatch.setenv("MODEL_VERSION_BASELINE", "1.0")
        
        with respx.mock:
            respx.post("http://torchserve:8080/predictions/model/1.0").mock(
                return_value=httpx.Response(503, text="Service Unavailable")
            )
            
            # Even-length text should give "positive" fallback
            response = client.post("/predict", json={"text": "test"})
            assert response.status_code == 200
            data = response.json()
            assert data["prediction"] == "positive"
            
            # Odd-length text should give "negative" fallback
            response = client.post("/predict", json={"text": "tests"})
            assert response.status_code == 200
            data = response.json()
            assert data["prediction"] == "negative"
            
    async def test_predict_timeout_fallback(self, monkeypatch):
        """Test fallback on timeout."""
        client = TestClient(app)
        monkeypatch.setenv("TS_URL", "http://torchserve:8080")
        monkeypatch.setenv("MODEL_NAME_BASELINE", "model")
        monkeypatch.setenv("TS_TIMEOUT_MS", "100")  # Very short timeout
        
        with respx.mock:
            # Mock a slow response
            respx.post("http://torchserve:8080/predictions/model").mock(
                side_effect=httpx.TimeoutException("timeout")
            )
            
            response = client.post("/predict", json={"text": "test"})
            assert response.status_code == 200
            data = response.json()
            assert data["prediction"] in ["positive", "negative"]
            

class TestHealthEndpoints:
    """Test health check endpoints."""
    
    def test_healthz(self):
        """Test basic health check."""
        client = TestClient(app)
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "version" in data
        
    @pytest.mark.asyncio
    async def test_readyz_healthy(self, monkeypatch):
        """Test readiness when TorchServe is healthy."""
        client = TestClient(app)
        monkeypatch.setenv("TS_URL", "http://torchserve:8080")
        
        with respx.mock:
            respx.get("http://torchserve:8080/ping").mock(
                return_value=httpx.Response(200, json={"status": "Healthy"})
            )
            
            response = client.get("/readyz")
            assert response.status_code == 200
            data = response.json()
            assert data["ready"] is True
            assert data["torchserve"] == "healthy"
            
    @pytest.mark.asyncio
    async def test_readyz_unhealthy(self, monkeypatch):
        """Test readiness when TorchServe is down."""
        client = TestClient(app)
        monkeypatch.setenv("TS_URL", "http://torchserve:8080")
        
        with respx.mock:
            respx.get("http://torchserve:8080/ping").mock(
                return_value=httpx.Response(503)
            )
            
            response = client.get("/readyz")
            assert response.status_code == 503
            assert "TorchServe not ready" in response.json()["detail"]
