"""
Thin MCP client wrapping the Elastic MCP server's "search" tool
(https://github.com/elastic/mcp-server-elasticsearch), used by KibanaAgent to
query Elasticsearch through MCP instead of raw REST -- matching how a real
Kibana MCP integration is meant to look.

The published npm package (@elastic/mcp-server-elasticsearch, 0.3.1 as of
this writing) only implements the MCP *stdio* transport -- there is no HTTP
transport flag despite what some docs suggest -- so this client spawns the
server as a subprocess per call via the `mcp` SDK's stdio_client, rather than
connecting to an always-on HTTP service. OTEL_SDK_DISABLED=true is required:
the package's built-in Elastic APM auto-instrumentation otherwise writes
non-JSON-RPC log lines to stdout on every failed metrics-export attempt
(there is no OTLP collector in this dev setup), which corrupts the stdio
transport's line-delimited JSON-RPC framing.
"""
import json
import logging
from typing import Any, Dict, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class ElasticMcpClient:
    def __init__(self, es_url: str, mcp_package: str = "@elastic/mcp-server-elasticsearch@0.3.1"):
        self.es_url = es_url
        self.mcp_package = mcp_package

    def _server_params(self) -> StdioServerParameters:
        return StdioServerParameters(
            command="npx",
            args=["-y", self.mcp_package],
            env={"ES_URL": self.es_url, "OTEL_SDK_DISABLED": "true"},
        )

    async def search(self, index: str, query_body: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Calls the Elastic MCP server's 'search' tool and returns the raw ES hits list."""
        async with stdio_client(self._server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "search",
                    arguments={"index": index, "queryBody": query_body},
                )
                if result.isError:
                    raise RuntimeError(f"Elastic MCP search failed: {result.content}")

                for block in result.content:
                    if getattr(block, "type", None) != "text":
                        continue
                    text = block.text
                    if text.startswith("Error:"):
                        # The server reports query/connection failures as plain-text content
                        # rather than the isError flag (observed directly against a running
                        # server) -- treat as "no evidence available", not a crash.
                        raise RuntimeError(f"Elastic MCP search failed: {text}")
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        logger.warning("Elastic MCP search returned non-JSON content: %r", text[:200])
                        return []
                    return payload.get("hits", {}).get("hits", [])
                return []
