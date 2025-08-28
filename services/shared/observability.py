"""
Shared observability utilities for Project Seraphim services.

This module provides standardized logging and tracing configuration
that can be reused across different inference services.
"""

import json
import logging
import os
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Optional

from opentelemetry import trace, baggage, context
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from pythonjsonlogger import jsonlogger


class CorrelationIdFilter(logging.Filter):
    """Add correlation ID to log records from OpenTelemetry context."""
    
    def filter(self, record):
        # Get trace context
        span = trace.get_current_span()
        if span.is_recording():
            span_context = span.get_span_context()
            record.trace_id = format(span_context.trace_id, '032x')
            record.span_id = format(span_context.span_id, '016x')
        else:
            record.trace_id = None
            record.span_id = None
            
        # Get correlation ID from baggage
        correlation_id = baggage.get_baggage("correlation_id")
        record.correlation_id = correlation_id or str(uuid.uuid4())
        
        return True


def setup_logging(service_name: str, log_level: Optional[str] = None) -> logging.Logger:
    """
    Configure structured JSON logging with correlation IDs.
    
    Args:
        service_name: Name of the service for logging context
        log_level: Optional log level override
        
    Returns:
        Configured logger instance
    """
    log_level = log_level or os.environ.get("LOG_LEVEL", "INFO").upper()
    
    # Create custom formatter with trace/correlation context
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s %(service_name)s %(trace_id)s %(span_id)s %(correlation_id)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        static_fields={"service_name": service_name}
    )
    
    # Configure handler
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationIdFilter())
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    # Return service-specific logger
    logger = logging.getLogger(service_name)
    logger.info("Structured logging initialized", extra={
        "log_level": log_level,
        "service_name": service_name
    })
    
    return logger


def setup_tracing(service_name: str, service_version: str = "unknown") -> trace.Tracer:
    """
    Configure OpenTelemetry distributed tracing.
    
    Args:
        service_name: Name of the service
        service_version: Version of the service
        
    Returns:
        Configured tracer instance
    """
    # Set up tracer provider with service info
    resource_attributes = {
        "service.name": service_name,
        "service.version": service_version,
    }
    
    from opentelemetry.sdk.resources import Resource
    resource = Resource.create(resource_attributes)
    
    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)
    
    # Configure exporters based on environment
    exporters = []
    
    # Jaeger exporter (primary)
    jaeger_endpoint = os.environ.get("JAEGER_ENDPOINT")
    if jaeger_endpoint or os.environ.get("JAEGER_AGENT_HOST"):
        try:
            jaeger_exporter = JaegerExporter(
                agent_host_name=os.environ.get("JAEGER_AGENT_HOST", "jaeger"),
                agent_port=int(os.environ.get("JAEGER_AGENT_PORT", "6831")),
            )
            exporters.append(jaeger_exporter)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Failed to configure Jaeger exporter", 
                extra={"error": str(e)}
            )
    
    # OTLP exporter (alternative)
    otlp_endpoint = os.environ.get("OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            otlp_exporter = OTLPSpanExporter(
                endpoint=otlp_endpoint,
                insecure=True
            )
            exporters.append(otlp_exporter)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Failed to configure OTLP exporter",
                extra={"error": str(e)}
            )
    
    # Console exporter for development
    if os.environ.get("TRACE_CONSOLE", "false").lower() == "true":
        exporters.append(ConsoleSpanExporter())
    
    # Add span processors
    for exporter in exporters:
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    
    tracer = trace.get_tracer(service_name, service_version)
    
    logging.getLogger(__name__).info(
        "Distributed tracing initialized",
        extra={
            "service_name": service_name,
            "service_version": service_version,
            "exporters": len(exporters)
        }
    )
    
    return tracer


def instrument_fastapi(app, service_name: str):
    """
    Instrument FastAPI application with automatic tracing.
    
    Args:
        app: FastAPI application instance
        service_name: Name of the service
    """
    FastAPIInstrumentor.instrument_app(
        app,
        server_request_hook=_server_request_hook,
        client_request_hook=_client_request_hook,
    )


def instrument_httpx():
    """Instrument httpx HTTP client with automatic tracing."""
    HTTPXClientInstrumentor().instrument()


def _server_request_hook(span: trace.Span, scope: dict):
    """Hook to add custom attributes to server spans."""
    if span and span.is_recording():
        # Add custom attributes
        headers = dict(scope.get("headers", []))
        
        # Add user agent
        user_agent = headers.get(b"user-agent")
        if user_agent:
            span.set_attribute("http.user_agent", user_agent.decode())
        
        # Add correlation ID from header or generate new one
        correlation_id = headers.get(b"x-correlation-id")
        if not correlation_id:
            correlation_id = str(uuid.uuid4()).encode()
        
        correlation_id_str = correlation_id.decode()
        span.set_attribute("correlation_id", correlation_id_str)
        
        # Set correlation ID in baggage for downstream services
        ctx = baggage.set_baggage("correlation_id", correlation_id_str)
        context.attach(ctx)


def _client_request_hook(span: trace.Span, request):
    """Hook to add custom attributes to client spans."""
    if span and span.is_recording():
        # Add correlation ID to outgoing requests
        correlation_id = baggage.get_baggage("correlation_id")
        if correlation_id and hasattr(request, "headers"):
            request.headers["X-Correlation-Id"] = correlation_id


@contextmanager
def trace_operation(operation_name: str, **attributes):
    """
    Context manager for creating custom spans.
    
    Args:
        operation_name: Name of the operation being traced
        **attributes: Additional span attributes
    
    Example:
        with trace_operation("model_prediction", model_name="bert", version="1.0"):
            result = model.predict(data)
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(operation_name) as span:
        # Add custom attributes
        for key, value in attributes.items():
            span.set_attribute(key, str(value))
        
        try:
            yield span
        except Exception as e:
            # Record exception in span
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise


def add_span_attributes(**attributes):
    """
    Add attributes to the current span.
    
    Args:
        **attributes: Key-value pairs to add as span attributes
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        for key, value in attributes.items():
            span.set_attribute(key, str(value))


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID from context."""
    return baggage.get_baggage("correlation_id")


def set_correlation_id(correlation_id: str):
    """Set correlation ID in the current context."""
    ctx = baggage.set_baggage("correlation_id", correlation_id)
    context.attach(ctx)


def sanitize_for_json_logging(value: Any) -> str:
    """
    Sanitize a value for safe inclusion in JSON logs.
    
    This function handles values that might contain unescaped newlines,
    special characters, or other content that could break JSON parsing.
    
    Args:
        value: The value to sanitize
        
    Returns:
        A string safe for JSON logging
    """
    if value is None:
        return "null"
    
    # Convert to string if not already
    str_value = str(value)
    
    # If it looks like JSON, try to parse and re-serialize to ensure proper escaping
    if str_value.strip().startswith(('{', '[', '"')) and len(str_value) > 1:
        try:
            # Try to parse as JSON
            parsed = json.loads(str_value)
            # Re-serialize with proper escaping
            return json.dumps(parsed, separators=(',', ':'), ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            # If it's not valid JSON, escape it as a string
            pass
    
    # For non-JSON strings, escape special characters
    # Replace newlines, tabs, and other problematic characters
    sanitized = str_value.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
    sanitized = sanitized.replace('"', '\\"').replace('\\', '\\\\')
    
    # Truncate very long strings to prevent log bloat
    if len(sanitized) > 1000:
        sanitized = sanitized[:997] + '...'
    
    return sanitized
