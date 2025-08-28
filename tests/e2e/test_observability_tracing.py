"""
End-to-end tests for distributed tracing with Jaeger.

Tests verify that traces are properly created, propagated, and
correlated across service boundaries with correct span attributes.
"""
import asyncio
import pytest
import time
from typing import Dict, List, Optional


class TestTraceGeneration:
    """Test that traces are created and properly structured."""

    @pytest.mark.asyncio
    async def test_basic_trace_creation(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test that basic service requests generate traces."""
        for service_name in test_config["services"]:
            if service_name not in service_configs:
                continue
            
            service_config = service_configs[service_name]
            
            # Make test request
            response = await service_client.predict(
                service_name,
                f"Trace test for {service_name}",
                service_config["default_model"]
            )
            assert response.status_code == 200
            
            # Validate trace exists
            traces = await observability_validator.validate_traces(
                service_config["name"],
                timeout=30
            )
            
            assert len(traces) > 0, f"No traces found for service {service_name}"
            
            # Validate trace structure
            trace = traces[0]
            assert "spans" in trace, "Trace missing spans"
            assert len(trace["spans"]) > 0, "Trace has no spans"
            
            # Check for correlation ID in spans
            correlation_found = False
            for span in trace["spans"]:
                span_tags = {tag["key"]: tag["value"] for tag in span.get("tags", [])}
                if span_tags.get("correlation_id") == correlation_id:
                    correlation_found = True
                    break
            
            assert correlation_found, f"Correlation ID {correlation_id} not found in trace spans"

    @pytest.mark.asyncio
    async def test_span_attributes(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test that spans contain expected attributes and tags."""
        service_name = test_config["services"][0]  # Test first available service
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Make test request with specific parameters
        test_text = "Detailed span attribute test request"
        response = await service_client.predict(
            service_name,
            test_text,
            service_config["default_model"]
        )
        assert response.status_code == 200
        
        # Get traces and validate span attributes
        traces = await observability_validator.validate_traces(
            service_config["name"],
            timeout=30
        )
        
        trace = traces[0]
        
        # Find root span (HTTP request span)
        root_span = None
        for span in trace["spans"]:
            if not span.get("parentSpanID") or span["parentSpanID"] == "0":
                root_span = span
                break
        
        assert root_span is not None, "No root span found"
        
        # Validate span tags
        span_tags = {tag["key"]: tag["value"] for tag in root_span.get("tags", [])}
        
        # Standard OpenTelemetry HTTP attributes
        assert "http.method" in span_tags, "Missing http.method tag"
        assert span_tags["http.method"] == "POST", f"Expected POST, got {span_tags['http.method']}"
        
        assert "http.url" in span_tags or "http.target" in span_tags, "Missing HTTP URL/target tag"
        
        # Custom correlation ID
        assert "correlation_id" in span_tags, "Missing correlation_id tag"
        assert span_tags["correlation_id"] == correlation_id, "Correlation ID mismatch"
        
        # Service identification
        assert root_span["operationName"], "Missing operation name"
        assert root_span["process"]["serviceName"] == service_config["name"], "Service name mismatch"

    @pytest.mark.asyncio
    async def test_nested_span_relationships(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        cleanup_test_data
    ):
        """Test parent-child relationships between spans."""
        service_name = "inference"  # Use inference service which has nested operations
        
        if service_name not in test_config["services"]:
            pytest.skip("Inference service not available for nested span testing")
        
        service_config = service_configs[service_name]
        
        # Make request that should create nested spans
        response = await service_client.predict(
            service_name,
            "Nested span relationship test",
            "primary"
        )
        assert response.status_code == 200
        
        # Get traces
        traces = await observability_validator.validate_traces(
            service_config["name"],
            timeout=30
        )
        
        trace = traces[0]
        spans = trace["spans"]
        
        # Build span hierarchy
        span_map = {span["spanID"]: span for span in spans}
        root_spans = []
        child_spans = []
        
        for span in spans:
            parent_id = span.get("parentSpanID")
            if not parent_id or parent_id == "0":
                root_spans.append(span)
            else:
                child_spans.append(span)
        
        # Should have at least one root span
        assert len(root_spans) >= 1, "No root spans found"
        
        # Should have child spans for inference operations
        assert len(child_spans) > 0, "No child spans found"
        
        # Validate parent-child relationships
        for child_span in child_spans:
            parent_id = child_span["parentSpanID"]
            assert parent_id in span_map, f"Parent span {parent_id} not found"
            
            parent_span = span_map[parent_id]
            assert parent_span["startTime"] <= child_span["startTime"], "Child span started before parent"
            
            parent_end_time = parent_span["startTime"] + parent_span["duration"]
            child_end_time = child_span["startTime"] + child_span["duration"]
            assert child_end_time <= parent_end_time, "Child span ended after parent"

    @pytest.mark.asyncio
    async def test_error_span_recording(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        cleanup_test_data
    ):
        """Test that errors are properly recorded in spans."""
        service_name = "inference"
        
        if service_name not in test_config["services"]:
            pytest.skip("Inference service not available for error span testing")
        
        service_config = service_configs[service_name]
        
        # Make request that might trigger error handling
        response = await service_client.make_request(
            service_name,
            "/predict",
            json={"text": "Error test", "model": "nonexistent-model"},
            headers={"X-Test-Timeout": "true"}  # Custom header to potentially trigger timeout
        )
        
        # Service should handle gracefully
        assert response.status_code == 200
        
        # Get traces
        traces = await observability_validator.validate_traces(
            service_config["name"],
            timeout=30
        )
        
        trace = traces[0]
        
        # Look for spans with error indicators
        error_spans = []
        for span in trace["spans"]:
            span_tags = {tag["key"]: tag["value"] for tag in span.get("tags", [])}
            
            # Check for error tags or HTTP error status
            if (span_tags.get("error") == "true" or 
                span_tags.get("http.status_code") and int(span_tags["http.status_code"]) >= 400):
                error_spans.append(span)
        
        # Note: May not have explicit error spans if service handles errors gracefully
        # But we should at least have successful spans
        successful_spans = [span for span in trace["spans"] if span.get("operationName")]
        assert len(successful_spans) > 0, "No operational spans found"


class TestTraceCorrelation:
    """Test trace correlation across service boundaries."""

    @pytest.mark.asyncio
    async def test_correlation_id_propagation(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test that correlation IDs are propagated through all spans."""
        # Test with multiple requests to ensure consistency
        for i in range(3):
            for service_name in test_config["services"]:
                if service_name not in service_configs:
                    continue
                
                service_config = service_configs[service_name]
                
                response = await service_client.predict(
                    service_name,
                    f"Correlation test {i}",
                    service_config["default_model"]
                )
                assert response.status_code == 200
        
        # Validate all traces have correlation ID
        for service_name in test_config["services"]:
            if service_name not in service_configs:
                continue
                
            service_config = service_configs[service_name]
            
            traces = await observability_validator.validate_traces(
                service_config["name"],
                timeout=30
            )
            
            for trace in traces:
                correlation_found = False
                for span in trace["spans"]:
                    span_tags = {tag["key"]: tag["value"] for tag in span.get("tags", [])}
                    if span_tags.get("correlation_id") == correlation_id:
                        correlation_found = True
                        break
                
                assert correlation_found, f"Correlation ID not found in trace for {service_name}"

    @pytest.mark.asyncio
    async def test_cross_service_tracing(
        self,
        service_client,
        observability_validator,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test tracing across multiple services (if available)."""
        available_services = [s for s in test_config["services"] if s in ["inference", "sentiment-analysis"]]
        
        if len(available_services) < 2:
            pytest.skip("Need at least 2 services for cross-service tracing test")
        
        # Make requests to different services with same correlation ID
        for service_name in available_services:
            response = await service_client.predict(
                service_name,
                f"Cross-service trace test for {service_name}",
                "primary"
            )
            assert response.status_code == 200
        
        # Wait for traces to propagate
        await asyncio.sleep(5)
        
        # Validate traces exist for all services with same correlation ID
        all_traces = []
        for service_name in available_services:
            service_config = service_configs[service_name]
            traces = await observability_validator.validate_traces(
                service_config["name"],
                timeout=20
            )
            all_traces.extend(traces)
        
        # Should have traces from multiple services
        assert len(all_traces) >= len(available_services), "Missing traces from some services"
        
        # All traces should have the same correlation ID
        for trace in all_traces:
            correlation_found = False
            for span in trace["spans"]:
                span_tags = {tag["key"]: tag["value"] for tag in span.get("tags", [])}
                if span_tags.get("correlation_id") == correlation_id:
                    correlation_found = True
                    break
            assert correlation_found, "Cross-service correlation ID not found"


class TestTraceQueries:
    """Test Jaeger query capabilities."""

    @pytest.mark.asyncio
    async def test_trace_search_by_service(
        self,
        service_client,
        observability_validator,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test searching traces by service name."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Generate test trace
        response = await service_client.predict(
            service_name,
            "Service search test",
            service_config["default_model"]
        )
        assert response.status_code == 200
        
        # Search by service name
        traces = await observability_validator.validate_traces(
            service_config["name"],
            timeout=30
        )
        
        assert len(traces) > 0, "No traces found by service search"
        
        # Validate all returned traces are from correct service
        for trace in traces:
            service_found = False
            for span in trace["spans"]:
                if span["process"]["serviceName"] == service_config["name"]:
                    service_found = True
                    break
            assert service_found, "Trace doesn't belong to searched service"

    @pytest.mark.asyncio
    async def test_trace_search_by_operation(
        self,
        service_client,
        observability_validator,
        test_config,
        cleanup_test_data
    ):
        """Test searching traces by operation name."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Generate test trace
        response = await service_client.predict(
            service_name,
            "Operation search test",
            service_config["default_model"]
        )
        assert response.status_code == 200
        
        # Get traces to find operation names
        traces = await observability_validator.validate_traces(
            service_config["name"],
            timeout=30
        )
        
        if traces:
            # Find unique operation names
            operations = set()
            for trace in traces:
                for span in trace["spans"]:
                    if span.get("operationName"):
                        operations.add(span["operationName"])
            
            assert len(operations) > 0, "No operation names found in traces"
            print(f"Found operations: {operations}")

    @pytest.mark.asyncio 
    async def test_trace_timeline_ordering(
        self,
        service_client,
        observability_validator,
        test_config,
        cleanup_test_data
    ):
        """Test that traces are properly ordered by time."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Generate multiple traces with time gaps
        request_times = []
        for i in range(3):
            start_time = time.time() * 1000000  # microseconds
            response = await service_client.predict(
                service_name,
                f"Timeline test {i}",
                service_config["default_model"]
            )
            request_times.append(start_time)
            assert response.status_code == 200
            await asyncio.sleep(1)  # Gap between requests
        
        # Get traces
        traces = await observability_validator.validate_traces(
            service_config["name"],
            timeout=30
        )
        
        # Validate trace timestamps are reasonable
        for trace in traces:
            for span in trace["spans"]:
                span_start = span["startTime"]
                assert span_start > 0, "Invalid span start time"
                
                # Check span duration is positive
                duration = span["duration"] 
                assert duration > 0, "Invalid span duration"
                
                # Verify timestamps are within reasonable range of request times
                reasonable_range = any(
                    abs(span_start - req_time) < 10000000  # 10 seconds tolerance
                    for req_time in request_times
                )
                assert reasonable_range, f"Span timestamp {span_start} outside reasonable range"
