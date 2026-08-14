# fixora-diagnostic-orchestrator-agent

Diagnostic orchestrator agent for Fixora. Coordinates a set of read-only diagnostic
agents that gather evidence (metrics, logs, traces, topics, pods, deployments, etc.)
on behalf of the main `fixora-orchestrator-agent` during investigation.

This is currently a basic project skeleton - agent logic will be added later.

## Layout

```
server.py                       # FastAPI app entrypoint (healthcheck for now)
agents/grafana_agent.py         # Metrics & dashboards
agents/kibana_agent.py          # Logs & search
agents/opentelemetry_agent.py   # Traces & spans
agents/kafka_agent.py           # Consumer lag, topics, brokers
agents/kubernetes_agent.py      # Pods, events, deployments
agents/deployment_agent.py      # Changes, releases, config
agents/other_tools_agent.py     # DB, cache, cloud, APM, etc.
```

## Setup

```bash
cd fixora-diagnostic-orchestrator-agent
python -m venv .venv

# Windows (Git Bash)
./.venv/Scripts/python.exe -m pip install -r requirements.txt
# macOS/Linux
source .venv/bin/activate && pip install -r requirements.txt

cp .env.example .env
# edit .env with real values (Grafana/Kibana/Kafka/Kube connection details)
```

## Run

```bash
python -m uvicorn server:app --host 0.0.0.0 --port 8092
```

Verify: `curl http://localhost:8092/healthcheck` -> `{"status":"ok"}`
