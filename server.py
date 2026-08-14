"""
Fixora Diagnostic Orchestrator Agent - coordinates read-only diagnostic agents
(Grafana, Kibana, OpenTelemetry, Kafka, Kubernetes, Deployment, other tools)
to collect evidence for the main fixora-orchestrator-agent.

This is a skeleton only - agent logic to be added later.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

APP_DIR = Path(__file__).parent
load_dotenv(APP_DIR / ".env")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8092"))

SERVICE_NAME = "fixora-diagnostic-orchestrator-agent"

app = FastAPI(title=SERVICE_NAME, version="0.1.0")


@app.get("/healthcheck")
def healthcheck():
    return {"status": "ok", "service": SERVICE_NAME, "version": "0.1.0"}


@app.get("/")
def root():
    return {
        "service": SERVICE_NAME,
        "version": "0.1.0",
        "description": "Diagnostic orchestrator agent - coordinates read-only diagnostic agents",
        "endpoints": ["/healthcheck"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
