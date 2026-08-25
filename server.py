"""
Fixora Diagnostic Orchestrator Agent - coordinates read-only diagnostic agents
(Grafana, Kibana, OpenTelemetry, Kafka, Kubernetes, Deployment, other tools)
to collect evidence for the main fixora-orchestrator-agent.

Phase 1: only KibanaAgent is wired to a real backend (Elastic MCP server).
Any other agent name is returned as "not available in this phase" evidence
rather than erroring, so the DiagnosticLoop upstream degrades gracefully if
it ever asks for one before it's implemented.
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from agents.kibana_agent import KibanaAgent
from mcp_clients.elastic_mcp_client import ElasticMcpClient

APP_DIR = Path(__file__).parent
load_dotenv(APP_DIR / ".env")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8092"))
ELASTIC_URL = os.environ.get("ELASTIC_URL", "http://localhost:9201")
KIBANA_LOG_INDEX = os.environ.get("KIBANA_LOG_INDEX", "fixora-app-logs")

SERVICE_NAME = "fixora-diagnostic-orchestrator-agent"

app = FastAPI(title=SERVICE_NAME, version="0.1.0")

WIRED_AGENTS = {"kibana"}


def get_kibana_agent() -> KibanaAgent:
    return KibanaAgent(mcp_client=ElasticMcpClient(ELASTIC_URL), index=KIBANA_LOG_INDEX)


class EvidenceRequestItem(BaseModel):
    agent: str
    check: str
    target_hypothesis: Optional[str] = None
    reason: Optional[str] = None


class CollectEvidenceRequest(BaseModel):
    incident_id: str
    alert: Dict[str, Any] = {}
    # Bounded: DiagnosticLoop's own max_checks_per_iteration caps requests per round to a
    # handful, and each "kibana" request spawns its own Elastic MCP subprocess (no pooled
    # session in phase 1) -- an unbounded list here would let one call fork unboundedly many
    # npx processes.
    requests: List[EvidenceRequestItem] = Field(max_length=20)


@app.get("/healthcheck")
def healthcheck():
    return {"status": "ok", "service": SERVICE_NAME, "version": "0.1.0"}


@app.post("/api/v1/collect-evidence")
async def collect_evidence(
    request: CollectEvidenceRequest,
    kibana_agent: KibanaAgent = Depends(get_kibana_agent),
):
    evidence = []
    for req in request.requests:
        agent_name = req.agent.lower().strip()
        if agent_name == "kibana":
            result = await kibana_agent.check(req.check, request.alert)
        elif agent_name in WIRED_AGENTS:
            result = {"finding": f"Agent '{agent_name}' has no check handler wired.", "anomaly": False}
        else:
            result = {"finding": f"Agent '{agent_name}' is not available in this phase.", "anomaly": False}

        evidence.append({
            "agent": agent_name,
            "check": req.check,
            "target_hypothesis": req.target_hypothesis,
            **result,
        })

    return {"evidence": evidence}


@app.get("/")
def root():
    return {
        "service": SERVICE_NAME,
        "version": "0.1.0",
        "description": "Diagnostic orchestrator agent - coordinates read-only diagnostic agents",
        "endpoints": ["/healthcheck", "/api/v1/collect-evidence"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
