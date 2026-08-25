"""
seed_sample_logs.py — pushes realistic, filebeat-shaped log documents into
Elasticsearch for one Fixora app, including a deliberate incident scenario
so KibanaAgent has real evidence to find during a Deep Analysis run.

Uses plain HTTP (httpx) against Elasticsearch's REST API rather than the
`elasticsearch` Python client library, to avoid client/server major-version
compatibility errors (the client pins an Accept/Content-Type media-type
version header that must match the server's major version exactly).

Usage:
    python seed_sample_logs.py --service payment-service --scenario db_pool_exhaustion
    python seed_sample_logs.py --service "Sample App" --scenario oom_leak --at "2026-08-23 19:27:00"
"""
import argparse
import random
from datetime import datetime, timedelta, timezone

import httpx

NORMAL_MESSAGES = [
    ("INFO", "Handled GET /api/v1/health in 4ms"),
    ("INFO", "Processed request id=req-{n} in 32ms"),
    ("INFO", "Cache hit for key=session:{n}"),
    ("WARN", "Slow query detected: 210ms for SELECT * FROM orders WHERE id={n}"),
]

SCENARIOS = {
    "db_pool_exhaustion": {
        "ground_truth": "DB connection pool exhaustion (HikariPool), preceded by pool-capacity WARN logs.",
        "incident_messages": [
            ("WARN", "DB connection pool at 90% capacity (45/50 connections in use)"),
            ("WARN", "DB connection pool at 96% capacity (48/50 connections in use)"),
            ("ERROR", "Connection pool exhausted: timed out after 5000ms waiting for a connection"),
            ("ERROR", "java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 5000ms"),
            ("ERROR", "Connection pool exhausted: timed out after 5000ms waiting for a connection"),
            ("ERROR", "Failed to process request id=req-{n}: could not obtain DB connection"),
        ],
    },
    "oom_leak": {
        "ground_truth": (
            "OOMKilled due to unbounded growth of an in-memory session cache: sessions were "
            "cached with no TTL/eviction policy, so the cache never released entries, heap usage "
            "climbed monotonically until the JVM ran out of heap and the container was OOMKilled."
        ),
        "incident_messages": [
            ("WARN", "Session cache size growing: 480,000 entries, no eviction policy configured (TTL unset)"),
            ("WARN", "Heap usage at 88% (3.6GB / 4GB), GC reclaiming <2% per cycle"),
            ("WARN", "Session cache size growing: 610,000 entries, no eviction policy configured (TTL unset)"),
            ("ERROR", "java.lang.OutOfMemoryError: Java heap space"),
            ("ERROR", "GC overhead limit exceeded -- 98% of recent CPU time spent in garbage collection, <2% heap freed"),
            ("ERROR", "Container OOMKilled: memory usage exceeded limit (4096Mi), session-cache retained 640,000+ entries with no expiry"),
        ],
    },
}


def build_docs(service: str, now: datetime, scenario: dict):
    docs = []
    incident_messages = scenario["incident_messages"]

    # 2 hours of normal traffic, one log every ~90s
    t = now - timedelta(hours=2)
    n = 0
    while t < now - timedelta(minutes=20):
        level, template = random.choice(NORMAL_MESSAGES)
        docs.append({
            "@timestamp": t.isoformat(),
            "message": template.format(n=n),
            "log.level": level,
            "service.name": service,
            "container.id": f"{service}-7d8f9-{n % 5:04d}",
        })
        t += timedelta(seconds=random.randint(60, 120))
        n += 1

    # Last 20 minutes: the incident, growing in frequency, ending right at "now" (i.e. still
    # ongoing / just-happened when Deep Analysis is triggered).
    t = now - timedelta(minutes=20)
    while t < now:
        level, template = random.choice(incident_messages)
        docs.append({
            "@timestamp": t.isoformat(),
            "message": template.format(n=n),
            "log.level": level,
            "service.name": service,
            "container.id": f"{service}-7d8f9-{n % 5:04d}",
        })
        t += timedelta(seconds=random.randint(5, 20))
        n += 1

    return docs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True, help="service.name to seed logs for (match an existing AlertConfiguration app name)")
    parser.add_argument("--index", default="fixora-app-logs")
    parser.add_argument("--es-url", default="http://localhost:9201")
    parser.add_argument("--scenario", default="db_pool_exhaustion", choices=sorted(SCENARIOS.keys()))
    parser.add_argument(
        "--at",
        default=None,
        help="Local timestamp the incident peaks at, e.g. '2026-08-23 19:27:00' (server's local "
             "timezone). Defaults to now.",
    )
    args = parser.parse_args()

    if args.at:
        # A naive datetime.astimezone() call is presumed to be in the system's local timezone
        # and converted from there -- exactly what we want for a human-typed "--at" time.
        now = datetime.strptime(args.at, "%Y-%m-%d %H:%M:%S").astimezone(timezone.utc)
    else:
        now = datetime.now(timezone.utc)

    scenario = SCENARIOS[args.scenario]
    docs = build_docs(args.service, now, scenario)

    with httpx.Client(timeout=30.0) as client:
        for doc in docs:
            resp = client.post(f"{args.es_url}/{args.index}/_doc", json=doc)
            resp.raise_for_status()
        client.post(f"{args.es_url}/{args.index}/_refresh").raise_for_status()

    print(f"Seeded {len(docs)} log documents into '{args.index}' for service '{args.service}' (scenario: {args.scenario}).")
    print(f"Incident window: {(now - timedelta(minutes=20)).isoformat()} to {now.isoformat()}")
    print(f"Ground truth: {scenario['ground_truth']}")


if __name__ == "__main__":
    main()
