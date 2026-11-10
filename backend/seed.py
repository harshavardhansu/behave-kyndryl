from datetime import datetime, timedelta, timezone

from .domain import PolicyInput


AGENT_ROLES = [
    ("orchestrator", "Orchestrator", "Coordinates bounded tasks and workflow dependencies", -1),
    ("intake", "Intake & classification", "Normalizes the issue and establishes incident context", 0),
    ("logs", "Log analysis", "Groups recurring exceptions in the authorized time window", 1),
    ("observability", "Observability correlation", "Correlates metrics, traces and dependency evidence", 1),
    ("repository", "Repository analysis", "Inspects the provided read-only source fixture", 1),
    ("knowledge", "Knowledge retrieval", "Retrieves approved runbooks and prior resolutions", 1),
    ("root-cause", "Root-cause analysis", "Evaluates competing hypotheses and missing evidence", 2),
    ("remediation", "Remediation", "Prepares a reviewable proposal without executing code", 3),
    ("testing", "Test engineering", "Evaluates the explicitly synthetic validation fixture", 4),
    ("security", "Security analysis", "Reviews synthetic security evidence and unresolved findings", 4),
    ("validation", "Validation", "Checks mandatory quality gates and acceptance criteria", 4),
    ("risk", "Change risk", "Assesses blast radius and rollback readiness", 5),
    ("release", "Release coordination", "Prepares the human-approved simulated release", 6),
    ("summary", "Incident summary", "Captures the recorded outcome and evidence references", 7),
]


def agent_tasks(incident_id: str) -> list[dict]:
    return [{
        "id": f"{incident_id}-{role}", "role": role, "name": name, "purpose": purpose,
        "status": "Idle", "task": "Awaiting authorized workflow", "incidentId": incident_id,
        "startedAt": None, "lastActivity": None,
        "dependencies": [f"{incident_id}-{other_role}" for other_role, _, _, other_phase in AGENT_ROLES if other_phase == phase - 1 and other_phase >= 0],
        "inputs": [], "outputs": [], "retries": 0, "usage": None,
        "approvalRequired": role == "release", "phase": phase,
        "limitations": "Synthetic deterministic workflow. No model invocation, repository access or code execution.",
    } for role, name, purpose, phase in AGENT_ROLES]


def seed_workspace(demo: bool = True) -> dict:
    anchor = datetime.now(timezone.utc)

    def stamp(minutes: int = 0) -> str:
        return (anchor - timedelta(minutes=minutes)).isoformat()

    state = {
        "mode": "demo" if demo else "production", "snapshotAt": stamp(), "workspace": "Northstar Commerce",
        "incidents": [], "services": [], "dependencies": [], "evidence": [], "hypotheses": [],
        "agents": [], "tests": [], "security": [], "changes": [], "approvals": [], "logs": [],
        "knowledge": [], "audit": [], "deployments": [], "integrations": [], "trends": [],
        "sandboxOperations": [],
        "policy": PolicyInput().model_dump(),
    }
    state["integrations"] = [
        {"id": "demo", "name": "Synthetic workspace", "category": "Evidence", "status": "Demo source" if demo else "Not configured", "description": "Versioned example services, logs and incident evidence. No live telemetry.", "required": []},
        {"id": "foundry", "name": "Microsoft Foundry", "category": "AI provider", "status": "Not configured", "description": "Read-only structured assessment through an authenticated provider boundary.", "required": ["AZURE_AI_PROJECT_ENDPOINT", "AZURE_AI_MODEL_DEPLOYMENT", "Managed identity or Azure CLI identity"]},
        {"id": "entra", "name": "Microsoft Entra ID", "category": "Identity", "status": "Not configured", "description": "Bearer-token validation for production API access. Local personas are demo-only.", "required": ["AZURE_TENANT_ID", "AGENTICA_AUTH_AUDIENCE", "App roles"]},
        {"id": "otel", "name": "OpenTelemetry", "category": "Telemetry", "status": "Not configured", "description": "Collector adapter not enabled. Import JSON, CSV or text evidence locally.", "required": ["Authorized collector endpoint", "Ingestion adapter"]},
        {"id": "github", "name": "GitHub / Azure DevOps", "category": "Repository", "status": "Not configured", "description": "No repository is accessed by entering a URL. Source fixture is read-only.", "required": ["Repository application identity", "Read-only repository allowlist"]},
        {"id": "runner", "name": "Isolated test runner", "category": "Execution", "status": "Not configured", "description": "Untrusted code execution is disabled. Validation replay uses synthetic fixtures.", "required": ["Sandboxed runner adapter", "Network and resource policy"]},
        {"id": "scanner", "name": "Security scanners", "category": "Security", "status": "Not configured", "description": "SAST, SCA, secret and container scanner adapters are not connected.", "required": ["Scanner adapter", "Scoped scanner identity"]},
        {"id": "deployment", "name": "Deployment provider", "category": "Release", "status": "Not configured", "description": "Only a gated simulation is available; no infrastructure writes are performed.", "required": ["Deployment adapter", "Environment-specific identity", "Approval policy"]},
    ]
    if not demo:
        return state

    incident_rows = [
        ("INC-1042", "Checkout failures after v2.18 release", "Critical", "Investigating", "checkout-svc", "Production", 43, "Alex Morgan", "12.8% of checkout requests are failing. Approximately 340 orders per hour are at risk.", "Monitoring alert"),
        ("INC-1041", "Elevated latency on payment authorization", "High", "Triaged", "payment-svc", "Production", 76, "James Wilson", "Payment authorization p95 exceeds 450 ms for a subset of requests.", "Monitoring alert"),
        ("INC-1040", "Inventory reconciliation queue backlog", "High", "Investigating", "inventory-svc", "Production", 112, "Maya Patel", "Inventory updates are delayed by up to 6 minutes.", "Telemetry import"),
        ("INC-1039", "API gateway rate-limit policy regression", "High", "Awaiting Approval", "api-gateway", "Production", 138, "James Wilson", "A subset of authenticated requests receives an incorrect 429 response.", "Manual report"),
        ("INC-1038", "Session cache eviction above baseline", "Medium", "New", "redis-cache", "Production", 181, "Noah Kim", "Some customers must authenticate again during their session.", "Monitoring alert"),
        ("INC-1037", "Order confirmation event delivery delayed", "Medium", "Testing", "kafka-orders", "Staging", 220, "Olivia Brooks", "Staging confirmation events are taking longer than the 2-second target.", "Application testing"),
        ("INC-1036", "User profile migration fails validation", "Critical", "Fix Proposed", "user-svc", "Staging", 252, "Maya Patel", "The staging release is blocked; production data is unaffected.", "Application testing"),
        ("INC-1035", "Recommendation response contract mismatch", "Medium", "Investigating", "recommendation-svc", "Development", 310, "Olivia Brooks", "The integration suite is failing for missing optional fields.", "Repository analysis"),
        ("INC-1034", "CDN stale asset cache after deployment", "Low", "Monitoring", "cloud-cdn", "Production", 370, "James Wilson", "A small set of customers received outdated static assets.", "Manual report"),
        ("INC-1033", "Object storage retry storm in export job", "High", "Resolved", "s3-assets", "Production", 460, "Alex Morgan", "Export jobs were delayed; recorded verification shows recovery.", "Monitoring alert"),
        ("INC-1032", "DNS resolver timeout in integration tests", "Low", "Closed", "cloud-dns", "Development", 620, "Olivia Brooks", "An intermittent integration test was blocked.", "Application testing"),
        ("INC-1031", "Frontend error telemetry missing build tag", "Medium", "Resolved", "frontend-web", "Production", 800, "Maya Patel", "Release attribution was unavailable for client errors.", "Manual report"),
    ]
    for identifier, title, severity, status, service, environment, age, owner, impact, source in incident_rows:
        state["incidents"].append({
            "id": identifier, "title": title, "description": impact + " This is a synthetic incident in the Northstar Commerce demonstration workspace.",
            "severity": severity, "status": status, "service": service, "environment": environment,
            "detectedAt": stamp(age), "owner": owner, "commander": owner, "impact": impact,
            "source": source, "correlationId": "trace-a83f12" if identifier == "INC-1042" else "",
            "error": "SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 2000ms" if identifier == "INC-1042" else "See linked evidence for available observations.",
            "expected": "Checkout completes within 500 ms with an error rate below 1%.",
            "actual": "Checkout p95 is 1,920 ms and error rate is 12.8%." if identifier == "INC-1042" else "A service-level or validation threshold was exceeded.",
            "steps": "Replay the synthetic checkout workload against the supplied configuration fixture.",
            "slaMinutes": 60 if severity == "Critical" else 240 if severity == "High" else 1440,
            "workflowStatus": "Idle", "workflowGeneration": 0, "outcome": "", "recovery": None, "synthetic": True,
        })

    service_rows = [
        ("cloud-cdn", "Cloud CDN", "Cloud", "Healthy", 18, 0.02, 2800, 0, 0),
        ("frontend-web", "frontend-web", "Web", "Degraded", 228, 4.2, 2420, 175, 0),
        ("api-gateway", "api-gateway", "API", "Degraded", 246, 3.4, 2190, 350, 0),
        ("cloud-dns", "Cloud DNS", "Cloud", "Healthy", 4, 0, 3200, 525, 0),
        ("user-svc", "user-svc", "Service", "Healthy", 34, 0.02, 620, 0, 115),
        ("recommendation-svc", "recommendation-svc", "Service", "Healthy", 52, 0.08, 910, 175, 115),
        ("checkout-svc", "checkout-svc", "Service", "Critical", 1920, 12.8, 842, 350, 145),
        ("inventory-svc", "inventory-svc", "Service", "Degraded", 142, 0.4, 730, 525, 115),
        ("redis-cache", "Redis cache", "Cache", "Healthy", 2, 0, 5420, 0, 255),
        ("payment-svc", "payment-svc", "Service", "Degraded", 460, 3.2, 842, 175, 285),
        ("rds-proxy", "AWS RDS proxy", "Cloud", "Degraded", 1811, 6.1, 1240, 350, 285),
        ("kafka-orders", "Kafka orders", "Queue", "Degraded", 86, 0.3, 780, 525, 255),
        ("payment-provider", "Payment provider", "External", "Healthy", 186, 0.1, 734, 175, 415),
        ("postgres-primary", "PostgreSQL primary", "Database", "Degraded", 384, 6.1, 1240, 350, 415),
        ("s3-assets", "S3 assets", "Cloud", "Healthy", 24, 0, 460, 525, 415),
    ]
    for identifier, name, kind, health, latency, error_rate, rps, position_x, position_y in service_rows:
        state["services"].append({
            "id": identifier, "name": name, "type": kind, "health": health, "environment": "Production",
            "latency": latency, "errorRate": error_rate, "rps": rps, "observedAt": stamp(),
            "evidence": ["EVD-301", "EVD-302"] if identifier in {"checkout-svc", "rds-proxy", "postgres-primary"} else ["EVD-306"],
            "changes": ["DEP-2180"] if identifier == "checkout-svc" else [],
            "incidents": [item["id"] for item in state["incidents"] if item["service"] == identifier and item["environment"] == "Production"],
            "position": {"x": position_x, "y": position_y},
        })
    relationships = [
        ("cloud-cdn", "frontend-web", "Content delivery", .99, False),
        ("frontend-web", "api-gateway", "HTTPS requests", .99, False),
        ("cloud-dns", "api-gateway", "DNS resolution", .97, False),
        ("api-gateway", "user-svc", "Authentication", .98, False),
        ("api-gateway", "recommendation-svc", "Recommendations", .96, False),
        ("api-gateway", "checkout-svc", "POST /checkout", .99, True),
        ("api-gateway", "inventory-svc", "Stock lookup", .97, False),
        ("user-svc", "redis-cache", "Session cache", .98, False),
        ("checkout-svc", "payment-svc", "Payment authorization", .96, True),
        ("checkout-svc", "rds-proxy", "Connection acquisition", .98, True),
        ("checkout-svc", "kafka-orders", "Order events", .91, False),
        ("inventory-svc", "kafka-orders", "Stock events", .88, False),
        ("payment-svc", "payment-provider", "External authorization", .99, False),
        ("rds-proxy", "postgres-primary", "SQL connection", .99, True),
        ("kafka-orders", "s3-assets", "Event archive", .72, False),
    ]
    for index, (source, target, relationship, strength, critical) in enumerate(relationships):
        state["dependencies"].append({"id": f"DEP-EDGE-{index + 1}", "source": source, "target": target, "relationship": relationship,
            "strength": strength, "classification": "Inferred" if strength < .9 else "Observed", "latency": 1811 if target == "rds-proxy" else 34,
            "timestamp": stamp(), "evidence": ["EVD-303"] if critical else ["EVD-306"], "critical": critical})

    evidence_rows = [
        ("EVD-301", "Connection acquisition timeout", "Log", "otel-demo / checkout.log:184", "checkout-svc", "Observed", "2026-10-30T09:42:18Z ERROR checkout-svc HikariPool-1: Connection is not available, request timed out after 2000ms. active=10 idle=0 waiting=124 trace_id=trace-a83f12", "Requests are waiting for an available database connection.", 40),
        ("EVD-302", "Connection pool saturation", "Metric", "synthetic-metrics / hikari_connections", "checkout-svc", "Observed", "hikari_active_connections=10; hikari_max_connections=10; hikari_pending_threads=124; checkout_error_rate=12.8%; p95=1920ms", "The pool is saturated while queued requests and latency rise.", 38),
        ("EVD-303", "Checkout distributed trace", "Trace", "synthetic-traces / trace-a83f12", "checkout-svc", "Observed", "POST /checkout 2014ms -> payment.authorize 186ms -> database.acquire_connection 1811ms -> SQLTransientConnectionException", "Connection acquisition dominates the sampled request; the payment span is within baseline.", 37),
        ("EVD-304", "Pool configuration changed in v2.18.0", "Change", "fixture / checkout/application-production.yml:18", "checkout-svc", "Observed", "commit c7f4e21: maximum-pool-size changed from 30 to 10. Deployed 8 minutes before the first error spike.", "Temporal correlation suggests an experiment, but does not prove causation.", 51),
        ("EVD-305", "External payment provider within baseline", "Metric", "synthetic-provider / authorization-slo", "payment-svc", "Observed", "Provider p95=186ms; error_rate=0.1%; availability=99.99% over the sampled incident window.", "This weakens the hypothesis that the external provider initiated the checkout failures.", 35),
        ("EVD-306", "Service topology snapshot", "Document", "fixture / topology-2026-10-30.json", "api-gateway", "Observed", "Synthetic topology from sampled spans and a declared service catalog. Kafka-to-S3 archival and inventory event routing are inferred from configuration and remain unverified.", "Relationships with evidence strength below 0.90 are explicitly inferred, not confirmed.", 30),
        ("EVD-307", "Baseline regression test failure", "Test", "synthetic-runner / TEST-840", "checkout-svc", "Observed", "checkout_concurrent_orders: expected successful responses >=99%; observed 87.2% under a synthetic 50-client workload.", "The baseline fixture reproduces connection-acquisition failure. No tests were run on an external repository.", 22),
        ("EVD-308", "Gateway policy regression validated", "Test", "synthetic-runner / TEST-839", "api-gateway", "Validated", "36/36 synthetic policy checks passed for the rate-limit configuration fixture.", "Supports review of the separate gateway policy change.", 70),
    ]
    for identifier, title, kind, source, service, classification, excerpt, reason, age in evidence_rows:
        state["evidence"].append({"id": identifier, "incidentId": "INC-1039" if identifier == "EVD-308" else "INC-1042", "title": title, "type": kind,
            "source": source, "timestamp": stamp(age), "service": service, "environment": "Production", "classification": classification,
            "excerpt": excerpt, "reason": reason, "traceId": "trace-a83f12" if identifier in {"EVD-301", "EVD-303"} else "", "synthetic": True})
    state["hypotheses"] = [
        {"id": "HYP-42-A", "incidentId": "INC-1042", "title": "Connection pool exhausted after configuration change", "status": "Supported by Evidence", "confidence": .91, "supports": ["EVD-301", "EVD-302", "EVD-303", "EVD-304"], "contradicts": [], "missing": ["Controlled comparison with the previous pool size", "Database connection budget across all replicas"], "nextStep": "Replay the same workload with pool size 30 and verify aggregate connections remain within the database budget.", "agent": "Root-cause analysis", "timestamp": stamp(12)},
        {"id": "HYP-42-B", "incidentId": "INC-1042", "title": "External payment provider degradation", "status": "Under Investigation", "confidence": .18, "supports": ["EVD-303"], "contradicts": ["EVD-305"], "missing": ["Provider-side request correlation for the full incident window"], "nextStep": "Compare provider-side error rates with the affected checkout traces.", "agent": "Observability correlation", "timestamp": stamp(15)},
        {"id": "HYP-42-C", "incidentId": "INC-1042", "title": "Database query regression under concurrency", "status": "Suspected", "confidence": .34, "supports": ["EVD-302"], "contradicts": ["EVD-303"], "missing": ["Query-plan comparison and lock-wait telemetry"], "nextStep": "Inspect query and lock telemetry before attributing the timeout to slow SQL.", "agent": "Repository analysis", "timestamp": stamp(18)},
    ]
    state["agents"] = agent_tasks("INC-1042")
    state["agents"][1].update(status="Completed", task="Incident context normalized", startedAt=stamp(34), lastActivity=stamp(33), inputs=["EVD-301"], outputs=["INC-1042"])
    for task in state["agents"][2:5]:
        task.update(status="Waiting for Evidence", task="Awaiting investigation replay", inputs=["EVD-301", "EVD-303"], lastActivity=stamp(10))

    state["tests"] = [
        {"id": "TEST-840", "incidentId": "INC-1042", "suite": "Checkout regression", "category": "Integration", "status": "Failed", "passed": 42, "failed": 3, "skipped": 1, "flaky": 0, "duration": 38.4, "coverage": None, "commit": "c7f4e21", "environment": "Staging", "timestamp": stamp(22), "synthetic": True, "source": "Pre-recorded synthetic baseline fixture", "cases": [
            {"name": "checkout_concurrent_orders", "status": "Failed", "expected": "Success rate >= 99% at 50 concurrent clients", "actual": "87.2% success; 124 waiting threads", "duration": 12.4, "error": "SQLTransientConnectionException at CheckoutRepository.java:84"},
            {"name": "connection_acquisition_budget", "status": "Failed", "expected": "Connection acquisition < 250 ms", "actual": "p95 1811 ms", "duration": 8.6, "error": "AssertionError: acquisition threshold exceeded"},
            {"name": "checkout_recovery_after_burst", "status": "Failed", "expected": "Recovery within 30 seconds", "actual": "Queue remained above threshold", "duration": 10.1, "error": "Recovery threshold exceeded"},
            {"name": "payment_provider_contract", "status": "Passed", "expected": "Valid authorization response", "actual": "Contract matched", "duration": .8, "error": ""},
        ]},
        {"id": "TEST-839", "incidentId": "INC-1039", "suite": "Gateway policy contract", "category": "Contract", "status": "Passed", "passed": 36, "failed": 0, "skipped": 0, "flaky": 0, "duration": 14.2, "coverage": None, "commit": "b8d2a19", "environment": "Staging", "timestamp": stamp(70), "synthetic": True, "source": "Pre-recorded synthetic policy fixture", "cases": [{"name": "authenticated_rate_limit", "status": "Passed", "expected": "100 requests per minute", "actual": "100 requests per minute", "duration": 1.4, "error": ""}]},
    ]
    state["security"] = [
        {"id": "SEC-201", "title": "Outdated transitive logging dependency", "category": "Dependency scanning", "severity": "High", "service": "recommendation-svc", "status": "Open", "incidentId": "INC-1035", "description": "Synthetic scanner finding: the dependency inventory includes an unsupported logging version. No real vulnerability scan was performed.", "reference": "demo-sca-201", "file": "pom.xml", "line": 62, "guidance": "Update to an approved supported release and rerun dependency and regression checks."},
        {"id": "SEC-202", "title": "Overly broad storage access policy", "category": "Infrastructure as Code", "severity": "Medium", "service": "s3-assets", "status": "Investigating", "incidentId": "", "description": "Synthetic IaC finding: an example statement allows broader object access than the service requires.", "reference": "demo-iac-202", "file": "infra/storage.tf", "line": 31, "guidance": "Scope the policy to the required bucket prefix and explicit operations."},
        {"id": "SEC-203", "title": "Credential-like value in sample build output", "category": "Secret scanning", "severity": "High", "service": "user-svc", "status": "Resolved", "incidentId": "INC-1036", "description": "A synthetic placeholder was redacted: [REDACTED]. No real secret is present in the fixture.", "reference": "demo-secret-203", "file": "build-output.log", "line": 118, "guidance": "Remove sensitive output and rotate any genuinely exposed credential through the approved process."},
    ]
    state["changes"] = [
        {"id": "CHG-2084", "incidentId": "INC-1042", "title": "Restore checkout connection pool budget", "status": "Draft", "risk": "Medium", "owner": "Alex Morgan", "environment": "Production", "branch": "fix/INC-1042-pool-budget", "commit": "demo-fix-42", "files": ["checkout/src/main/resources/application-production.yml"], "diff": "--- a/checkout/src/main/resources/application-production.yml\n+++ b/checkout/src/main/resources/application-production.yml\n@@ -16,5 +16,5 @@ spring.datasource.hikari\n   minimum-idle: 5\n-  maximum-pool-size: 10\n+  maximum-pool-size: 30\n   connection-timeout: 2000\n+  validation-timeout: 1000\n   idle-timeout: 600000", "rollback": "Restore deployment v2.17.3 and its approved configuration. Stop the rollout if p95 exceeds 500 ms or error rate exceeds 1% for 5 minutes. Verify pool usage across all five replicas remains below the 200-connection database budget.", "plan": ["Verify the 150-connection aggregate budget against the 200-connection database limit", "Apply to the isolated staging fixture and review validation evidence", "Obtain separate human approval", "Simulate a 10% canary, compare recovery thresholds, then complete the demo rollout"], "justification": "Restore the previously configured pool size and validate the regression hypothesis under equivalent load.", "approvalId": None, "gates": []},
        {"id": "CHG-2081", "incidentId": "INC-1039", "title": "Correct authenticated gateway rate limits", "status": "Approval", "risk": "Low", "owner": "James Wilson", "environment": "Production", "branch": "fix/gateway-policy", "commit": "b8d2a19", "files": ["gateway/rate-limit.yml"], "diff": "--- a/gateway/rate-limit.yml\n+++ b/gateway/rate-limit.yml\n-requests-per-minute: 10\n+requests-per-minute: 100", "rollback": "Restore the previously approved policy artifact and verify the gateway error rate.", "plan": ["Validate policy fixture", "Obtain human approval", "Simulate controlled rollout", "Record recovery"], "justification": "Restore the approved authenticated request allowance.", "approvalId": "APR-501", "gates": []},
    ]
    state["approvals"] = [{"id": "APR-501", "changeId": "CHG-2081", "incidentId": "INC-1039", "title": "Gateway policy correction", "requestedBy": "James Wilson", "requestedAt": stamp(58), "status": "Pending", "reviewedBy": None, "decidedAt": None, "reason": ""}]

    log_templates = [
        ("ERROR", "checkout-svc", "HikariPool-1 - Connection is not available, request timed out after 2000ms", "EVD-301"),
        ("ERROR", "checkout-svc", "POST /api/v1/checkout returned 503: database connection acquisition failed", "EVD-303"),
        ("WARN", "rds-proxy", "Connection acquisition queue above threshold: waiting=124 active=10 idle=0", "EVD-302"),
        ("INFO", "payment-svc", "Payment authorization completed in 186ms with status=authorized", "EVD-305"),
        ("WARN", "inventory-svc", "Consumer lag increased to 1462 events for inventory-updates", "EVD-306"),
        ("INFO", "api-gateway", "Upstream checkout health check returned degraded", "EVD-306"),
        ("DEBUG", "redis-cache", "Session cache lookup completed: hit=true latency_ms=2", "EVD-306"),
    ]
    for index in range(35):
        level, service, message, evidence_id = log_templates[index % len(log_templates)]
        state["logs"].append({"id": f"LOG-{900 + index}", "timestamp": stamp(3 + index), "level": level, "service": service, "environment": "Production", "message": message, "traceId": "trace-a83f12" if service in {"checkout-svc", "payment-svc", "rds-proxy"} else f"trace-demo-{index}", "source": "synthetic-otel-fixture", "attributes": {"deployment": "v2.18.0", "region": "us-east-1", "requestId": f"req-demo-{index}", "fingerprint": f"{service}:{level}"}, "evidenceId": evidence_id})

    state["knowledge"] = [
        {"id": "KB-101", "title": "Database connection pool saturation", "type": "Runbook", "owner": "Platform Engineering", "version": "2.4", "reviewedAt": stamp(4320), "approved": True, "source": "Synthetic operational handbook", "services": ["checkout-svc", "postgres-primary"], "incidents": ["INC-1042"], "body": "Symptoms\nRising connection-acquisition latency, an exhausted pool and queued request threads.\n\nDiagnostic sequence\n1. Confirm the incident time window and compare active, idle and pending connections.\n2. Compare the pool configuration before and after the recent release.\n3. Inspect slow queries and lock waits to evaluate competing causes.\n4. Check the aggregate connection budget across replicas.\n\nValidation\nReplay an equivalent bounded workload in an isolated environment. Require error rate below 1%, p95 below 500 ms and total connections below the approved budget.\n\nGovernance\nA separate human approver must review the change, validation evidence and rollback plan before any production action."},
        {"id": "KB-102", "title": "Production change readiness checklist", "type": "Release checklist", "owner": "Change Management", "version": "3.1", "reviewedAt": stamp(2880), "approved": True, "source": "Synthetic change handbook", "services": ["api-gateway", "checkout-svc"], "incidents": ["INC-1039"], "body": "Required evidence\nSuccessful build and required regression checks; reviewed security findings; defined blast radius; artifact identity; approved rollback plan; separate human authorization.\n\nRecovery\nDefine measurable success criteria before rollout. Record post-change evidence and keep the change open when verification is inconclusive."},
        {"id": "KB-103", "title": "Checkout v2.18 investigation notes", "type": "Investigation draft", "owner": "Root-cause analysis agent", "version": "0.1", "reviewedAt": stamp(10), "approved": False, "source": "Synthetic AI draft", "services": ["checkout-svc"], "incidents": ["INC-1042"], "body": "Working hypothesis\nA reduced connection pool may explain the observed saturation. EVD-301 through EVD-304 support this hypothesis. EVD-305 weakens the external provider hypothesis.\n\nLimitations\nCausation is not confirmed. Controlled comparison and aggregate connection-budget evidence are still required. This draft is not an authoritative resolution record."},
        {"id": "KB-104", "title": "Handling delayed order events", "type": "Troubleshooting guide", "owner": "Commerce SRE", "version": "1.8", "reviewedAt": stamp(7200), "approved": True, "source": "Synthetic operations library", "services": ["kafka-orders", "inventory-svc"], "incidents": ["INC-1040"], "body": "Collect the consumer group, lag by partition, retry count and event timestamps. Compare producer throughput and consumer capacity. Preserve event IDs before retrying. Do not replay non-idempotent operations without checking deduplication semantics."},
    ]
    state["deployments"] = [
        {"id": "DEP-2180", "changeId": "CHG-2072", "service": "checkout-svc", "version": "v2.18.0", "environment": "Production", "timestamp": stamp(51), "status": "Under investigation"},
        {"id": "DEP-2178", "changeId": "CHG-2069", "service": "frontend-web", "version": "v4.12.2", "environment": "Production", "timestamp": stamp(180), "status": "Completed"},
        {"id": "DEP-2176", "changeId": "CHG-2065", "service": "user-svc", "version": "v1.9.4", "environment": "Staging", "timestamp": stamp(240), "status": "Completed"},
    ]
    for index, (action, resource, actor, previous, next_state, age) in enumerate([
        ("Deployment recorded", "DEP-2180", "Release fixture", "Scheduled", "Completed", 51),
        ("Incident detected", "INC-1042", "Monitoring fixture", "", "New", 43),
        ("Incident acknowledged", "INC-1042", "Alex Morgan", "New", "Investigating", 41),
        ("Evidence attached", "EVD-301", "Log analysis fixture", "", "Observed", 40),
        ("Evidence correlated", "EVD-303", "Observability fixture", "", "Observed", 37),
        ("Hypothesis proposed", "HYP-42-A", "RCA fixture", "", "Supported by Evidence", 12),
        ("Approval requested", "CHG-2081", "James Wilson", "Validation", "Approval", 58),
    ]):
        state["audit"].append({"id": f"AUD-{1000 + index}", "timestamp": stamp(age), "actor": actor, "role": "Demo fixture", "action": action, "resource": resource, "previous": previous, "next": next_state, "outcome": "Recorded", "correlationId": "INC-1039" if resource == "CHG-2081" else "INC-1042", "environment": "Production", "evidence": "EVD-301" if "Evidence" in action else "", "synthetic": True})
    for index in range(7):
        state["trends"].append({"date": (anchor - timedelta(days=6 - index)).strftime("%b %d"), "critical": [1, 2, 1, 0, 2, 1, 2][index], "high": [4, 3, 5, 3, 4, 2, 4][index], "other": [8, 6, 9, 7, 6, 5, 6][index], "resolved": [10, 9, 12, 8, 10, 7, 9][index]})
    return state