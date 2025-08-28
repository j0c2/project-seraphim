"""
Fixtures and configuration for end-to-end observability tests.

This module provides reusable fixtures for testing observability across
multiple inference services.
"""
import asyncio
import os
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx
import pytest
from prometheus_api_client import PrometheusConnect

# Ensure repository root is importable for tests
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[2]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


# Test configuration
@pytest.fixture(scope="session")
def test_config():
    """Global test configuration."""
    return {
        "services": os.environ.get("E2E_SERVICES", "inference").split(","),
        "prometheus_url": os.environ.get("E2E_PROMETHEUS_URL", "http://localhost:9090"),
        "jaeger_url": os.environ.get("E2E_JAEGER_URL", "http://localhost:16686"),
        "loki_url": os.environ.get("E2E_LOKI_URL", "http://localhost:3100"),
        "grafana_url": os.environ.get("E2E_GRAFANA_URL", "http://localhost:3000"),
        "test_timeout": int(os.environ.get("E2E_TEST_TIMEOUT", "60")),
        "correlation_prefix": os.environ.get("E2E_CORRELATION_PREFIX", "e2e-test"),
    }


# Service configuration mapping
@pytest.fixture(scope="session")
def service_configs():
    """Configuration for different inference services."""
    return {
        "inference": {
            "name": "seraphim-inference",
            "port": 8088,
            "predict_endpoint": "/predict",
            "metrics_endpoint": "/metrics",
            "health_endpoint": "/healthz",
            "observability_endpoint": "/observability/health",
            "default_model": "primary",
            "expected_metrics": [
                "seraphim_inference_requests_total",
                "seraphim_inference_latency_seconds",
            ],
            "prometheus_job": "seraphim-gateway",
        },
        "sentiment-analysis": {
            "name": "seraphim-sentiment",
            "port": 8089,
            "predict_endpoint": "/analyze",
            "metrics_endpoint": "/metrics", 
            "health_endpoint": "/health",
            "observability_endpoint": "/observability/status",
            "default_model": "sentiment-v1",
            "expected_metrics": [
                "seraphim_sentiment_requests_total",
                "seraphim_sentiment_latency_seconds",
            ],
            "prometheus_job": "seraphim-sentiment",
        },
        "text-classification": {
            "name": "seraphim-classifier",
            "port": 8090,
            "predict_endpoint": "/classify",
            "metrics_endpoint": "/metrics",
            "health_endpoint": "/health",
            "observability_endpoint": "/observability/status", 
            "default_model": "classifier-v1",
            "expected_metrics": [
                "seraphim_classifier_requests_total",
                "seraphim_classifier_latency_seconds",
            ],
            "prometheus_job": "seraphim-classifier",
        }
    }


@pytest.fixture(scope="function")
def correlation_id(test_config):
    """Generate unique correlation ID for test tracing."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    return f"{test_config['correlation_prefix']}-{timestamp}-{unique_id}"


@pytest.fixture(scope="session")
def prometheus_client(test_config):
    """Prometheus client for metrics validation."""
    return PrometheusConnect(url=test_config["prometheus_url"])


@pytest.fixture(scope="session") 
async def http_client():
    """Async HTTP client for service requests."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        yield client


@pytest.fixture(scope="function")
def test_timeframe():
    """Provide test time boundaries for queries."""
    start_time = datetime.utcnow()
    yield start_time
    # Test cleanup happens after yield


@pytest.fixture(scope="session")
async def observability_stack_health(test_config):
    """Verify observability stack is healthy before running tests."""
    endpoints = [
        (test_config["prometheus_url"], "Prometheus"),
        (test_config["jaeger_url"], "Jaeger"),
        (test_config["loki_url"], "Loki"),
        (test_config["grafana_url"], "Grafana"),
    ]
    
    healthy_services = {}
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for url, service_name in endpoints:
            try:
                # Different health check endpoints for different services
                if "prometheus" in url:
                    health_url = f"{url}/-/healthy"
                elif "jaeger" in url:
                    health_url = f"{url}/"  # Jaeger UI returns 200 for root
                elif "loki" in url:
                    health_url = f"{url}/ready"
                else:  # Grafana
                    health_url = f"{url}/api/health"
                
                response = await client.get(health_url)
                healthy_services[service_name] = response.status_code < 400
            except Exception as e:
                print(f"Warning: {service_name} health check failed: {e}")
                healthy_services[service_name] = False
    
    # Require at least Prometheus to be healthy
    if not healthy_services.get("Prometheus", False):
        pytest.skip("Prometheus is not available - skipping observability tests")
    
    return healthy_services


@pytest.fixture(scope="function")
async def service_client(test_config, service_configs, correlation_id):
    """Client for making requests to inference services with observability headers."""
    
    class ServiceClient:
        def __init__(self, config, service_configs, correlation_id):
            self.config = config
            self.service_configs = service_configs
            self.correlation_id = correlation_id
            self.base_headers = {
                "X-Correlation-ID": correlation_id,
                "User-Agent": "SeraphimE2ETest/1.0",
                "Content-Type": "application/json"
            }
        
        async def make_request(self, service_name: str, endpoint: str = None, **kwargs):
            """Make request to specified service."""
            if service_name not in self.service_configs:
                raise ValueError(f"Unknown service: {service_name}")
            
            service_config = self.service_configs[service_name]
            port = service_config["port"]
            endpoint = endpoint or service_config["predict_endpoint"]
            
            url = f"http://localhost:{port}{endpoint}"
            
            # Merge headers
            headers = {**self.base_headers, **kwargs.pop("headers", {})}
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await client.post(url, headers=headers, **kwargs)
        
        async def predict(self, service_name: str, text: str, model: str = None):
            """Make prediction request with standard payload."""
            service_config = self.service_configs[service_name]
            model = model or service_config["default_model"]
            
            payload = {"text": text, "model": model}
            
            return await self.make_request(
                service_name,
                service_config["predict_endpoint"],
                json=payload
            )
        
        async def health_check(self, service_name: str):
            """Check service health."""
            service_config = self.service_configs[service_name]
            port = service_config["port"] 
            url = f"http://localhost:{port}{service_config['health_endpoint']}"
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                return await client.get(url)
    
    return ServiceClient(test_config, service_configs, correlation_id)


@pytest.fixture(scope="function") 
def observability_validator(test_config, prometheus_client, correlation_id):
    """Utilities for validating observability data."""
    
    class ObservabilityValidator:
        def __init__(self, config, prometheus_client, correlation_id):
            self.config = config
            self.prometheus = prometheus_client
            self.correlation_id = correlation_id
            self.jaeger_url = config["jaeger_url"]
            self.loki_url = config["loki_url"]
            self.grafana_url = config["grafana_url"]
        
        async def wait_for_metrics(self, metric_name: str, labels: Dict = None, timeout: int = 30):
            """Wait for metrics to appear in Prometheus."""
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    query = metric_name
                    if labels:
                        label_pairs = [f'{k}="{v}"' for k, v in labels.items()]
                        query = f'{metric_name}{{{",".join(label_pairs)}}}'
                    
                    result = self.prometheus.custom_query(query)
                    if result:
                        return result
                except Exception as e:
                    print(f"Metrics query failed: {e}")
                
                await asyncio.sleep(1)
            
            raise TimeoutError(f"Metric {metric_name} not found within {timeout}s")
        
        async def validate_traces(self, service_name: str, timeout: int = 30):
            """Validate traces exist for correlation ID."""
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    url = f"{self.jaeger_url}/api/traces"
                    params = {
                        "service": service_name,
                        "tag": f"correlation_id:{self.correlation_id}",
                        "limit": 10
                    }
                    
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(url, params=params)
                        if response.status_code == 200:
                            data = response.json()
                            if data.get("data") and len(data["data"]) > 0:
                                return data["data"]
                except Exception as e:
                    print(f"Trace validation failed: {e}")
                
                await asyncio.sleep(2)
            
            raise TimeoutError(f"No traces found for correlation ID {self.correlation_id}")
        
        async def validate_logs(self, service_name: str, timeout: int = 30):
            """Validate logs exist for correlation ID."""
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    url = f"{self.loki_url}/loki/api/v1/query_range"
                    
                    # Build LogQL query for correlation ID
                    query = f'{{service="{service_name}"}} |= "{self.correlation_id}"'
                    
                    # Query last 5 minutes
                    end_time = datetime.utcnow()
                    start_query_time = end_time - timedelta(minutes=5)
                    
                    params = {
                        "query": query,
                        "start": int(start_query_time.timestamp() * 1e9),  # nanoseconds
                        "end": int(end_time.timestamp() * 1e9),
                        "limit": 100
                    }
                    
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(url, params=params)
                        if response.status_code == 200:
                            data = response.json()
                            results = data.get("data", {}).get("result", [])
                            if results:
                                return results
                except Exception as e:
                    print(f"Log validation failed: {e}")
                
                await asyncio.sleep(2)
            
            raise TimeoutError(f"No logs found for correlation ID {self.correlation_id}")
    
    return ObservabilityValidator(test_config, prometheus_client, correlation_id)


@pytest.fixture(scope="function")
def test_data_generator():
    """Generate deterministic test data for consistent testing."""
    
    test_texts = [
        "This is a positive sentiment example for testing observability",
        "Negative example with error handling validation",
        "Neutral text for classification and routing tests",
        "Long text example to test latency measurements and histogram buckets in observability stack",
        "Short text",
    ]
    
    def generate_request_batch(count: int = 5, service_type: str = "inference"):
        """Generate batch of test requests."""
        batch = []
        for i in range(count):
            text = test_texts[i % len(test_texts)]
            batch.append({
                "text": f"{text} (batch-{i})",
                "model": "primary" if service_type == "inference" else f"{service_type}-v1",
                "expected_variant": "baseline" if i % 3 != 0 else "candidate"  # Roughly 33% canary
            })
        return batch
    
    return {"generate_request_batch": generate_request_batch}


@pytest.fixture(scope="function")
async def cleanup_test_data(correlation_id, test_timeframe):
    """Cleanup fixture to ensure test isolation."""
    yield  # Test runs here
    
    # Post-test cleanup
    # Note: In practice, we rely on time-bounded queries rather than 
    # active cleanup since observability data is append-only
    print(f"Test completed for correlation ID: {correlation_id}")
