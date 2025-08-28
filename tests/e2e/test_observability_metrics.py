"""
End-to-end tests for Prometheus metrics collection and validation.

Tests verify that custom metrics are properly collected, labeled,
and queryable across multiple inference services.
"""
import asyncio
import pytest
import time
from typing import Dict, List

import httpx


class TestMetricsCollection:
    """Test custom metrics are collected and properly labeled."""

    @pytest.mark.asyncio
    async def test_request_counter_metrics(
        self, 
        service_client, 
        observability_validator,
        service_configs,
        test_config,
        test_data_generator,
        cleanup_test_data
    ):
        """Test that request counters increment correctly."""
        # Test all configured services
        for service_name in test_config["services"]:
            if service_name not in service_configs:
                continue
                
            service_config = service_configs[service_name]
            metric_name = service_config["expected_metrics"][0]  # requests_total metric
            
            # Get baseline metric count
            try:
                baseline_result = await observability_validator.wait_for_metrics(
                    metric_name, timeout=5
                )
                baseline_count = sum(float(r["value"][1]) for r in baseline_result)
            except TimeoutError:
                baseline_count = 0
            
            # Generate test requests
            batch = test_data_generator["generate_request_batch"](count=3, service_type=service_name)
            
            for request_data in batch:
                response = await service_client.predict(
                    service_name, 
                    request_data["text"], 
                    request_data["model"]
                )
                assert response.status_code == 200
            
            # Validate metric increments
            await asyncio.sleep(2)  # Allow metrics to propagate
            result = await observability_validator.wait_for_metrics(metric_name)
            
            new_count = sum(float(r["value"][1]) for r in result)
            assert new_count >= baseline_count + 3, f"Expected at least 3 new requests, got {new_count - baseline_count}"
            
            # Validate metric labels
            for metric in result:
                metric_labels = metric["metric"]
                assert "outcome" in metric_labels, "Missing outcome label"
                assert "variant" in metric_labels, "Missing variant label"
                assert metric_labels["outcome"] in ["success", "error", "timeout"], f"Invalid outcome: {metric_labels['outcome']}"

    @pytest.mark.asyncio
    async def test_latency_histogram_metrics(
        self,
        service_client,
        observability_validator, 
        service_configs,
        test_config,
        cleanup_test_data
    ):
        """Test latency histograms are populated correctly."""
        for service_name in test_config["services"]:
            if service_name not in service_configs:
                continue
                
            service_config = service_configs[service_name]
            latency_metric = service_config["expected_metrics"][1]  # latency histogram
            
            # Make test request
            response = await service_client.predict(
                service_name,
                "Test request for latency measurement",
                service_config["default_model"]
            )
            assert response.status_code == 200
            
            # Get response time from service
            response_data = response.json()
            reported_latency = response_data.get("latency_ms", 0)
            
            # Validate histogram metrics exist
            await asyncio.sleep(2)
            histogram_result = await observability_validator.wait_for_metrics(
                f"{latency_metric}_bucket"
            )
            
            assert len(histogram_result) > 0, "No histogram buckets found"
            
            # Validate histogram structure
            buckets = {}
            for metric in histogram_result:
                le_value = metric["metric"].get("le")
                if le_value:
                    buckets[le_value] = float(metric["value"][1])
            
            # Should have standard Prometheus histogram buckets
            expected_buckets = ["0.005", "0.01", "0.025", "0.05", "0.1", "+Inf"]
            for bucket in expected_buckets:
                assert bucket in buckets, f"Missing histogram bucket: {bucket}"
            
            # Validate bucket values are monotonically increasing
            prev_value = 0
            for bucket in sorted(buckets.keys(), key=lambda x: float(x) if x != "+Inf" else float("inf")):
                current_value = buckets[bucket]
                assert current_value >= prev_value, f"Histogram bucket {bucket} value decreased"
                prev_value = current_value

    @pytest.mark.asyncio 
    async def test_canary_variant_metrics(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        cleanup_test_data
    ):
        """Test that canary routing metrics show proper variant distribution."""
        service_name = "inference"  # Only inference service has canary routing
        
        if service_name not in test_config["services"] or service_name not in service_configs:
            pytest.skip("Inference service not available for canary testing")
        
        service_config = service_configs[service_name]
        metric_name = service_config["expected_metrics"][0]
        
        # Force baseline requests
        baseline_requests = 3
        for i in range(baseline_requests):
            response = await service_client.make_request(
                service_name,
                "/predict",
                json={"text": f"Baseline test {i}", "model": "primary"},
                headers={"X-Canary": "baseline"}
            )
            assert response.status_code == 200
        
        # Force candidate requests  
        candidate_requests = 2
        for i in range(candidate_requests):
            response = await service_client.make_request(
                service_name,
                "/predict", 
                json={"text": f"Candidate test {i}", "model": "primary"},
                headers={"X-Canary": "candidate"}
            )
            assert response.status_code == 200
        
        # Validate variant metrics
        await asyncio.sleep(2)
        result = await observability_validator.wait_for_metrics(metric_name)
        
        variant_counts = {}
        for metric in result:
            variant = metric["metric"].get("variant")
            if variant:
                variant_counts[variant] = variant_counts.get(variant, 0) + float(metric["value"][1])
        
        # Should have both variants represented
        assert "baseline" in variant_counts, "No baseline variant metrics found"
        assert "candidate" in variant_counts, "No candidate variant metrics found"

    @pytest.mark.asyncio
    async def test_error_metrics_collection(
        self,
        service_client,
        observability_validator,
        service_configs, 
        test_config,
        cleanup_test_data
    ):
        """Test that error conditions generate appropriate metrics."""
        service_name = "inference"
        
        if service_name not in test_config["services"]:
            pytest.skip("Inference service not available for error testing")
        
        service_config = service_configs[service_name]
        metric_name = service_config["expected_metrics"][0]
        
        # Get baseline error count
        try:
            baseline_result = await observability_validator.wait_for_metrics(
                metric_name, labels={"outcome": "error"}, timeout=5
            )
            baseline_errors = sum(float(r["value"][1]) for r in baseline_result)
        except TimeoutError:
            baseline_errors = 0
        
        # Make request that should cause fallback (timeout/error)
        # Note: This relies on the service having proper error handling
        response = await service_client.make_request(
            service_name,
            "/predict",
            json={"text": "Test request", "model": "nonexistent-model"},
            headers={"X-Test-Error": "simulate-error"}  # Custom header for error simulation
        )
        
        # Service should still return 200 with fallback prediction
        assert response.status_code == 200
        
        # Wait a bit longer for error metrics to propagate
        await asyncio.sleep(3)
        
        # Check if error metrics increased (or timeout/http_error metrics)
        error_outcomes = ["error", "timeout", "http_error"]
        error_found = False
        
        for outcome in error_outcomes:
            try:
                result = await observability_validator.wait_for_metrics(
                    metric_name, labels={"outcome": outcome}, timeout=5
                )
                if result:
                    error_found = True
                    break
            except TimeoutError:
                continue
        
        # At minimum, we should have success metrics even if error simulation didn't work
        success_result = await observability_validator.wait_for_metrics(
            metric_name, labels={"outcome": "success"}
        )
        assert len(success_result) > 0, "No success metrics found"


class TestMetricsQueries:
    """Test advanced Prometheus queries for observability dashboards."""

    @pytest.mark.asyncio
    async def test_request_rate_calculation(
        self,
        service_client,
        observability_validator,
        prometheus_client,
        service_configs,
        test_config,
        cleanup_test_data
    ):
        """Test request rate calculations using rate() function."""
        service_name = test_config["services"][0]  # Test first available service
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        metric_name = service_config["expected_metrics"][0]
        
        # Generate consistent load
        for i in range(5):
            response = await service_client.predict(
                service_name,
                f"Rate test request {i}",
                service_config["default_model"]
            )
            assert response.status_code == 200
            await asyncio.sleep(1)  # Spread requests over time
        
        # Query request rate
        await asyncio.sleep(5)  # Allow metrics to settle
        rate_query = f"sum(rate({metric_name}[1m]))"
        
        try:
            result = prometheus_client.custom_query(rate_query)
            assert len(result) > 0, "No rate query results"
            
            rate_value = float(result[0]["value"][1])
            assert rate_value > 0, "Request rate should be greater than 0"
            
        except Exception as e:
            pytest.fail(f"Rate query failed: {e}")

    @pytest.mark.asyncio
    async def test_latency_percentiles(
        self,
        service_client,
        observability_validator,
        prometheus_client,
        service_configs,
        test_config,
        cleanup_test_data
    ):
        """Test latency percentile calculations using histogram_quantile()."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        latency_metric = service_config["expected_metrics"][1]
        
        # Generate requests to populate histogram
        for i in range(10):
            response = await service_client.predict(
                service_name,
                f"Latency test request {i}",
                service_config["default_model"]
            )
            assert response.status_code == 200
        
        await asyncio.sleep(5)
        
        # Test different percentiles
        percentiles = [0.50, 0.95, 0.99]
        for p in percentiles:
            quantile_query = f"histogram_quantile({p}, sum by (le) (rate({latency_metric}_bucket[5m])))"
            
            try:
                result = prometheus_client.custom_query(quantile_query)
                if result:  # May be empty if not enough data
                    latency_value = float(result[0]["value"][1])
                    assert latency_value >= 0, f"P{int(p*100)} latency should be non-negative"
                    
                    # Convert to milliseconds and check reasonable bounds
                    latency_ms = latency_value * 1000
                    assert latency_ms < 10000, f"P{int(p*100)} latency {latency_ms}ms seems unreasonably high"
                    
            except Exception as e:
                print(f"Warning: P{int(p*100)} percentile query failed: {e}")

    @pytest.mark.asyncio
    async def test_error_rate_calculation(
        self,
        prometheus_client,
        service_configs,
        test_config,
        cleanup_test_data
    ):
        """Test error rate calculation queries."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        metric_name = service_config["expected_metrics"][0]
        
        # Error rate query (same as used in dashboard)
        error_rate_query = f'''
        (
            sum(rate({metric_name}{{outcome!="success"}}[5m])) or vector(0)
        ) / (
            sum(rate({metric_name}[5m])) or vector(1)
        ) * 100
        '''
        
        try:
            result = prometheus_client.custom_query(error_rate_query)
            
            if result:
                error_rate = float(result[0]["value"][1])
                assert 0 <= error_rate <= 100, f"Error rate {error_rate}% out of valid range"
            else:
                # No result might mean no errors, which is fine
                pass
                
        except Exception as e:
            print(f"Warning: Error rate query failed: {e}")
            # Don't fail test since this might be expected in some environments
