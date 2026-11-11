"""Realistic, internally consistent demo stories for every seeded incident.

Each incident gets evidence that matches its service, status and impact, plus
hypotheses, remediation proposals, deployments, runbooks and log lines where its
lifecycle stage calls for them. Everything here is synthetic (``synthetic: True``)
except the Payment API sandbox incident, whose live measurements are added at
demo time by running the real workload.
"""

from typing import Callable

Stamp = Callable[[int], str]

DETAILS = {
    "INC-1041": ("Payment authorization p95 468 ms (SLO 300 ms) in eu-west-1 since fraud ruleset v41", "p95 authorization latency below 300 ms", "p95 468 ms; p50 142 ms; error rate 0.4%"),
    "INC-1040": ("inventory-reconciler consumers leave the group every ~45 s (session timeout exceeded)", "Inventory updates applied within 30 seconds", "Updates delayed up to 6 minutes; lag peak 2,310 events"),
    "INC-1039": ("HTTP 429 Too Many Requests for premium-tier clients at 100 req/min (expected 1,000)", "Premium clients limited at 1,000 requests per minute", "7.8% of premium requests rejected with 429"),
    "INC-1038": ("Redis evicted_keys/s 420 (baseline 5); sessions missing on lookup", "Session cache evictions under 10/s; no forced re-login", "3.1% of active sessions forced to re-authenticate"),
    "INC-1037": ("order-confirmed events delivered in 4.6 s at p95 in staging", "Order confirmation events delivered within 2 seconds", "p95 delivery 4,620 ms in 3 of 3 test runs"),
    "INC-1036": ("Flyway V42__split_full_name: null value in column last_name violates not-null constraint", "Migration completes for all staging profiles", "18,204 of 1.2M rows fail; migration rolled back"),
    "INC-1035": ("PACT verification failed: missing optional field reason_code in recommendation response", "Responses match api-gateway contract v3", "Contract test fails on every build since the serializer upgrade"),
    "INC-1034": ("2.3% of static asset requests served the previous build hash app.4f1c.js", "All clients receive assets from the current build", "Stale share 0.2% and falling after manual purge"),
    "INC-1033": ("S3 503 SlowDown responses 1,840/min during the export window", "Export completes in 10-12 minutes", "Recovered: export 11 minutes, 0 SlowDown for 2 hours"),
    "INC-1032": ("dial tcp: lookup api.internal on 10.0.0.2:53: i/o timeout", "Integration tests resolve internal hosts reliably", "Resolved by node-local DNS cache on CI runners"),
    "INC-1031": ("Client error events arrive with release=null after the pipeline v7 migration", "Every client error is attributed to a release", "Release tag restored; source maps uploaded"),
}

# (id, incident, title, type, source, service, environment, classification, excerpt, reason, minutes ago)
EVIDENCE = [
    ("EVD-311", "INC-1041", "Authorization latency above SLO", "Metric", "metrics / payment_authorization_latency", "payment-svc", "Production", "Observed",
     "payment_authorization_latency_p95_ms=468 (SLO 300); p50=142; error_rate=0.4%; window=30m; region=eu-west-1 only; other regions p95 190-210 ms", "Quantifies the latency breach and its regional scope.", 70),
    ("EVD-312", "INC-1041", "Slow authorization trace", "Trace", "traces / trace-5c19e0", "payment-svc", "Production", "Observed",
     "POST /payments/authorize 512ms -> fraud-check.score 331ms (cache_hit=false) -> payment-provider.authorize 151ms -> ledger.write 18ms", "Shows where the time is spent inside one slow request.", 64),
    ("EVD-313", "INC-1041", "Fraud scoring budget exceeded", "Log", "payment-svc / fraud-check.log", "payment-svc", "Production", "Observed",
     "WARN payment-svc fraud-check: scoring exceeded 300ms budget (took 331ms) ruleset=v41 step=device_fingerprint_lookup mode=synchronous", "Points at a specific step in the new ruleset.", 61),
    ("EVD-314", "INC-1041", "Fraud ruleset v41 enabled", "Change", "fraud-rules / ruleset v41", "payment-svc", "Production", "Observed",
     "ruleset v41 enabled 82 minutes ago in eu-west-1 first (staged rollout); adds a synchronous device-fingerprint lookup to every authorization", "Timing and region match the start of the latency breach.", 82),
    ("EVD-315", "INC-1041", "Fraud cache hit ratio dropped", "Metric", "metrics / fraud_cache_hit_ratio", "payment-svc", "Production", "Observed",
     "fraud_cache_hit_ratio 0.91 -> 0.37 after ruleset v41 (new cache key includes device fingerprint)", "Explains why more requests pay the full lookup cost.", 58),

    ("EVD-321", "INC-1040", "Consumer lag on inventory-updates", "Metric", "metrics / kafka_consumer_lag", "inventory-svc", "Production", "Observed",
     "kafka_consumer_lag{group=inventory-reconciler,topic=inventory-updates} current=1462 peak=2310; active consumers 3 of 6", "Measures the backlog and lost consumer capacity.", 105),
    ("EVD-322", "INC-1040", "Consumer group rebalance loop", "Log", "inventory-svc / reconciler.log", "inventory-svc", "Production", "Observed",
     "WARN inventory-reconciler-4 left group inventory-reconciler: session timeout 10000ms exceeded; rebalance #37 in 30 minutes", "Consumers repeatedly drop out and trigger rebalances.", 98),
    ("EVD-323", "INC-1040", "Long GC pauses on reconciler pods", "Metric", "metrics / jvm_gc_pause_seconds", "inventory-svc", "Production", "Observed",
     "jvm_gc_pause_seconds max=11.4 p99=8.2 on inventory-reconciler-4..6; heap usage 94% during batch processing", "Pauses longer than the 10 s session timeout explain the rebalances.", 95),
    ("EVD-324", "INC-1040", "Reconciler batch size increased", "Change", "repository / inventory-svc commit 9ad21f0", "inventory-svc", "Production", "Observed",
     "commit 9ad21f0 (deployed 3 h ago): reconciler.batch.size 500 -> 5000 to reduce commit overhead", "Larger batches raise heap pressure; timing matches.", 180),

    ("EVD-331", "INC-1039", "Unexpected 429 for premium clients", "Log", "api-gateway / access.log", "api-gateway", "Production", "Observed",
     "429 Too Many Requests tenant=premium client_id=web-checkout policy=default limit=100/min (expected premium 1000/min)", "Premium traffic is matched to the default policy.", 130),
    ("EVD-332", "INC-1039", "Rate-limit policy refactor", "Change", "repository / gateway-policies PR #482", "api-gateway", "Production", "Observed",
     "PR #482: tier lookup key changed from plan_id to plan_code; premium plan_code not present in policy map -> falls back to default 100/min", "Code change that explains the wrong tier lookup.", 140),
    ("EVD-333", "INC-1039", "429 rate by tier", "Metric", "metrics / gateway_rejections", "api-gateway", "Production", "Observed",
     "429 share: premium 7.8%, standard 0.2%, internal 0%; started 2 h 20 m ago, aligned with policy rollout", "Confirms only the premium tier is affected.", 128),

    ("EVD-341", "INC-1038", "Redis evictions above baseline", "Metric", "metrics / redis_evicted_keys", "redis-cache", "Production", "Observed",
     "evicted_keys/s=420 (baseline 5); used_memory=7.6GB of maxmemory 8GB; maxmemory-policy=allkeys-lru", "Memory pressure is evicting keys, including sessions.", 175),
    ("EVD-342", "INC-1038", "Forced re-authentication", "Log", "user-svc / session.log", "user-svc", "Production", "Observed",
     "INFO user-svc session not found for sid=7f3c… redirecting to /login (3.1% of session lookups in the last hour)", "Customer impact of evicted sessions.", 170),
    ("EVD-343", "INC-1038", "Recommendation keys growing without TTL", "Metric", "metrics / redis_keyspace", "redis-cache", "Production", "Observed",
     "keyspace rec:* grew from 1.1M to 6.4M keys in 24 h; 96% have no TTL; average value 1.1 KB", "Likely source of the memory growth.", 160),

    ("EVD-351", "INC-1037", "Event delivery latency in staging", "Metric", "metrics / order_event_delivery", "kafka-orders", "Staging", "Observed",
     "order-confirmed p95 delivery 4.6 s (target 2 s); producer batch fill 3%; linger.ms=500", "Producer waits to fill batches that never fill at staging volume.", 215),
    ("EVD-352", "INC-1037", "Producer batching tuned for throughput", "Change", "repository / commit 51be3c2", "kafka-orders", "Staging", "Observed",
     "commit 51be3c2: linger.ms 5 -> 500, batch.size 16KB -> 256KB (staging only, performance experiment)", "Configuration change that adds up to 500 ms per event.", 240),
    ("EVD-353", "INC-1037", "Event latency test failing", "Test", "test-runner / TEST-851", "kafka-orders", "Staging", "Observed",
     "order_confirmation_latency: expected <= 2000 ms, observed 4620 ms (3 of 3 runs)", "Automated check confirming the regression.", 200),

    ("EVD-361", "INC-1036", "Migration validation failure", "Test", "test-runner / TEST-860", "user-svc", "Staging", "Observed",
     "migration V42__split_full_name: 18,204 of 1,204,880 rows fail NOT NULL on last_name; all are single-token names", "Pinpoints the failing rows.", 245),
    ("EVD-362", "INC-1036", "Flyway migration aborted", "Log", "user-svc / flyway.log", "user-svc", "Staging", "Observed",
     "ERROR Flyway V42 failed: null value in column \"last_name\" violates not-null constraint; transaction rolled back", "Database refused the migration; no partial data written.", 248),
    ("EVD-363", "INC-1036", "Data profile of affected names", "Document", "data-quality / name-profile-2026-11", "user-svc", "Staging", "Observed",
     "1.5% of staging profiles have a single-token name (mononyms, legal single names); production share estimated 1.3%", "Shows this is valid customer data, not bad input.", 230),

    ("EVD-371", "INC-1035", "Contract test failure", "Test", "test-runner / PACT verification", "recommendation-svc", "Development", "Observed",
     "PACT: recommendation-svc response missing optional field 'reason_code' expected by api-gateway contract v3 (14 interactions failing)", "Consumer contract broken.", 300),
    ("EVD-372", "INC-1035", "Serializer upgrade", "Change", "repository / commit e0d7c91", "recommendation-svc", "Development", "Observed",
     "commit e0d7c91: jackson 2.15 -> 2.17 with spring.jackson.default-property-inclusion=NON_NULL; null fields now omitted", "Explains why the optional field disappeared.", 320),
    ("EVD-373", "INC-1035", "Gateway deserialization warning", "Log", "api-gateway / client.log", "api-gateway", "Development", "Observed",
     "WARN RecommendationClient: missing property reason_code; defaulting to UNKNOWN (rate 100% of responses)", "Consumer-side symptom.", 295),

    ("EVD-381", "INC-1034", "Requests for the previous asset hash", "Metric", "cdn / edge-logs", "cloud-cdn", "Production", "Observed",
     "requests for app.4f1c.js (previous build) = 2.3% of asset requests; Cache-Control max-age=86400", "Clients still served the old bundle.", 360),
    ("EVD-382", "INC-1034", "Deployment without cache purge", "Change", "pipeline / DEP-2178", "frontend-web", "Production", "Observed",
     "DEP-2178 frontend-web v4.12.2 completed; purge step skipped because PURGE_CDN=false was left from a test run", "Root cause of the stale cache.", 375),
    ("EVD-383", "INC-1034", "Stale share falling after purge", "Metric", "cdn / edge-logs", "cloud-cdn", "Production", "Validated",
     "stale asset share 2.3% -> 0.2% within 40 minutes of the manual purge; no new reports", "Recovery is being monitored.", 300),

    ("EVD-391", "INC-1033", "S3 SlowDown responses", "Metric", "metrics / s3_errors", "s3-assets", "Production", "Observed",
     "s3 503 SlowDown 1,840/min during export window; average retries per request 6.2 (fixed 100 ms retry)", "Retries amplify the throttling.", 455),
    ("EVD-392", "INC-1033", "Backoff with jitter introduced", "Change", "repository / commit 7c0aa13", "s3-assets", "Production", "Observed",
     "commit 7c0aa13: retry policy fixed 100 ms -> exponential backoff (base 200 ms, full jitter, max 5 attempts)", "The fix that was deployed.", 430),
    ("EVD-393", "INC-1033", "Recovery verified", "Metric", "metrics / export_job", "s3-assets", "Production", "Validated",
     "export job duration 11 min (baseline 10-12 min); SlowDown 0/min for 2 h after the fix", "Recorded recovery verification.", 300),

    ("EVD-401", "INC-1032", "Resolver timeouts in CI", "Log", "ci / integration-tests", "cloud-dns", "Development", "Observed",
     "dial tcp: lookup api.internal on 10.0.0.2:53: i/o timeout (3 of 412 runs this week)", "Intermittent failures were DNS, not product code.", 615),
    ("EVD-402", "INC-1032", "Node-local DNS cache on CI runners", "Change", "ci / runner image 2026.10", "cloud-dns", "Development", "Validated",
     "ci-runner image 2026.10: dnsmasq node-local cache enabled; 0 resolver timeouts in 1,100 runs since", "Fix and verification.", 600),

    ("EVD-411", "INC-1031", "Errors missing release tag", "Log", "error-tracking / client events", "frontend-web", "Production", "Observed",
     "client error events with release=null: 100% since build pipeline v7 migration", "Release attribution lost.", 790),
    ("EVD-412", "INC-1031", "Release tag injected at build", "Change", "pipeline / build v7.1", "frontend-web", "Production", "Validated",
     "SENTRY_RELEASE set from git describe; source maps uploaded per build; 100% of new events tagged", "Fix and verification.", 700),

    ("EVD-421", "INC-1043", "Payment API v3.8.1 release configuration", "Change", "payment-api / release v3.8.1", "payment-api", "Sandbox", "Observed",
     "v3.8.1 adds Feature X: GET /payments/summary (holds a DB connection ~0.3 s per request). Configuration: PAYMENT_DB_POOL_SIZE=5 (previous release: 20), max_overflow=0, pool_timeout=2 s.", "The release changed both the workload and the pool size.", 25),
    ("EVD-422", "INC-1043", "Sandbox service-level target", "Document", "payment-api / sandbox SLO", "payment-api", "Sandbox", "Observed",
     "Target: 50 concurrent GET /payments/summary requests with 0 HTTP 5xx and p95 under 2 s. Approved recovery options: pool size 20 on v3.8.1, or roll back to the previous release (loses Feature X).", "Acceptance criteria for recovery.", 24),
]

# (id, incident, title, status, confidence, supports, contradicts, missing, next step, agent, minutes ago)
HYPOTHESES = [
    ("HYP-41-A", "INC-1041", "Synchronous device-fingerprint lookup in fraud ruleset v41", "Supported by Evidence", .74, ["EVD-312", "EVD-313", "EVD-314", "EVD-315"], [], ["Latency of the fingerprint service itself"], "Make the lookup asynchronous or cache it per device; compare eu-west-1 p95 with other regions.", "Root-cause analysis", 40),
    ("HYP-41-B", "INC-1041", "Payment provider latency", "Under Investigation", .12, ["EVD-311"], ["EVD-312"], ["Provider-side latency report"], "Confirm provider span stays near 150 ms across slow traces.", "Observability correlation", 45),
    ("HYP-40-A", "INC-1040", "Larger batches cause GC pauses beyond the session timeout", "Supported by Evidence", .7, ["EVD-322", "EVD-323", "EVD-324"], [], ["Heap profile at batch size 5000"], "Revert batch size to 500 on one consumer and compare GC and lag.", "Root-cause analysis", 60),
    ("HYP-40-B", "INC-1040", "Kafka broker under-replication", "Suspected", .15, ["EVD-321"], ["EVD-322"], ["Broker ISR metrics"], "Check under-replicated partitions for inventory-updates.", "Observability correlation", 70),
    ("HYP-39-A", "INC-1039", "Policy lookup key change drops premium tier to default", "Supported by Evidence", .9, ["EVD-331", "EVD-332", "EVD-333"], [], [], "Map plan_code for premium in the policy table and re-run the contract suite.", "Root-cause analysis", 100),
    ("HYP-38-A", "INC-1038", "Recommendation keys without TTL fill Redis and evict sessions", "Suspected", .64, ["EVD-341", "EVD-343"], [], ["Memory by key prefix over 48 h"], "Set a TTL on rec:* keys and isolate sessions in a separate database or instance.", "Root-cause analysis", 150),
    ("HYP-37-A", "INC-1037", "Producer linger.ms=500 delays low-volume events", "Supported by Evidence", .82, ["EVD-351", "EVD-352", "EVD-353"], [], [], "Restore linger.ms=5 for the order-confirmed producer and re-run TEST-851.", "Root-cause analysis", 190),
    ("HYP-36-A", "INC-1036", "Migration assumes every full name has two tokens", "Supported by Evidence", .88, ["EVD-361", "EVD-362", "EVD-363"], [], [], "Allow an empty last_name and keep full_name as the source of truth.", "Root-cause analysis", 235),
    ("HYP-35-A", "INC-1035", "NON_NULL serialization omits the optional reason_code", "Supported by Evidence", .78, ["EVD-371", "EVD-372", "EVD-373"], [], ["Whether other optional fields are affected"], "Serialize reason_code explicitly as null or relax the consumer contract.", "Root-cause analysis", 280),
]

KNOWLEDGE = [
    {"id": "KB-105", "title": "Redis memory pressure and session evictions", "type": "Runbook", "owner": "Platform Engineering", "version": "1.6", "reviewedAt": 5760, "approved": True, "services": ["redis-cache", "user-svc"], "incidents": ["INC-1038"],
     "body": "Check used_memory against maxmemory and evicted_keys per second. Find the largest key prefixes. Set TTLs on cache data and keep sessions in a separate logical database or instance with noeviction. Never flush production Redis during an incident."},
    {"id": "KB-106", "title": "Kafka consumer rebalance storms", "type": "Troubleshooting guide", "owner": "Commerce SRE", "version": "2.0", "reviewedAt": 8640, "approved": True, "services": ["kafka-orders", "inventory-svc"], "incidents": ["INC-1040"],
     "body": "Correlate rebalance events with GC pauses and processing time per poll. Keep max.poll.records and batch sizes below what fits in session.timeout.ms. Prefer reverting recent batch-size changes before scaling consumers."},
    {"id": "KB-107", "title": "CDN purge after frontend deployments", "type": "Release checklist", "owner": "Web Platform", "version": "1.2", "reviewedAt": 4320, "approved": True, "services": ["cloud-cdn", "frontend-web"], "incidents": ["INC-1034"],
     "body": "Every frontend deployment must purge changed asset paths or use content-hashed file names with a short HTML cache. Verify PURGE_CDN is true in the pipeline before approving a release."},
    {"id": "KB-108", "title": "Payment API connection pool sizing", "type": "Runbook", "owner": "Payments Engineering", "version": "1.0", "reviewedAt": 1440, "approved": True, "services": ["payment-api"], "incidents": ["INC-1043"],
     "body": "Required connections ≈ concurrent requests × hold time ÷ acquisition timeout. At 50 concurrent summary requests holding 0.3 s with a 2 s timeout, pool size 5 is not enough; 20 keeps waits well under the timeout. Approved sandbox recovery: pool size 20 on v3.8.1, or roll back to the previous release (pool 20, no summary endpoint). Always re-run the calibrated workload to verify."},
    {"id": "KB-109", "title": "Safe retry policies for cloud storage", "type": "Runbook", "owner": "Data Platform", "version": "1.3", "reviewedAt": 10080, "approved": True, "services": ["s3-assets"], "incidents": ["INC-1033"],
     "body": "Use exponential backoff with full jitter and a bounded number of attempts. Fixed short retries amplify throttling (503 SlowDown). Spread batch jobs across prefixes and time windows."},
]

LOG_TEMPLATES = [
    ("WARN", "payment-svc", "fraud-check scoring took 331ms (budget 300ms) ruleset=v41 cache_hit=false", "EVD-313"),
    ("INFO", "payment-svc", "Authorization approved in 512ms provider=acme-pay region=eu-west-1", "EVD-312"),
    ("WARN", "inventory-svc", "inventory-reconciler-4 left group: session timeout 10000ms exceeded", "EVD-322"),
    ("INFO", "inventory-svc", "Rebalance completed: 3 consumers assigned 12 partitions", "EVD-322"),
    ("WARN", "api-gateway", "429 Too Many Requests tenant=premium policy=default limit=100/min", "EVD-331"),
    ("WARN", "redis-cache", "Evicting keys under maxmemory pressure: 420 keys/s policy=allkeys-lru", "EVD-341"),
    ("INFO", "user-svc", "Session not found; redirecting to /login", "EVD-342"),
    ("INFO", "kafka-orders", "order-confirmed delivered in 4612ms (linger.ms=500)", "EVD-351"),
    ("ERROR", "user-svc", "Flyway V42 failed: null value in column last_name violates not-null constraint", "EVD-362"),
    ("WARN", "api-gateway", "RecommendationClient missing property reason_code; defaulting to UNKNOWN", "EVD-373"),
    ("INFO", "cloud-cdn", "Served app.4f1c.js from cache (age 41020s)", "EVD-381"),
    ("INFO", "frontend-web", "Client error captured release=4.12.2 sourcemap=resolved", "EVD-412"),
]


def _change(identifier: str, incident: str, title: str, status: str, risk: str, owner: str, environment: str, files: list[str], diff: str, rollback: str, plan: list[str], justification: str, extra: dict | None = None) -> dict:
    return {"id": identifier, "incidentId": incident, "title": title, "status": status, "risk": risk, "owner": owner, "environment": environment,
            "branch": f"fix/{incident}", "commit": f"demo-{identifier.lower()}", "files": files, "diff": diff, "rollback": rollback, "plan": plan,
            "justification": justification, "approvalId": None, "gates": [], **(extra or {})}


def add_story_data(state: dict, stamp: Stamp) -> None:
    incidents = {incident["id"]: incident for incident in state["incidents"]}
    for identifier, (error, expected, actual) in DETAILS.items():
        incident = incidents.get(identifier)
        if incident:
            incident.update(error=error, expected=expected, actual=actual)

    # The live, measurable Payment API sandbox incident (see backend/payment_local.py).
    sandbox_incident = {
        "id": "INC-1043", "title": "Payment summary endpoint failing after v3.8.1 release",
        "description": "Under concurrent load, GET /payments/summary returns HTTP 500 for a share of requests in the isolated Payment API sandbox. Run the calibrated workload to measure it live.",
        "severity": "High", "status": "New", "service": "payment-api", "environment": "Sandbox", "detectedAt": stamp(18),
        "owner": "Alex Morgan", "commander": "Alex Morgan",
        "impact": "Feature X (payment summary) fails for a share of requests under load; the previous release did not have this endpoint.",
        "source": "Sandbox workload", "correlationId": "",
        "error": "sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 0 reached, connection timed out, timeout 2.00",
        "expected": "50 concurrent summary requests with 0 HTTP 5xx and p95 under 2 s",
        "actual": "Measured live: run the workload from the AI War Room",
        "steps": "Start the Payment API sandbox, run the 50-request workload, inspect errors and the active configuration.",
        "slaMinutes": 240, "workflowStatus": "Idle", "workflowGeneration": 0, "outcome": "", "recovery": None, "synthetic": False,
    }
    state["incidents"].append(sandbox_incident)
    state["services"].append({
        "id": "payment-api", "name": "payment-api (sandbox)", "type": "Service", "health": "Degraded", "environment": "Sandbox",
        "latency": 0, "errorRate": 0, "rps": 0, "observedAt": stamp(0), "evidence": ["EVD-421"], "changes": ["DEP-2182"],
        "incidents": ["INC-1043"], "position": {"x": 700, "y": 145},
    })

    for identifier, incident, title, kind, source, service, environment, classification, excerpt, reason, age in EVIDENCE:
        state["evidence"].append({"id": identifier, "incidentId": incident, "title": title, "type": kind, "source": source, "timestamp": stamp(age),
                                  "service": service, "environment": environment, "classification": classification, "excerpt": excerpt,
                                  "reason": reason, "traceId": "trace-5c19e0" if identifier == "EVD-312" else "", "synthetic": incident != "INC-1043"})

    for identifier, incident, title, status, confidence, supports, contradicts, missing, next_step, agent, age in HYPOTHESES:
        state["hypotheses"].append({"id": identifier, "incidentId": incident, "title": title, "status": status, "confidence": confidence,
                                    "supports": supports, "contradicts": contradicts, "missing": missing, "nextStep": next_step, "agent": agent, "timestamp": stamp(age)})

    state["changes"] += [
        _change("CHG-2086", "INC-1040", "Revert reconciler batch size to 500", "Draft", "Low", "Maya Patel", "Production", ["inventory-svc/src/main/resources/application.yml"],
                "--- a/application.yml\n+++ b/application.yml\n@@ reconciler @@\n-  batch-size: 5000\n+  batch-size: 500", "Re-apply batch size 5000 only after heap and session timeout are re-tuned.",
                ["Apply to one consumer first", "Compare GC pauses and lag for 15 minutes", "Roll out to all consumers"], "Return to the last configuration that met the 30-second reconciliation target."),
        _change("CHG-2087", "INC-1037", "Restore producer linger.ms for order events", "Validation", "Low", "Olivia Brooks", "Staging", ["kafka-orders/producer.properties"],
                "--- a/producer.properties\n+++ b/producer.properties\n-linger.ms=500\n-batch.size=262144\n+linger.ms=5\n+batch.size=16384", "Restore the experiment values if throughput targets regress.",
                ["Re-run TEST-851", "Confirm p95 delivery under 2 s", "Close the experiment"], "Latency target matters more than batching efficiency for order confirmations."),
        _change("CHG-2088", "INC-1036", "Allow empty last_name for single-token names", "Validation", "Medium", "Maya Patel", "Staging", ["user-svc/db/migration/V42__split_full_name.sql"],
                "--- a/V42__split_full_name.sql\n+++ b/V42__split_full_name.sql\n-  last_name TEXT NOT NULL,\n+  last_name TEXT NOT NULL DEFAULT '',\n+-- single-token names keep full_name as given_name", "Drop the new columns; full_name remains the source of truth.",
                ["Re-run the migration on a staging copy", "Verify 0 failed rows", "Review UI for single-token names"], "Valid customer names must never block a migration."),
        _change("CHG-2090", "INC-1043", "Restore Payment API connection pool", "Draft", "Low", "Alex Morgan", "Sandbox", ["Payment API sandbox configuration"],
                "PAYMENT_DB_POOL_SIZE: 5 -> 20; keep release v3.8.1 active.", "Set release to previous and pool size to 20 in the isolated Payment API sandbox; verify Feature X is absent.",
                ["Confirm the measured pool exhaustion evidence", "Apply pool size 20 through the sandbox controller", "Repeat the calibrated workload and confirm Feature X"],
                "Restore the previous connection-pool capacity while preserving the v3.8.1 summary endpoint.",
                {"branch": "sandbox/payment-pool-recovery", "sandboxAction": {"release": "3.8.1", "pool_size": 20}, "sandboxRollbackAction": {"release": "previous", "pool_size": 20}}),
    ]

    state["tests"] += [
        {"id": "TEST-851", "incidentId": "INC-1037", "suite": "Order event latency", "category": "Performance", "status": "Failed", "passed": 11, "failed": 1, "skipped": 0, "flaky": 0, "duration": 64.0, "coverage": None, "commit": "51be3c2", "environment": "Staging", "timestamp": stamp(200), "synthetic": True, "source": "Pre-recorded synthetic runner output",
         "cases": [{"name": "order_confirmation_latency", "status": "Failed", "expected": "p95 <= 2000 ms", "actual": "p95 4620 ms", "duration": 60.0, "error": "AssertionError: delivery latency above target"}]},
        {"id": "TEST-860", "incidentId": "INC-1036", "suite": "Profile migration validation", "category": "Data migration", "status": "Failed", "passed": 6, "failed": 1, "skipped": 0, "flaky": 0, "duration": 212.0, "coverage": None, "commit": "f31b9aa", "environment": "Staging", "timestamp": stamp(245), "synthetic": True, "source": "Pre-recorded synthetic runner output",
         "cases": [{"name": "migration_v42_all_rows", "status": "Failed", "expected": "0 failed rows", "actual": "18,204 failed rows (single-token names)", "duration": 200.0, "error": "NOT NULL violation on last_name"}]},
    ]

    for record in KNOWLEDGE:
        state["knowledge"].append({**record, "reviewedAt": stamp(record["reviewedAt"]), "source": "Synthetic operations library"})

    state["deployments"] += [
        {"id": "DEP-2182", "changeId": "CHG-2089", "service": "payment-api", "version": "v3.8.1", "environment": "Sandbox", "timestamp": stamp(25), "status": "Under investigation"},
        {"id": "DEP-2181", "changeId": "CHG-2085", "service": "payment-svc", "version": "fraud-rules v41", "environment": "Production", "timestamp": stamp(82), "status": "Under investigation"},
        {"id": "DEP-2179", "changeId": "CHG-2070", "service": "inventory-svc", "version": "v3.4.0", "environment": "Production", "timestamp": stamp(180), "status": "Under investigation"},
        {"id": "DEP-2177", "changeId": "CHG-2067", "service": "s3-assets", "version": "export-job v2.9.1", "environment": "Production", "timestamp": stamp(430), "status": "Completed"},
    ]

    for index in range(85):
        level, service, message, evidence_id = LOG_TEMPLATES[index % len(LOG_TEMPLATES)]
        state["logs"].append({"id": f"LOG-{1000 + index}", "timestamp": stamp(2 + index * 2), "level": level, "service": service, "environment": "Production",
                              "message": message, "traceId": "trace-5c19e0" if service == "payment-svc" else f"trace-story-{index}", "source": "synthetic-otel-fixture",
                              "attributes": {"deployment": {"payment-svc": "fraud-rules v41", "inventory-svc": "v3.4.0", "frontend-web": "v4.12.2"}.get(service, "current"),
                                             "region": "eu-west-1" if service == "payment-svc" else "us-east-1", "requestId": f"req-story-{index}", "fingerprint": f"{service}:{level}"},
                              "evidenceId": evidence_id})

    for index, (action, resource, actor, previous, next_state, age) in enumerate([
        ("Deployment recorded", "DEP-2181", "Release fixture", "Scheduled", "Completed", 82),
        ("Incident detected", "INC-1041", "Monitoring fixture", "", "New", 76),
        ("Incident triaged", "INC-1041", "James Wilson", "New", "Triaged", 72),
        ("Deployment recorded", "DEP-2182", "Release fixture", "Scheduled", "Completed", 25),
        ("Incident detected", "INC-1043", "Sandbox workload", "", "New", 18),
        ("Evidence attached", "EVD-421", "Release fixture", "", "Observed", 17),
        ("Fix proposed", "CHG-2088", "Maya Patel", "Draft", "Validation", 230),
        ("Recovery verified", "INC-1033", "Alex Morgan", "Monitoring", "Resolved", 300),
    ]):
        state["audit"].append({"id": f"AUD-{1100 + index}", "timestamp": stamp(age), "actor": actor, "role": "Demo fixture", "action": action, "resource": resource,
                               "previous": previous, "next": next_state, "outcome": "Recorded", "correlationId": resource if resource.startswith("INC") else "",
                               "environment": "Sandbox" if resource in {"DEP-2182", "INC-1043", "EVD-421"} else "Production", "evidence": "", "synthetic": True})
