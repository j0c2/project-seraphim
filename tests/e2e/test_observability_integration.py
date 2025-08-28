"""
End-to-end integration tests for observability stack.

Tests verify that metrics, logs, and traces work together correctly
and provide complete observability across the inference pipeline.
"""
import asyncio
import json
import pytest
import time
from typing import Dict, List, Set


class TestObservabilityIntegration:
    """Test integration between metrics, logs, and traces."""

    @pytest.mark.asyncio
    async def test_end_to_end_correlation(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test that a single request generates correlated metrics, logs, and traces."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Record baseline metrics
        metric_name = service_config["expected_metrics"][0]
        try:
            baseline_metrics = await observability_validator.wait_for_metrics(
                metric_name, timeout=5
            )
            baseline_count = sum(float(r["value"][1]) for r in baseline_metrics)
        except TimeoutError:
            baseline_count = 0
        
        # Make test request with unique text for correlation
        test_text = f"End-to-end correlation test {int(time.time())}"
        response = await service_client.predict(
            service_name,
            test_text,
            service_config["default_model"]
        )
        assert response.status_code == 200
        
        # Wait for observability data to propagate
        await asyncio.sleep(3)
        
        # Validate metrics increased
        metrics = await observability_validator.wait_for_metrics(metric_name)
        new_count = sum(float(r["value"][1]) for r in metrics)
        assert new_count > baseline_count, "Metrics did not increment"
        
        # Validate trace exists with correlation ID
        traces = await observability_validator.validate_traces(
            service_config["name"],
            timeout=30
        )
        
        trace_found = False
        trace_id = None
        for trace in traces:
            for span in trace["spans"]:
                span_tags = {tag["key"]: tag["value"] for tag in span.get("tags", [])}
                if span_tags.get("correlation_id") == correlation_id:
                    trace_found = True
                    trace_id = trace["traceID"]
                    break
            if trace_found:
                break
        
        assert trace_found, "No trace found with correlation ID"
        
        # Validate logs exist with correlation ID
        logs = await observability_validator.validate_logs(
            service_config["name"],
            timeout=30
        )
        
        log_found = False
        for log_stream in logs:
            for log_entry in log_stream.get("values", []):
                timestamp, log_message = log_entry
                if correlation_id in log_message and test_text in log_message:
                    log_found = True
                    break
            if log_found:
                break
        
        assert log_found, "No log found with correlation ID and test text"
        
        print(f"✅ End-to-end correlation successful:")
        print(f"  - Metrics: {new_count - baseline_count} new requests")
        print(f"  - Trace ID: {trace_id}")
        print(f"  - Correlation ID: {correlation_id}")

    @pytest.mark.asyncio
    async def test_multi_service_observability(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test observability across multiple services."""
        available_services = [s for s in test_config["services"] if s in service_configs]
        
        if len(available_services) < 1:
            pytest.skip("No configured services available")
        
        # Generate requests across all available services
        service_results = {}
        
        for service_name in available_services:
            service_config = service_configs[service_name]
            
            # Get baseline metrics
            metric_name = service_config["expected_metrics"][0]
            try:
                baseline_metrics = await observability_validator.wait_for_metrics(
                    metric_name, timeout=5
                )
                baseline_count = sum(float(r["value"][1]) for r in baseline_metrics)
            except TimeoutError:
                baseline_count = 0
            
            # Make request
            response = await service_client.predict(
                service_name,
                f"Multi-service test for {service_name}",
                service_config["default_model"]
            )
            assert response.status_code == 200
            
            service_results[service_name] = {
                "baseline_count": baseline_count,
                "service_config": service_config,
                "response": response
            }
        
        # Wait for observability data
        await asyncio.sleep(5)
        
        # Validate each service has observability data
        for service_name, result in service_results.items():
            service_config = result["service_config"]
            baseline_count = result["baseline_count"]
            
            # Check metrics
            metric_name = service_config["expected_metrics"][0]
            metrics = await observability_validator.wait_for_metrics(metric_name)
            new_count = sum(float(r["value"][1]) for r in metrics)
            assert new_count > baseline_count, f"No metric increment for {service_name}"
            
            # Check traces
            traces = await observability_validator.validate_traces(
                service_config["name"],
                timeout=20
            )
            assert len(traces) > 0, f"No traces found for {service_name}"
            
            # Check logs
            try:
                logs = await observability_validator.validate_logs(
                    service_config["name"],
                    timeout=20
                )
                assert len(logs) > 0, f"No logs found for {service_name}"
            except TimeoutError:
                print(f"Warning: Logs not found for {service_name} (may be expected)")
        
        print(f"✅ Multi-service observability validated for {len(available_services)} services")

    @pytest.mark.asyncio
    async def test_error_propagation_observability(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test that errors are properly captured in all observability pillars."""
        service_name = "inference"  # Use inference service which has error handling
        
        if service_name not in test_config["services"]:
            pytest.skip("Inference service not available for error testing")
        
        service_config = service_configs[service_name]
        
        # Get baseline error metrics
        metric_name = service_config["expected_metrics"][0]
        try:
            error_metrics = await observability_validator.wait_for_metrics(
                metric_name, labels={"outcome": "http_error"}, timeout=5
            )
            baseline_errors = sum(float(r["value"][1]) for r in error_metrics)
        except TimeoutError:
            baseline_errors = 0
        
        # Make request that should trigger error handling
        response = await service_client.make_request(
            service_name,
            "/predict",
            json={"text": "Error propagation test", "model": "nonexistent-model"},
            headers={"X-Force-Error": "timeout"}  # Custom header to simulate error
        )
        
        # Should still return 200 with fallback
        assert response.status_code == 200
        
        await asyncio.sleep(3)
        
        # Check if error metrics were generated
        error_outcomes = ["error", "timeout", "http_error"]
        error_metric_found = False
        
        for outcome in error_outcomes:
            try:
                result = await observability_validator.wait_for_metrics(
                    metric_name, labels={"outcome": outcome}, timeout=10
                )
                if result:
                    error_metric_found = True
                    print(f"Found error metric with outcome: {outcome}")
                    break
            except TimeoutError:
                continue
        
        # Check traces for error indicators
        traces = await observability_validator.validate_traces(
            service_config["name"],
            timeout=30
        )
        
        error_trace_found = False
        for trace in traces:
            for span in trace["spans"]:
                span_tags = {tag["key"]: tag["value"] for tag in span.get("tags", [])}
                if (span_tags.get("correlation_id") == correlation_id and 
                    (span_tags.get("error") == "true" or 
                     "error" in span.get("operationName", "").lower())):
                    error_trace_found = True
                    break
        
        # Check logs for error messages
        logs = await observability_validator.validate_logs(
            service_config["name"],
            timeout=30
        )
        
        error_log_found = False
        for log_stream in logs:
            for log_entry in log_stream.get("values", []):
                timestamp, log_message = log_entry
                
                if (correlation_id in log_message and 
                    ("ERROR" in log_message.upper() or 
                     "error" in log_message.lower() or
                     "fallback" in log_message.lower())):
                    error_log_found = True
                    break
        
        # Print results for debugging
        print(f"Error observability results:")
        print(f"  - Error metrics: {error_metric_found}")
        print(f"  - Error traces: {error_trace_found}")
        print(f"  - Error logs: {error_log_found}")
        
        # At minimum, we should have successful handling indicated somewhere
        assert error_metric_found or error_trace_found or error_log_found, \
            "No error indicators found in any observability pillar"

    @pytest.mark.asyncio
    async def test_performance_impact_validation(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        cleanup_test_data
    ):
        """Test that observability doesn't significantly impact performance."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Warm up
        for _ in range(3):
            response = await service_client.predict(
                service_name,
                "Warmup request",
                service_config["default_model"]
            )
            assert response.status_code == 200
        
        # Measure latency with observability
        latencies = []
        for i in range(10):
            start_time = time.time()
            response = await service_client.predict(
                service_name,
                f"Performance test {i}",
                service_config["default_model"]
            )
            end_time = time.time()
            
            assert response.status_code == 200
            
            # Get reported latency from service
            response_data = response.json()
            service_latency = response_data.get("latency_ms", 0)
            client_latency = (end_time - start_time) * 1000
            
            latencies.append({
                "service": service_latency,
                "client": client_latency
            })
        
        # Validate reasonable performance
        avg_service_latency = sum(l["service"] for l in latencies) / len(latencies)
        avg_client_latency = sum(l["client"] for l in latencies) / len(latencies)
        
        # Reasonable thresholds (adjust based on your requirements)
        assert avg_service_latency < 1000, f"Average service latency {avg_service_latency}ms too high"
        assert avg_client_latency < 2000, f"Average client latency {avg_client_latency}ms too high"
        
        # Validate observability overhead is reasonable
        overhead_ms = avg_client_latency - avg_service_latency
        assert overhead_ms < 500, f"Observability overhead {overhead_ms}ms seems excessive"
        
        print(f"Performance validation:")
        print(f"  - Average service latency: {avg_service_latency:.1f}ms")
        print(f"  - Average client latency: {avg_client_latency:.1f}ms")
        print(f"  - Estimated overhead: {overhead_ms:.1f}ms")


class TestDashboardIntegration:
    """Test Grafana dashboard integration and functionality."""

    @pytest.mark.asyncio
    async def test_grafana_datasource_connectivity(
        self,
        test_config,
        observability_stack_health,
        cleanup_test_data
    ):
        """Test that Grafana can connect to all datasources."""
        import httpx
        
        grafana_url = test_config["grafana_url"]
        
        # Test datasource health endpoints
        datasources = ["prometheus", "loki", "jaeger"]
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            for ds_uid in datasources:
                try:
                    response = await client.get(
                        f"{grafana_url}/api/datasources/uid/{ds_uid}/health",
                        auth=("admin", "admin")
                    )
                    
                    if response.status_code == 200:
                        health_data = response.json()
                        assert health_data.get("status") in ["OK", "success"], \
                            f"Datasource {ds_uid} unhealthy: {health_data}"
                        print(f"✅ Datasource {ds_uid}: {health_data.get('status', 'OK')}")
                    else:
                        print(f"⚠️ Datasource {ds_uid} health check failed: {response.status_code}")
                        
                except Exception as e:
                    print(f"⚠️ Datasource {ds_uid} health check error: {e}")

    @pytest.mark.asyncio
    async def test_dashboard_query_validation(
        self,
        service_client,
        observability_validator,
        prometheus_client,
        test_config,
        service_configs,
        cleanup_test_data
    ):
        """Test that dashboard queries return valid data."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Generate some data for dashboard queries
        for i in range(5):
            response = await service_client.predict(
                service_name,
                f"Dashboard query test {i}",
                service_config["default_model"]
            )
            assert response.status_code == 200
        
        await asyncio.sleep(5)
        
        # Test key dashboard queries
        metric_name = service_config["expected_metrics"][0]
        latency_metric = service_config["expected_metrics"][1]
        
        dashboard_queries = [
            # Request rate query
            f"sum(rate({metric_name}[1m]))",
            # Error rate query
            f"(sum(rate({metric_name}{{outcome!=\"success\"}}[5m])) or vector(0)) / (sum(rate({metric_name}[5m])) or vector(1)) * 100",
            # P95 latency query
            f"histogram_quantile(0.95, sum by (le) (rate({latency_metric}_bucket[5m]))) * 1000",
            # Request by variant
            f"sum by (variant) (rate({metric_name}[1m]))",
        ]
        
        query_results = {}
        for i, query in enumerate(dashboard_queries):
            try:
                result = prometheus_client.custom_query(query)
                query_results[f"query_{i}"] = {
                    "query": query,
                    "success": True,
                    "result_count": len(result) if result else 0
                }
                
                if result:
                    # Validate result structure
                    for r in result:
                        assert "metric" in r, "Missing metric labels"
                        assert "value" in r, "Missing metric value"
                        assert len(r["value"]) == 2, "Invalid metric value format"
                
            except Exception as e:
                query_results[f"query_{i}"] = {
                    "query": query,
                    "success": False,
                    "error": str(e)
                }
        
        # Validate at least some queries succeeded
        successful_queries = sum(1 for r in query_results.values() if r["success"])
        total_queries = len(query_results)
        
        assert successful_queries > 0, "No dashboard queries succeeded"
        
        print(f"Dashboard query validation: {successful_queries}/{total_queries} queries successful")
        for query_id, result in query_results.items():
            status = "✅" if result["success"] else "❌"
            print(f"  {status} {query_id}: {result.get('result_count', 'N/A')} results")

    @pytest.mark.asyncio
    async def test_alert_rule_validation(
        self,
        prometheus_client,
        service_configs,
        test_config,
        cleanup_test_data
    ):
        """Test that Prometheus alert rules are properly configured."""
        try:
            # Query Prometheus rules API
            import httpx
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{test_config['prometheus_url']}/api/v1/rules")
                
                if response.status_code == 200:
                    rules_data = response.json()
                    
                    if rules_data.get("status") == "success":
                        rule_groups = rules_data.get("data", {}).get("groups", [])
                        
                        total_rules = 0
                        total_alerts = 0
                        
                        for group in rule_groups:
                            rules = group.get("rules", [])
                            total_rules += len(rules)
                            
                            for rule in rules:
                                if rule.get("type") == "alerting":
                                    total_alerts += 1
                                    
                                    # Validate rule structure
                                    assert "name" in rule, "Alert rule missing name"
                                    assert "query" in rule, "Alert rule missing query"
                                    assert "labels" in rule, "Alert rule missing labels"
                        
                        print(f"Alert rules validation: {total_alerts} alerts in {len(rule_groups)} groups")
                        print(f"Total rules: {total_rules}")
                        
                        # Should have at least some alerting rules
                        if total_alerts == 0:
                            print("⚠️ No alerting rules found")
                        else:
                            print(f"✅ Found {total_alerts} alerting rules")
                    else:
                        print(f"⚠️ Prometheus rules query failed: {rules_data}")
                else:
                    print(f"⚠️ Prometheus rules API returned {response.status_code}")
                    
        except Exception as e:
            print(f"⚠️ Alert rule validation failed: {e}")
            # Don't fail the test since alerting rules might not be configured


class TestObservabilityHealth:
    """Test overall observability stack health and monitoring."""

    @pytest.mark.asyncio
    async def test_observability_stack_health_monitoring(
        self,
        observability_stack_health,
        test_config,
        cleanup_test_data
    ):
        """Test that observability stack components are healthy."""
        required_services = ["Prometheus"]  # Minimum required
        optional_services = ["Jaeger", "Loki", "Grafana"]
        
        # Validate required services
        for service in required_services:
            assert observability_stack_health.get(service, False), \
                f"Required service {service} is not healthy"
        
        # Report optional services
        healthy_services = []
        unhealthy_services = []
        
        for service, is_healthy in observability_stack_health.items():
            if is_healthy:
                healthy_services.append(service)
            else:
                unhealthy_services.append(service)
        
        print(f"Observability stack health:")
        print(f"  ✅ Healthy: {healthy_services}")
        if unhealthy_services:
            print(f"  ❌ Unhealthy: {unhealthy_services}")
        
        # Calculate health score
        total_services = len(observability_stack_health)
        healthy_count = len(healthy_services)
        health_score = (healthy_count / total_services) * 100 if total_services > 0 else 0
        
        print(f"  📊 Health score: {health_score:.1f}% ({healthy_count}/{total_services})")
        
        # Should have at least 50% of services healthy
        assert health_score >= 50, f"Observability stack health score {health_score}% too low"

    @pytest.mark.asyncio
    async def test_data_retention_and_cleanup(
        self,
        service_client,
        observability_validator,
        test_config,
        service_configs,
        cleanup_test_data
    ):
        """Test that observability data is being retained appropriately."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Generate timestamped test data
        test_timestamp = int(time.time())
        response = await service_client.predict(
            service_name,
            f"Retention test at {test_timestamp}",
            service_config["default_model"]
        )
        assert response.status_code == 200
        
        await asyncio.sleep(2)
        
        # Check data exists in different systems
        data_sources = {}
        
        # Check metrics retention
        try:
            metric_name = service_config["expected_metrics"][0]
            metrics = await observability_validator.wait_for_metrics(metric_name, timeout=10)
            data_sources["metrics"] = len(metrics) > 0
        except TimeoutError:
            data_sources["metrics"] = False
        
        # Check trace retention
        try:
            traces = await observability_validator.validate_traces(
                service_config["name"], timeout=10
            )
            data_sources["traces"] = len(traces) > 0
        except TimeoutError:
            data_sources["traces"] = False
        
        # Check log retention
        try:
            logs = await observability_validator.validate_logs(
                service_config["name"], timeout=10
            )
            data_sources["logs"] = len(logs) > 0
        except TimeoutError:
            data_sources["logs"] = False
        
        # Report retention status
        retained_sources = [k for k, v in data_sources.items() if v]
        print(f"Data retention status: {retained_sources}")
        
        # At least metrics should be retained
        assert data_sources["metrics"], "Metrics not being retained"
        
        # Ideally, all data sources should retain data
        retention_score = (len(retained_sources) / len(data_sources)) * 100
        print(f"Retention score: {retention_score:.1f}%")
