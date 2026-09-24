import os
import time
from fastapi import FastAPI, Response, Request, status
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Initialize OpenTelemetry
resource = Resource.create(attributes={"service.name": "gitops-microservice", "environment": os.getenv("ENVIRONMENT", "production")})
provider = TracerProvider(resource=resource)
processor = SimpleSpanProcessor(ConsoleSpanExporter())
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("gitops.app")

app = FastAPI(
    title="Autonomous GitOps Microservice",
    version=os.getenv("APP_VERSION", "v1.0.0"),
    description="Telemetry-instrumented microservice with chaos engineering hooks"
)
FastAPIInstrumentor.instrument_app(app)

# Prometheus Metrics
REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total count of HTTP requests handled",
    ["method", "endpoint", "status"]
)
REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "Histogram of request processing duration in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)
CHAOS_ACTIVE = Gauge(
    "app_chaos_active",
    "Flag indicating whether synthetic failure chaos is active (1 = active, 0 = healthy)"
)
CHAOS_ACTIVE.set(0)

# In-memory chaos state
state = {
    "chaos_active": False,
    "chaos_injected_at": None,
    "version": os.getenv("APP_VERSION", "v1.0.0")
}

@app.middleware("http")
async def prometheus_metrics_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    
    endpoint = request.url.path
    # Group chaotic root requests
    REQUESTS_TOTAL.labels(
        method=request.method,
        endpoint=endpoint,
        status=str(response.status_code)
    ).inc()
    
    REQUEST_DURATION_SECONDS.labels(
        method=request.method,
        endpoint=endpoint
    ).observe(duration)
    
    return response

@app.get("/healthz", tags=["Operations"])
async def healthz():
    """Liveness & Readiness probe endpoint."""
    return {
        "status": "healthy",
        "version": state["version"],
        "chaos_active": state["chaos_active"]
    }

@app.get("/metrics", tags=["Observability"])
async def metrics():
    """Prometheus exposition format endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/", tags=["Workload"])
async def root():
    """Main workload endpoint. Returns 500 when chaos is triggered."""
    with tracer.start_as_current_span("handle_root_workload") as span:
        span.set_attribute("chaos.active", state["chaos_active"])
        if state["chaos_active"]:
            span.set_attribute("error", True)
            span.record_exception(Exception("Chaos induced failure: synthetic service degradation"))
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "status": "error",
                    "error": "ChaosInducedFailure",
                    "message": "Synthetic service degradation active. Error budget consuming.",
                    "version": state["version"]
                }
            )
        
        return {
            "status": "ok",
            "message": "Autonomous GitOps Microservice operating nominally",
            "version": state["version"],
            "environment": os.getenv("ENVIRONMENT", "production")
        }

@app.post("/chaos/inject", tags=["Chaos Testing"])
async def inject_chaos():
    """Simulate a critical failure state by turning on 500 errors."""
    state["chaos_active"] = True
    state["chaos_injected_at"] = time.time()
    CHAOS_ACTIVE.set(1)
    return {
        "status": "chaos_active",
        "message": "Chaos injection enabled. GET / will now respond with HTTP 500.",
        "injected_at": state["chaos_injected_at"]
    }

@app.post("/chaos/reset", tags=["Chaos Testing"])
async def reset_chaos():
    """Restore normal operations."""
    state["chaos_active"] = False
    state["chaos_injected_at"] = None
    CHAOS_ACTIVE.set(0)
    return {
        "status": "nominal",
        "message": "Chaos reset. GET / will now respond with HTTP 200."
    }
