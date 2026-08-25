from mcp_clients.elastic_mcp_client import _parse_hit_block


def test_parse_hit_block_extracts_quoted_string_fields():
    text = (
        '@timestamp: "2026-08-23T12:44:43.532694+00:00"\n'
        'message: "Connection pool exhausted: timed out after 5000ms waiting for a connection"\n'
        'log.level: "ERROR"\n'
        'service.name: "payment-service"\n'
        'container.id: "payment-service-7d8f9-0004"'
    )

    result = _parse_hit_block(text)

    assert result == {
        "_source": {
            "@timestamp": "2026-08-23T12:44:43.532694+00:00",
            "message": "Connection pool exhausted: timed out after 5000ms waiting for a connection",
            "log.level": "ERROR",
            "service.name": "payment-service",
            "container.id": "payment-service-7d8f9-0004",
        }
    }


def test_parse_hit_block_ignores_lines_without_a_colon():
    result = _parse_hit_block('no colon here\nlog.level: "WARN"')

    assert result == {"_source": {"log.level": "WARN"}}
