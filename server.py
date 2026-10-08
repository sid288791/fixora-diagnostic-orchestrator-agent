"""
Fixora Diagnostic Orchestrator Agent - RCA engine powered by HolmesGPT.

Integrates with HolmesGPT to coordinate read-only diagnostic toolsets
(Grafana, Kibana, Kubernetes, Kafka, REST APIs, MCP servers, etc.)
and produce root cause analysis using a local Ollama LLM.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).parent
load_dotenv(APP_DIR / ".env")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

SERVICE_NAME = "fixora-diagnostic-orchestrator-agent"
VERSION = "0.2.0"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class DiagnoseRequest(BaseModel):
    """Payload for the /diagnose endpoint."""
    question: str = Field(
        ...,
        description="Incident description or diagnostic question",
        examples=["Why is the payment service returning 500 errors?"],
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional context (alert payload, service name, namespace, etc.)",
        examples=[{"service": "payment-api", "namespace": "production", "alert": "HighErrorRate"}],
    )


class AskRequest(BaseModel):
    """Payload for the /ask endpoint."""
    question: str = Field(
        ...,
        description="A free-form question to ask the RCA agent",
        examples=["What pods are in CrashLoopBackOff?"],
    )


class ToolCallResponse(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = {}
    result_summary: str = ""


class DiagnoseResponse(BaseModel):
    question: str
    analysis: str
    tool_calls: List[ToolCallResponse] = []
    status: str = "completed"
    error: Optional[str] = None


class ToolsetInfo(BaseModel):
    name: str
    description: str = ""
    status: str = "unknown"
    type: str = "unknown"
    tools: List[str] = []


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize HolmesEngine on startup."""
    from core.holmes_engine import get_engine

    logger.info("Starting %s v%s", SERVICE_NAME, VERSION)
    try:
        engine = get_engine()
        engine.initialize()
        logger.info("HolmesGPT engine ready")
    except Exception:
        logger.exception("Failed to initialize HolmesGPT engine - endpoints will return errors")
    yield
    logger.info("Shutting down %s", SERVICE_NAME)


app = FastAPI(
    title=SERVICE_NAME,
    version=VERSION,
    description="Diagnostic orchestrator agent - RCA engine powered by HolmesGPT + Ollama",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/healthcheck")
def healthcheck():
    """Basic liveness check."""
    from core.holmes_engine import get_engine

    engine = get_engine()
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": VERSION,
        "holmes_initialized": engine._initialized,
        "model": engine._fixora_config.llm.model,
    }


@app.get("/")
def root():
    return {
        "service": SERVICE_NAME,
        "version": VERSION,
        "description": "Diagnostic orchestrator agent - RCA engine powered by HolmesGPT",
        "endpoints": [
            "/healthcheck",
            "/diagnose",
            "/ask",
            "/toolsets",
            "/config",
        ],
    }


@app.post("/diagnose", response_model=DiagnoseResponse)
async def diagnose(request: DiagnoseRequest):
    """Run a full RCA investigation.

    The HolmesGPT agentic loop will:
    1. Analyze the question and context
    2. Call relevant diagnostic tools (Grafana, K8s, Kibana, etc.)
    3. Iterate until it has enough evidence
    4. Produce a structured root cause analysis
    """
    from core.holmes_engine import get_engine

    engine = get_engine()
    if not engine._initialized:
        raise HTTPException(status_code=503, detail="HolmesGPT engine not initialized")

    result = await engine.investigate(request.question, request.context)

    return DiagnoseResponse(
        question=result.question,
        analysis=result.analysis,
        tool_calls=[
            ToolCallResponse(
                tool_name=tc.tool_name,
                arguments=tc.arguments,
                result_summary=tc.result_summary,
            )
            for tc in result.tool_calls
        ],
        status=result.status,
        error=result.error,
    )


@app.post("/ask", response_model=DiagnoseResponse)
async def ask(request: AskRequest):
    """Ask a free-form question without structured incident context."""
    from core.holmes_engine import get_engine

    engine = get_engine()
    if not engine._initialized:
        raise HTTPException(status_code=503, detail="HolmesGPT engine not initialized")

    result = await engine.ask(request.question)

    return DiagnoseResponse(
        question=result.question,
        analysis=result.analysis,
        tool_calls=[
            ToolCallResponse(
                tool_name=tc.tool_name,
                arguments=tc.arguments,
                result_summary=tc.result_summary,
            )
            for tc in result.tool_calls
        ],
        status=result.status,
        error=result.error,
    )


@app.get("/toolsets", response_model=List[ToolsetInfo])
def list_toolsets():
    """List all loaded diagnostic toolsets and their status."""
    from core.holmes_engine import get_engine

    engine = get_engine()
    if not engine._initialized:
        raise HTTPException(status_code=503, detail="HolmesGPT engine not initialized")

    toolsets = engine.get_toolsets_info()
    return [ToolsetInfo(**ts) for ts in toolsets]


@app.get("/config")
def get_config():
    """Return the current (sanitized) configuration."""
    from core.holmes_engine import get_engine

    engine = get_engine()
    cfg = engine._fixora_config

    return {
        "llm": {
            "model": cfg.llm.model,
            "api_base": cfg.llm.api_base,
            "max_steps": cfg.llm.max_steps,
        },
        "builtin_toolsets": {
            name: {"enabled": ts.enabled}
            for name, ts in cfg.builtin_toolsets.items()
        },
        "mcp_servers": {
            name: {"description": srv.description, "enabled": srv.enabled}
            for name, srv in cfg.mcp_servers.items()
        },
        "custom_toolsets": cfg.custom_toolsets,
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    from core.config_loader import load_config

    config = load_config()
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
    )
