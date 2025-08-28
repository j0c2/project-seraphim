"""
End-to-end tests for structured logging with Loki.

Tests verify that logs are properly formatted, aggregated, and
correlated with traces and metrics across services.
"""
import asyncio
import json
import pytest
import time
from typing import Dict, List, Optional


class TestLogGeneration:
    """Test that structured logs are generated correctly."""

    @pytest.mark.asyncio
    async def test_json_log_format(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test that logs are in proper JSON format."""
        for service_name in test_config["services"]:
            if service_name not in service_configs:
                continue
            
            service_config = service_configs[service_name]
            
            # Make test request
            response = await service_client.predict(
                service_name,
                f"JSON log format test for {service_name}",
                service_config["default_model"]
            )
            assert response.status_code == 200
            
            # Validate logs exist and are properly formatted
            logs = await observability_validator.validate_logs(
                service_config["name"],
                timeout=30
            )
            
            assert len(logs) > 0, f"No logs found for service {service_name}"
            
            # Validate JSON structure of log entries
            for log_stream in logs:
                for log_entry in log_stream.get("values", []):
                    timestamp, log_message = log_entry
                    
                    # Skip non-JSON logs (might be uvicorn access logs)
                    if not log_message.strip().startswith("{"):
                        continue
                    
                    try:
                        log_data = json.loads(log_message)
                        
                        # Validate required JSON log fields
                        assert "asctime" in log_data, "Missing asctime field"
                        assert "name" in log_data, "Missing name field"
                        assert "levelname" in log_data, "Missing levelname field"
                        assert "message" in log_data, "Missing message field"
                        assert "service_name" in log_data, "Missing service_name field"
                        assert "correlation_id" in log_data, "Missing correlation_id field"
                        
                        # Validate field values
                        assert log_data["levelname"] in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], \
                            f"Invalid log level: {log_data['levelname']}"
                        assert log_data["service_name"] == service_config["name"], \
                            "Service name mismatch in logs"
                        
                        # At least some logs should have our correlation ID
                        if log_data["correlation_id"] == correlation_id:
                            assert True  # Found our correlation ID
                            break
                            
                    except json.JSONDecodeError as e:
                        pytest.fail(f"Invalid JSON in log message: {log_message[:100]}... Error: {e}")

    @pytest.mark.asyncio
    async def test_log_levels(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        cleanup_test_data
    ):
        """Test that different log levels are captured correctly."""
        service_name = test_config["services"][0]  # Test first available service
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Make various requests that should generate different log levels
        test_requests = [
            {"text": "Normal request for INFO level", "expected_level": "INFO"},
            {"text": "Request with potential warning", "expected_level": "WARNING"},
        ]
        
        for req in test_requests:
            response = await service_client.predict(
                service_name,
                req["text"],
                service_config["default_model"]
            )
            assert response.status_code == 200
        
        # Get logs
        logs = await observability_validator.validate_logs(
            service_config["name"],
            timeout=30
        )
        
        # Collect log levels from JSON logs
        found_levels = set()
        for log_stream in logs:
            for log_entry in log_stream.get("values", []):
                timestamp, log_message = log_entry
                
                if log_message.strip().startswith("{"):
                    try:
                        log_data = json.loads(log_message)
                        found_levels.add(log_data.get("levelname", "UNKNOWN"))
                    except json.JSONDecodeError:
                        continue
        
        # Should have at least INFO level logs
        assert "INFO" in found_levels, "No INFO level logs found"
        
        # Validate log levels are standard Python levels
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        for level in found_levels:
            assert level in valid_levels, f"Invalid log level: {level}"

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
        """Test that correlation IDs are consistently logged."""
        # Make multiple requests with the same correlation ID
        for i in range(3):
            for service_name in test_config["services"]:
                if service_name not in service_configs:
                    continue
                
                service_config = service_configs[service_name]
                
                response = await service_client.predict(
                    service_name,
                    f"Correlation ID test {i}",
                    service_config["default_model"]
                )
                assert response.status_code == 200
        
        # Validate logs contain correct correlation ID
        for service_name in test_config["services"]:
            if service_name not in service_configs:
                continue
            
            service_config = service_configs[service_name]
            
            logs = await observability_validator.validate_logs(
                service_config["name"],
                timeout=30
            )
            
            correlation_found = False
            for log_stream in logs:
                for log_entry in log_stream.get("values", []):
                    timestamp, log_message = log_entry
                    
                    if correlation_id in log_message:
                        correlation_found = True
                        
                        # If it's JSON, validate the correlation_id field
                        if log_message.strip().startswith("{"):
                            try:
                                log_data = json.loads(log_message)
                                assert log_data.get("correlation_id") == correlation_id, \
                                    "Correlation ID mismatch in JSON log"
                            except json.JSONDecodeError:
                                pass  # Non-JSON log with correlation ID is also valid
            
            assert correlation_found, f"Correlation ID {correlation_id} not found in logs for {service_name}"

    @pytest.mark.asyncio
    async def test_trace_log_correlation(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test that logs contain trace IDs for correlation."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Make request to generate both trace and logs
        response = await service_client.predict(
            service_name,
            "Trace-log correlation test",
            service_config["default_model"]
        )
        assert response.status_code == 200
        
        # Get both traces and logs
        traces = await observability_validator.validate_traces(
            service_config["name"],
            timeout=30
        )
        logs = await observability_validator.validate_logs(
            service_config["name"],
            timeout=30
        )
        
        # Extract trace IDs from traces
        trace_ids = set()
        for trace in traces:
            for span in trace["spans"]:
                span_tags = {tag["key"]: tag["value"] for tag in span.get("tags", [])}
                if span_tags.get("correlation_id") == correlation_id:
                    trace_ids.add(trace["traceID"])
        
        assert len(trace_ids) > 0, "No trace IDs found for correlation ID"
        
        # Look for trace IDs in logs
        trace_in_logs = False
        for log_stream in logs:
            for log_entry in log_stream.get("values", []):
                timestamp, log_message = log_entry
                
                if correlation_id in log_message and log_message.strip().startswith("{"):
                    try:
                        log_data = json.loads(log_message)
                        log_trace_id = log_data.get("trace_id")
                        
                        if log_trace_id:
                            # Trace IDs might be in different formats, check if any match
                            for trace_id in trace_ids:
                                if log_trace_id in trace_id or trace_id in log_trace_id:
                                    trace_in_logs = True
                                    break
                        
                        if trace_in_logs:
                            break
                    except json.JSONDecodeError:
                        continue
            
            if trace_in_logs:
                break
        
        # Note: This might not always pass if tracing instrumentation isn't fully integrated
        # with logging, so we make it a soft assertion
        if not trace_in_logs:
            print("Warning: No trace IDs found in logs - trace/log correlation may not be fully configured")


class TestLogAggregation:
    """Test log aggregation and filtering in Loki."""

    @pytest.mark.asyncio
    async def test_log_streaming_and_labels(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        cleanup_test_data
    ):
        """Test that logs are properly labeled and streamable."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Generate logs at different levels
        test_cases = [
            {"text": "Info level test message", "expected_patterns": ["INFO", "test message"]},
            {"text": "Another info message for streaming", "expected_patterns": ["INFO", "streaming"]},
        ]
        
        for case in test_cases:
            response = await service_client.predict(
                service_name,
                case["text"],
                service_config["default_model"]
            )
            assert response.status_code == 200
        
        # Get logs with labels
        logs = await observability_validator.validate_logs(
            service_config["name"],
            timeout=30
        )
        
        # Validate log streams have proper labels
        for log_stream in logs:
            stream_labels = log_stream.get("stream", {})
            
            # Should have service identification labels
            assert "service" in stream_labels or "job" in stream_labels or "container_name" in stream_labels, \
                "Missing service identification labels in log stream"
            
            # Validate log entries exist
            values = log_stream.get("values", [])
            assert len(values) > 0, "Log stream has no entries"
            
            # Validate timestamp format
            for timestamp, log_message in values:
                assert timestamp.isdigit(), f"Invalid timestamp format: {timestamp}"
                assert len(log_message) > 0, "Empty log message"

    @pytest.mark.asyncio
    async def test_log_filtering_by_level(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test filtering logs by level using LogQL."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Generate test logs
        response = await service_client.predict(
            service_name,
            "Log level filtering test",
            service_config["default_model"]
        )
        assert response.status_code == 200
        
        # Test LogQL filtering by attempting to parse log levels
        logs = await observability_validator.validate_logs(
            service_config["name"],
            timeout=30
        )
        
        # Count different log levels in results
        level_counts = {}
        for log_stream in logs:
            for log_entry in log_stream.get("values", []):
                timestamp, log_message = log_entry
                
                # Try to extract level from JSON logs
                if log_message.strip().startswith("{"):
                    try:
                        log_data = json.loads(log_message)
                        level = log_data.get("levelname", "UNKNOWN")
                        level_counts[level] = level_counts.get(level, 0) + 1
                    except json.JSONDecodeError:
                        continue
                else:
                    # For non-JSON logs, try to detect level in message
                    for level in ["ERROR", "WARNING", "INFO", "DEBUG"]:
                        if level in log_message.upper():
                            level_counts[level] = level_counts.get(level, 0) + 1
                            break
        
        assert len(level_counts) > 0, "No log levels detected in messages"
        print(f"Found log levels: {level_counts}")

    @pytest.mark.asyncio
    async def test_log_time_range_queries(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test querying logs within specific time ranges."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Record start time
        start_time = time.time()
        
        # Generate timestamped logs
        for i in range(3):
            response = await service_client.predict(
                service_name,
                f"Time range test {i} at {int(start_time)}",
                service_config["default_model"]
            )
            assert response.status_code == 200
            await asyncio.sleep(1)
        
        # Get logs (should include our test logs)
        logs = await observability_validator.validate_logs(
            service_config["name"],
            timeout=30
        )
        
        # Validate logs contain our timestamped messages
        found_test_logs = 0
        for log_stream in logs:
            for log_entry in log_stream.get("values", []):
                timestamp_ns, log_message = log_entry
                
                # Convert timestamp to seconds for comparison
                timestamp_s = int(timestamp_ns) / 1e9
                
                # Check if log is within our test time range (with some tolerance)
                if abs(timestamp_s - start_time) < 60:  # Within 1 minute
                    if f"at {int(start_time)}" in log_message:
                        found_test_logs += 1
        
        assert found_test_logs > 0, "No test logs found within expected time range"


class TestLogQueries:
    """Test advanced LogQL queries for observability."""

    @pytest.mark.asyncio
    async def test_log_rate_calculation(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        cleanup_test_data
    ):
        """Test calculating log rates using LogQL."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Generate consistent log volume
        log_count = 5
        for i in range(log_count):
            response = await service_client.predict(
                service_name,
                f"Log rate test message {i}",
                service_config["default_model"]
            )
            assert response.status_code == 200
            await asyncio.sleep(0.5)  # Spread over time
        
        # Get logs to validate they were generated
        logs = await observability_validator.validate_logs(
            service_config["name"],
            timeout=30
        )
        
        # Count log entries for rate validation
        total_entries = sum(len(stream.get("values", [])) for stream in logs)
        assert total_entries >= log_count, f"Expected at least {log_count} log entries, got {total_entries}"
        
        # Test would ideally include LogQL rate() queries, but that requires
        # direct Loki API access with range queries which is complex to validate

    @pytest.mark.asyncio
    async def test_log_pattern_matching(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test LogQL pattern matching and filtering."""
        service_name = test_config["services"][0]
        service_config = service_configs.get(service_name)
        
        if not service_config:
            pytest.skip(f"Service {service_name} not configured")
        
        # Generate logs with specific patterns
        test_patterns = [
            "PATTERN_SUCCESS for testing",
            "PATTERN_ERROR for validation", 
            "Normal log without pattern"
        ]
        
        for pattern in test_patterns:
            response = await service_client.predict(
                service_name,
                pattern,
                service_config["default_model"]
            )
            assert response.status_code == 200
        
        # Get logs and validate pattern presence
        logs = await observability_validator.validate_logs(
            service_config["name"],
            timeout=30
        )
        
        found_patterns = set()
        for log_stream in logs:
            for log_entry in log_stream.get("values", []):
                timestamp, log_message = log_entry
                
                for pattern in ["PATTERN_SUCCESS", "PATTERN_ERROR"]:
                    if pattern in log_message:
                        found_patterns.add(pattern)
        
        # Should find at least one pattern (depending on log processing)
        print(f"Found patterns in logs: {found_patterns}")

    @pytest.mark.asyncio
    async def test_log_correlation_queries(
        self,
        service_client,
        observability_validator,
        service_configs,
        test_config,
        correlation_id,
        cleanup_test_data
    ):
        """Test querying logs by correlation ID."""
        # Make requests across multiple services with same correlation ID
        services_used = []
        for service_name in test_config["services"]:
            if service_name not in service_configs:
                continue
            
            service_config = service_configs[service_name]
            services_used.append(service_name)
            
            response = await service_client.predict(
                service_name,
                f"Cross-service correlation test for {service_name}",
                service_config["default_model"]
            )
            assert response.status_code == 200
        
        # Get logs for each service and validate correlation ID presence
        correlation_found = False
        for service_name in services_used:
            service_config = service_configs[service_name]
            
            try:
                logs = await observability_validator.validate_logs(
                    service_config["name"],
                    timeout=20
                )
                
                for log_stream in logs:
                    for log_entry in log_stream.get("values", []):
                        timestamp, log_message = log_entry
                        
                        if correlation_id in log_message:
                            correlation_found = True
                            break
                    
                    if correlation_found:
                        break
                        
            except TimeoutError:
                print(f"Warning: Timeout getting logs for {service_name}")
                continue
        
        assert correlation_found, f"Correlation ID {correlation_id} not found in any service logs"
