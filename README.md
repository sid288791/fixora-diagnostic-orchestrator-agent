# fixora-diagnostic-orchestrator-agent

RCA (Root Cause Analysis) engine for Fixora, powered by [HolmesGPT](https://github.com/HolmesGPT/holmesgpt) (CNCF sandbox project) and local Ollama models.

Coordinates read-only diagnostic toolsets (Grafana, Kibana, Kubernetes, Kafka, REST APIs, MCP servers, databases, etc.) to gather evidence and produce structured root cause analysis.

## Architecture

```
                    +-----------------------+
                    |    FastAPI Server      |
                    |  /diagnose  /ask       |
                    |  /toolsets  /config    |
                    +-----------+-----------+
                                |
                    +-----------v-----------+
                    |    HolmesGPT Engine    |
                    |   (Python SDK embed)   |
                    +-----------+-----------+
                                |
              +-----------------+-----------------+
              |                 |                 |
    +---------v------+  +------v-------+  +------v-------+
    | Built-in       |  | Custom YAML  |  | MCP Servers  |
    | Toolsets        |  | Toolsets     |  | (Grafana,K6, |
    | (K8s, Grafana,  |  | (REST API,   |  |  DBs, etc.)  |
    |  Kafka, ES...)  |  |  Kibana...)  |  |              |
    +-----------------+  +--------------+  +--------------+
              |
    +---------v------+
    |   Ollama LLM   |
    |  qwen3:4b      |
    +----------------+
```

## Layout

```
server.py                                   # FastAPI app - API endpoints
core/
  config_loader.py                          # YAML config parser + validation
  holmes_engine.py                          # HolmesGPT SDK wrapper
config/
  holmes_config.yaml                        # Main configuration (LLM, toolsets, MCP)
  toolsets/
    rest_api_toolset.yaml                   # Custom REST API diagnostic tools
    kibana_toolset.yaml                     # Kibana/Elasticsearch log search tools
agents/                                     # Legacy placeholders (replaced by HolmesGPT)
```

## Prerequisites

1. **Python 3.10+**
2. **Ollama** - Install from [ollama.com](https://ollama.com), then:
   ```bash
   ollama serve
   ollama pull qwen3:4b
   ```

## Setup

```bash
cd fixora-diagnostic-orchestrator-agent
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your data source credentials
```

## Configuration

All configuration lives in `config/holmes_config.yaml`. Key sections:

### LLM Provider
```yaml
llm:
  model: "ollama_chat/qwen3:4b"          # Any LiteLLM-supported model
  api_base: "http://localhost:11434"       # Ollama server
  max_steps: 30                            # Agentic loop iterations
```

### Built-in Toolsets (toggle on/off)
```yaml
builtin_toolsets:
  kubernetes:
    enabled: true
  grafana:
    enabled: true
    env:
      GRAFANA_URL: "{{ env.GRAFANA_BASE_URL }}"
      GRAFANA_API_KEY: "{{ env.GRAFANA_API_KEY }}"
  kafka:
    enabled: true
  elasticsearch:
    enabled: true
```

### MCP Servers
```yaml
mcp_servers:
  grafana:
    description: "Grafana dashboards via MCP"
    config:
      url: "http://localhost:8000/mcp/messages"
      mode: streamable-http
      headers:
        Authorization: "Bearer {{ env.GRAFANA_MCP_TOKEN }}"
    llm_instructions: "Use for metric visualization and alert queries."
```

### Custom YAML Toolsets
```yaml
custom_toolsets:
  - "toolsets/rest_api_toolset.yaml"
  - "toolsets/kibana_toolset.yaml"
```

Environment variables in YAML use `{{ env.VAR_NAME }}` syntax.

## Run

```bash
python -m uvicorn server:app --host 0.0.0.0 --port 8092
```

## API Endpoints

| Method | Path          | Description                                      |
|--------|---------------|--------------------------------------------------|
| GET    | `/healthcheck`| Liveness check with engine status                |
| POST   | `/diagnose`   | Run full RCA investigation                       |
| POST   | `/ask`        | Ask a free-form diagnostic question              |
| GET    | `/toolsets`   | List loaded toolsets and their status             |
| GET    | `/config`     | View current (sanitized) configuration           |

### Example: Run Diagnosis

```bash
curl -X POST http://localhost:8092/diagnose \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Why is the payment service returning 500 errors?",
    "context": {
      "service": "payment-api",
      "namespace": "production",
      "alert": "HighErrorRate"
    }
  }'
```

### Example: Ask a Question

```bash
curl -X POST http://localhost:8092/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What pods are in CrashLoopBackOff in the production namespace?"}'
```

## Adding Data Sources

### Option 1: Enable a Built-in Toolset
HolmesGPT ships with toolsets for Kubernetes, Grafana, Kafka, Elasticsearch, Datadog, and more. Toggle them in `holmes_config.yaml` under `builtin_toolsets`.

### Option 2: Add a Custom YAML Toolset
Create a YAML file in `config/toolsets/` following HolmesGPT's format:
```yaml
toolsets:
  my-tools:
    description: "My custom diagnostic tools"
    prerequisites:
      - command: "curl --version"
    tools:
      - name: check_something
        description: "Check something important"
        command: |
          curl -s "${MY_URL}/api/status"
```

### Option 3: Connect an MCP Server
Add an MCP server entry to `holmes_config.yaml` under `mcp_servers`. Supports `streamable-http`, `stdio`, and `sse` transports.
