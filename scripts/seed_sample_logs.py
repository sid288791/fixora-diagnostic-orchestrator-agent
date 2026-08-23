"""
seed_sample_logs.py — pushes realistic, filebeat-shaped log documents into
Elasticsearch for one Fixora app, including a deliberate incident scenario
(DB connection pool exhaustion) so KibanaAgent has real evidence to find
during a Deep Analysis run.

Uses plain HTTP (httpx) against Elasticsearch's REST API rather than the
`elasticsearch` Python client library, to avoid client/server major-version
compatibility errors (the client pins an Accept/Content-Type media-type
version header that must match the server's major version exactly).

Usage:
    python seed_sample_logs.py --service payment-service --index fixora-app-logs
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

INCIDENT_MESSAGES = [
    ("WARN", "DB connection pool at 90% capacity (45/50 connections in use)"),
    ("WARN", "DB connection pool at 96% capacity (48/50 connections in use)"),
    ("ERROR", "Connection pool exhausted: timed out after 5000ms waiting for a connection"),
    ("ERROR", "java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 5000ms"),
    ("ERROR", "Connection pool exhausted: timed out after 5000ms waiting for a connection"),
    ("ERROR", "Failed to process request id=req-{n}: could not obtain DB connection"),
]


def build_docs(service: str, now: datetime):
    docs = []
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

    # Last 20 minutes: the incident. Connection pool exhaustion, growing in
    # frequency, ending right at "now" (i.e. still ongoing when Deep Analysis
    # is triggered).
    t = now - timedelta(minutes=20)
    while t < now:
        level, template = random.choice(INCIDENT_MESSAGES)
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
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    docs = build_docs(args.service, now)

    with httpx.Client(timeout=30.0) as client:
        for doc in docs:
            resp = client.post(f"{args.es_url}/{args.index}/_doc", json=doc)
            resp.raise_for_status()
        client.post(f"{args.es_url}/{args.index}/_refresh").raise_for_status()

    print(f"Seeded {len(docs)} log documents into '{args.index}' for service '{args.service}'.")
    print(f"Incident window: {(now - timedelta(minutes=20)).isoformat()} to {now.isoformat()}")
    print("Ground truth: DB connection pool exhaustion (HikariPool), preceded by pool-capacity WARN logs.")


if __name__ == "__main__":
    main()
