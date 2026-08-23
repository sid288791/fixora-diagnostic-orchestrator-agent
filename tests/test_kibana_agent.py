import pytest

from agents.kibana_agent import KibanaAgent


class FakeElasticMcpClient:
    def __init__(self, hits):
        self._hits = hits
        self.last_call = None

    async def search(self, index, query_body):
        self.last_call = (index, query_body)
        return self._hits


@pytest.mark.asyncio
async def test_check_error_logs_flags_anomaly_when_errors_found():
    hits = [
        {"_source": {"@timestamp": "2026-08-23T10:00:00Z", "message": "Connection pool exhausted", "log.level": "ERROR"}},
        {"_source": {"@timestamp": "2026-08-23T10:00:05Z", "message": "Connection pool exhausted", "log.level": "ERROR"}},
    ]
    client = FakeElasticMcpClient(hits)
    agent = KibanaAgent(mcp_client=client, index="fixora-app-logs")

    result = await agent.check("error_logs", {"service": "payment-service"})

    assert result["anomaly"] is True
    assert "Connection pool exhausted" in result["finding"]
    assert "2 " in result["finding"] or "2" in result["finding"]


@pytest.mark.asyncio
async def test_check_error_logs_no_anomaly_when_no_hits():
    client = FakeElasticMcpClient([])
    agent = KibanaAgent(mcp_client=client, index="fixora-app-logs")

    result = await agent.check("error_logs", {"service": "payment-service"})

    assert result["anomaly"] is False
    assert "no" in result["finding"].lower()


@pytest.mark.asyncio
async def test_check_unknown_check_name_still_searches_with_no_level_filter():
    client = FakeElasticMcpClient([])
    agent = KibanaAgent(mcp_client=client, index="fixora-app-logs")

    await agent.check("some_future_check", {"service": "payment-service"})

    index, query_body = client.last_call
    assert index == "fixora-app-logs"
    assert query_body["query"]["bool"]["must"][0]["match"]["service.name"] == "payment-service"
