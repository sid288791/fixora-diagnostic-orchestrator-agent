"""
KibanaAgent - read-only diagnostic agent. Searches logs via the Elastic MCP
server (Elasticsearch under the hood). Supports the check names referenced in
DiagnosticLoop's AVAILABLE_AGENTS_DESC for "kibana": error_logs,
container_logs, db_timeout_logs, oom_events, exception_traces.
"""
from typing import Any, Dict

CHECK_LEVEL_FILTERS = {
    "error_logs": ["ERROR"],
    "container_logs": None,  # no level filter -- full recent log window
    "db_timeout_logs": ["ERROR", "WARN"],
    "oom_events": ["ERROR"],
    "exception_traces": ["ERROR"],
}

CHECK_KEYWORDS = {
    "db_timeout_logs": ["connection", "timeout", "pool"],
    "oom_events": ["outofmemory", "oom", "heap space"],
    "exception_traces": ["exception", "stack trace", "traceback"],
}

MAX_HITS = 20


class KibanaAgent:
    def __init__(self, mcp_client, index: str = "fixora-app-logs"):
        self.mcp_client = mcp_client
        self.index = index

    async def check(self, check_name: str, alert: Dict[str, Any]) -> Dict[str, Any]:
        service = alert.get("service") or alert.get("service_name") or alert.get("app_name")
        # `alert` is an untyped dict from the request body -- guard against a caller sending a
        # non-string (object/array/number) here, which would otherwise be spliced directly into
        # the Elasticsearch query DSL as a "match" value.
        if not isinstance(service, str) or not service.strip():
            service = None

        must = [{"match": {"service.name": service}}] if service else []
        level_filter = CHECK_LEVEL_FILTERS.get(check_name, ["ERROR", "WARN"])
        if level_filter:
            must.append({"terms": {"log.level": level_filter}})
        for keyword in CHECK_KEYWORDS.get(check_name, []):
            must.append({"match_phrase": {"message": keyword}})

        query_body = {
            "query": {"bool": {"must": must}} if must else {"match_all": {}},
            "sort": [{"@timestamp": "desc"}],
            "size": MAX_HITS,
        }

        hits = await self.mcp_client.search(self.index, query_body)

        if not hits:
            return {"finding": f"No matching log entries found for check '{check_name}'.", "anomaly": False}

        samples = [h.get("_source", {}).get("message", "") for h in hits[:5]]
        finding = (
            f"{len(hits)} matching log entries found for check '{check_name}'. "
            f"Sample messages: {' | '.join(samples)}"
        )
        return {"finding": finding, "anomaly": True}
