# BEHAVE KYNDRYL Upgrade Audit and Foundation Report

## Current Stage 0 Report — Master Engineering Prompt

Audit date: 2026-11-03. The repository and acceptance criteria were checked against the supplied BEHAVE KYNDRYL master engineering prompt. The earlier audit below documents a prior incremental upgrade; where its phase names or scope differ, this current report and the companion [architecture](architecture.md), [implementation roadmap](implementation-roadmap.md), and [agent mapping](agent-mapping.md) govern the new staged work.

**Stage 0: PASS. No blocker prevents Stage 1A.** The application has a usable, tested local foundation and one authoritative workflow state machine. Its existing workflow, role definitions, API and tests can be preserved while Stage 1A adds an isolated sandbox. Dynamic planning, persistent execution events, and real agent tool use are absent; these are material Stage 1B gaps, but do not prevent the independent Payment API sandbox work. No competing orchestration engine is recommended.

| Audit area | Verified current state | Stage 1A / later implication |
| --- | --- | --- |
| Frontend and modules | React 19, TypeScript, Vite, 14 routed modules; existing service topology uses XY Flow. | Preserve the SPA and module routes. Three.js/R3F/Drei are not installed; Stage 2 only. |
| Backend and APIs | FastAPI routes are registered in `backend/app.py`; Pydantic contracts are in `backend/domain.py`. Existing incident, evidence, assessment, workflow, knowledge, admin, repository-fixture and report APIs are present. | Add sandbox APIs only where needed; preserve existing request contracts. |
| Persistence | SQLAlchemy JSON entities, workspace metadata, audit records and sessions in `backend/store.py`; SQLite is the local default. Production configuration requires PostgreSQL, but no migration framework or tenant-scoped records exist. | Payment API must have a separate PostgreSQL database; the main demo database may remain SQLite. |
| Workflow | `backend/workflow.py` owns all 17 required actions, authorization gates, idempotency, approval separation, and synthetic demo execution. | Keep this as the only lifecycle authority. Stage 1A sandbox execution must be behind a bounded adapter, not the demo simulator. |
| Agents and orchestration | `backend/seed.py` defines all 14 logical roles. Starting the demo initializes a fixed set of phase tasks; it does not dynamically select agents or perform specialist analysis. | Existing roles are suitable identity/contracts to preserve, but are not evidence of real agent execution. Implement planning and execution contracts in Stage 1B. |
| Events | Workflow state and audit records persist. The frontend polls `/api/v1/workspace` every 1.2 seconds while a workflow runs and every 30 seconds otherwise. There is no typed persistent event log, sequence/replay API, SSE or WebSocket delivery. | No blocker for Stage 1A. Stage 1B must add durable events and reconnect/replay without replacing workflow state. |
| Providers | An optional Microsoft Foundry adapter performs a bounded, read-only structured assessment. Configuration is not proof of connectivity; the current UI reports unverified configuration. No Foundry credentials or live connection were verified in this audit. | Provider connection state remains `NOT CONFIGURED` until an explicit check succeeds. Mock planning/tools are Stage 1B work. |
| Evidence and security | Manual/upload evidence validation, redaction, hashes/provenance metadata, sensitivity inheritance and provider egress allowlisting exist. Local personas are demo-only; production token validation is present. Tenant isolation, object storage, malware scanning, retention enforcement and tamper-resistant audit are not complete. | Keep sandbox and provider data boundaries explicit. Do not claim production readiness. |
| Payment scenario and infrastructure | No Payment API sandbox, Dockerfile, Compose file, sandbox PostgreSQL service, two-release implementation, workload generator or sandbox control adapter is present. Seeded checkout incidents and tests are synthetic and are not the requested scenario. | Entire Stage 1A operational scenario remains to be implemented and measured. |
| Dependencies and deployment | Frontend dependencies include React, XY Flow, charts, Radix and Lucide; no Three.js/R3F/Drei or LangGraph/Microsoft Agent Framework. Backend includes FastAPI, SQLAlchemy, SQLite/PostgreSQL drivers and optional Azure Foundry libraries. No Docker/Azure deployment files or CI workflow were found. | Continue with `workflow.py` as the sole orchestrator. Add only dependencies needed by an approved stage. |
| Tests | Existing backend and Playwright suites exercise local APIs, workflow gates, evidence handling, route navigation and responsive behavior. | These protect existing behavior; they do not prove the new Payment API acceptance criteria. |

### Stage 0 Standard Report

| Required item | Result |
| --- | --- |
| 1. Objective | Inspect the repository and decide whether the existing architecture can proceed safely into Stage 1A. |
| 2. Features implemented | Stage 0 documentation and verified repository baseline only; no application behavior changed. |
| 3. Existing features preserved | All 14 modules, 14 role definitions, 17 workflow actions, current APIs, evidence controls and XY Flow topology remain unchanged. |
| 4. Files created | `docs/architecture.md`, `docs/implementation-roadmap.md`, `docs/agent-mapping.md`. |
| 5. Files modified | `docs/upgrade-audit.md`. |
| 6. Files removed | None. No unused or redundant application code was removed. |
| 7. API changes | None. |
| 8. Database changes | None. No migrations or data changes. |
| 9. Security changes | None; existing local and production-mode boundaries were documented. |
| 10. Tests executed | Backend pytest suite, TypeScript typecheck, Oxlint, and Playwright browser suite. |
| 11. Actual results | `PASS`: 48 backend tests; `PASS`: typecheck; `PASS`: lint; `PASS`: 9 Playwright tests including production frontend build. |
| 12. Integration status | PostgreSQL Payment API, Docker Compose, Foundry connectivity and cloud resources: `NOT CONFIGURED` or not implemented. |
| 13. Simulation boundaries | Existing demo workflow, seeded operational data, replay validation and deployment/rollback remain explicitly synthetic. |
| 14. Remaining acceptance items | All Stage 1A sandbox implementation and three-run acceptance items remain. Independent owner execution is required before Stage 1A can be accepted. |
| 15. Next-stage prerequisites | Stage 1A may proceed automatically. Stop after its three complete runs and owner verification; request explicit confirmation before Stage 1B. |

The audit found no Stage 0 stop condition. This is not a production-readiness assessment and does not certify PostgreSQL, Docker, cloud identity, provider connectivity or external deployment.

## Current Stage 1A Report — Payment API Sandbox

Implementation date: 2026-11-03. **Stage 1A status: `WARN`.** The isolated service, Podman Compose definition, workload runner, sandbox adapter and existing-workflow integration are implemented. Podman 5.8.1 and the Podman machine are running, and `podman-compose` 1.6.0 is selected explicitly. The image build is blocked because TLS verification fails while pulling `python:3.12-slim` from `docker.io` (`x509: certificate signed by unknown authority`). Certificate verification was not disabled. No live PostgreSQL pool-exhaustion result or three-run pass is claimed.

| Required item | Result |
| --- | --- |
| 1. Objective | Add the isolated Payment API/PostgreSQL scenario and a bounded, governed way to change only that sandbox. |
| 2. Features implemented | PostgreSQL-only FastAPI sandbox; v3.8.1 summary route and previous-release route omission; pool/timeout configuration; structured logs and bounded request metrics; concurrent workload runner; fixed-project control adapter; approval-bound workflow deploy/rollback; three-cycle acceptance runner. |
| 3. Existing features preserved | React/Vite, FastAPI APIs, SQLite local workspace, all 14 modules, 14 role definitions, 17 actions, provider abstraction, XY Flow topology and other services’ simulation behavior. `workflow.py` remains the only lifecycle authority. |
| 4. Files created | `Containerfile`, `compose.yaml`, `.containerignore`, `requirements-podman.txt`, `backend/payment_sandbox.py`, focused backend tests, `payment_api/app.py`, `payment_api/requirements.txt`, sandbox env example, workload runner and tests, `scripts/stage1a_acceptance.py`. |
| 5. Files modified | `.env.example`, `README.md`, `backend/app.py`, `backend/domain.py`, `backend/seed.py`, `backend/workflow.py`, Sandbox intake/types/filters, browser tests, this report and the roadmap. |
| 6. Files removed | `Dockerfile`, `docker-compose.yml`, `.dockerignore`; replaced with Podman-native `Containerfile`, `compose.yaml`, and `.containerignore` per company policy. |
| 7. API changes | Payment API exposes `/health`, `/control/config`, `/metrics`, and only v3.8.1 exposes `/payments/summary`. Existing incident intake accepts only `service=payment-api` with `environment=Sandbox`; its governed deploy/rollback actions use the sandbox adapter. |
| 8. Database changes | Payment API requires PostgreSQL and creates/seeds its `payments` table at startup. The existing BEHAVE store remains unchanged in schema; sandbox operation records persist in its workspace metadata. No migrations were added. |
| 9. Security changes | Loopback-only ports; fixed Compose project/service; release/pool allowlists; exact approval payload hash; existing backend permission and separate-approver checks; adapter JSONL audit plus workflow audit; interrupted operations require manual inspection and are never replayed automatically. |
| 10. Tests executed | Combined backend and Payment API pytest suites; frontend typecheck, lint and Playwright; Python compile checks; YAML parse/structure check. |
| 11. Actual test results | After the Podman switch: `PASS`: 68 backend/Payment API tests; `PASS`: 8 focused adapter tests; `PASS`: TypeScript typecheck; `PASS`: Oxlint; `PASS`: 10 Playwright tests; `PASS`: `podman compose --profile release-build config --quiet`. The two release image builds were attempted and `FAIL`ed at registry TLS certificate verification. `NOT RUN`: PostgreSQL health, actual HTTP 500/log verification, pool-20 recovery and three consecutive acceptance cycles. |
| 12. Integration status | Podman 5.8.1 engine and Podman machine: `REAL` and reachable. Native `podman-compose` 1.6.0: installed and selected. Sandbox images: `NOT CONFIGURED`; registry pull is blocked by TLS trust. Microsoft Foundry and cloud infrastructure remain `NOT CONFIGURED`. |
| 13. Simulation boundaries | Sample payment rows are seeded (`SYNTHETIC`). Unit/integration test doubles are test-only fixtures. No workload measurement exists yet; the harness labels output `MEASURED` only when it actually sends requests. Existing non-sandbox agent work remains synthetic. |
| 14. Remaining acceptance items | Configure an approved registry mirror or install the company-approved CA into the Podman machine without weakening TLS; build and run with Podman; execute `scripts/stage1a_acceptance.py` for three complete runs; retain all run JSON; independently verify Compose, workload and tests as project owner. Any failed run restarts the full three-run sequence. |
| 15. Next-stage prerequisites | Stage 1A acceptance and owner verification must pass. Then stop and request explicit Stage 1B confirmation and confirmation about Foundry credentials/access. Stage 1B has not started. |

The acceptance runner writes evidence under `test-results/stage1a/<sequence>/`. Because that directory is generated test output and ignored, copy/retain the verified run artifacts through the project’s approved handoff process; no results exist in this workspace yet.

## Current War Room UI Increment Report

**Status: UI implemented; full Stage 2 acceptance remains `NOT RUN`.** This increment upgrades the existing AI War Room display without changing backend workflows, APIs, persistence, approval policy, or XY Flow behavior.

- The central workforce defaults to a lazy-loaded Three.js/React Three Fiber/Drei scene on desktop. All 14 existing task identities are represented from the selected incident’s current backend snapshot; the Orchestrator is central and specialist positions are deterministic.
- Specialist state colors and the restrained active pulse use only the persisted task status. Connections use the recorded task dependency IDs. Evidence markers and labels use task input/output references that resolve to evidence attached to the same incident. No communication events, planner selections, skip reasons, live telemetry, model usage, progress values, or workflow ID are invented.
- The existing XY Flow service topology remains available through the Workforce/XY Flow switch. The existing incident context, hypothesis findings, event timeline, logs, task controls, release readiness, authorization, and approval flows remain in place.
- The agent inspector shows persisted identity, task, status, timestamps, retries, usage availability, approval state, declared dependencies, linked evidence, and execution limitations. Clicking 3D nodes/labels selects the existing inspector; evidence labels open the existing evidence inspector.
- Role/status filters, labels, focus, camera reset, OrbitControls, fullscreen, reduced-motion handling, an accessible 2D workforce, WebGL detection, and a forced WebGL-failure fallback are implemented.
- 3D dependencies installed: Three.js 0.187.0, React Three Fiber 9.8.2, Drei 10.7.9. Package changes are recorded in the npm manifest/lockfile.
- Verification: `PASS` TypeScript typecheck, `PASS` Oxlint, `PASS` 12 Playwright tests including the existing XY Flow/workflow regressions, WebGL fallback, and desktop/tablet/mobile layouts. Screenshots are generated under ignored `test-results/workspace-desktop-tablet-a-a62aa-ts-stay-within-the-viewport/`.
- A local 120-frame browser sample measured approximately 2.02 s, median frame interval 16.7 ms, p95 17.1 ms, and zero sampled intervals above 33 ms on this session’s WebGL browser. This is a local observation, not a hardware-wide target or long-session benchmark.
- Stage 2 remains incomplete: no dynamic planner decisions/skip reasons, durable execution-event stream/replay, actual Stage 1B recording, real agent execution, provider inference visibility beyond `NOT CONFIGURED`, manual agent-add UI, concurrent workflow isolation test, long-session memory measurement, or supported-hardware performance certification. Existing backend agents still run the explicitly synthetic workflow.

Date: 2026-10-31. Target specification: "MASTER ENTERPRISE ENGINEERING UPGRADE - 3D AI WORKFORCE & OPERATIONAL INTELLIGENCE" supplied by the user.

**Subsequent naming update (2026-10-31):** At the user's request, the visible product name is now exactly BEHAVE KYNDRYL across the shell, title/metadata, loading/sign-in/error screens, product messages, API documentation and report filenames. Internal settings, cookies and saved-session keys remain unchanged. Five focused browser tests passed, including exact-case branding and desktop/tablet/mobile layouts; build and lint passed. This supersedes the earlier pending-name statements below, not the remaining enterprise or 3D scope. No backend behavior or stored historical records were migrated for the rename.

## Scope and Phase Status

Phase 0 was a read-only code/test audit before implementation. Its baseline was 26 passing backend tests, passing TypeScript checks and passing lint. This report was subsequently written during the first Phase 1 increment.

The existing UI is a functional demonstration, not full compliance with the redefined specification. In particular, the 3D workforce, most intelligence services and enterprise data governance do not exist yet. No implementation percentage or production readiness is claimed.

| Phase | Status | Dependency and exit condition |
| --- | --- | --- |
| 0: Repository audit | PASS | Code/contracts/security inspected, executable baseline recorded, ordered plan produced. |
| 1: Foundation | WARN | First security/reliability increment tested. Tenant-scoped persistence, migrations, execution/event contracts and remaining governance/recovery controls are still required. |
| 2: 3D workforce | NOT RUN | Start only after Phase 1's authoritative execution/event and authorization contracts are tested. |
| 3: Operational intelligence | NOT RUN | Requires tenant-safe evidence, dependency records and stable assessment contracts. |
| 4: Evaluation and optimization | NOT RUN | Requires recorded execution/usage, versioned policies/datasets and reviewed knowledge lineage. |
| 5: Resilience and assurance | NOT RUN | Requires an isolated fault-injection harness and verified recovery contracts. |
| 6: Product quality | NOT RUN | Final rebranding, accessibility, performance and complete acceptance review follow preceding phases. |

The favicon repair is a narrow regression fix for the existing application, not completion of the later product-quality phase. No 3D scene or second workflow engine was introduced.

## Phase 0 Comparison

| Requirement | Evidence in current application | Remaining gap |
| --- | --- | --- |
| Preserve architecture, agents, actions, modules | [Routes](../src/App.tsx), [agent identities](../backend/seed.py), [actions](../backend/workflow.py); regression and browser checks pass. | Preserve these contracts during every subsequent migration. |
| BEHAVE Kyndryl branding | Current UI still displays Agentica. | Apply the new name/tagline consistently without renaming compatibility-sensitive cookies, configuration or contracts unnecessarily. |
| 3D workforce | War Room has a working [XY Flow topology](../src/pages/WarRoom.tsx); [dependencies](../package.json) contain no Three.js/R3F/Drei. | Dedicated lazy-loaded 14-agent scene, backend-driven statuses, meaningful connections, inspector, camera/filter/fullscreen controls, keyboard selection, reduced motion, cleanup and WebGL/2D fallback. |
| Authoritative real-time events | [Context](../src/context.tsx) polls snapshots at 1.2 seconds while workflows run and 30 seconds otherwise. | No SSE/WebSocket infrastructure, replay cursor, event sequence, deduplication or event outbox. Build this before visualizing communication. |
| Incident intelligence | Stored incident/evidence/knowledge records; local search and fixture hypotheses. | No backend similarity ranking/explanations using attributes, dependency context and approved outcomes. Similarity must not become causality. |
| Change impact prediction | Stored changes, review gates and service dependencies. | No backend impact assessment or evidence-backed risk paths, business impact, uncertainty or history-based pre-release checks. |
| What-if remediation | Proposed fixture diff and rollout/rollback plans; Reports has a business-effort estimator. | No backend multi-plan simulator. The effort estimator is not remediation simulation. |
| Blast radius | Inspectable service/dependency graph. | No incident/change-rooted traversal assessment with explainable upstream/downstream paths, business/data dependencies and graph-gap disclosures. |
| Agent evaluation centre | Task statuses, not evaluation results. | Versioned evaluation dataset, documented formulas, per-agent scorecards, case results, regression comparisons, citation/policy checks and reviewer feedback absent. |
| AI cost intelligence | Optional provider call; no retained provider token usage/pricing ledger. | Record actual provider metadata and attempts first, then apply versioned configured prices. Missing usage/pricing must remain Unavailable. |
| Operational learning | Closure creates a draft; separate knowledge review and recovery requirements exist. | Requests for changes, immutable versions/review history, sensitivity lineage and tenant-safe approved-only retrieval are incomplete. |
| SLA intelligence | [SLA display](../src/lib/format.ts) uses incident timestamps and `slaMinutes`. | Creation infers durations from severity and ticket import hardcodes a duration. Replace with configured service/environment policies and policy provenance; no invented deadline when policy is absent. |
| Resilience testing | Existing isolated pytest/Playwright suites; new database/provider fault regressions. | No in-app isolated assurance lab, fault catalog, run records or complete timeout/process/event/tool/approval/remediation/restart coverage. |
| Explainable recommendations | Evidence links, hypotheses, missing evidence and next experiment; optional structured assessment. | Standard recommendation contract needs alternatives, risk comparison, assumptions, preconditions, approval and validation plan. Model confidence is not a calibrated accuracy measure. |
| Agent/provider failure management | Manual pause/resume/cancel/retry, task timeout budget, bounded provider concurrency/SDK retry; model failure records strengthened in this increment. | Per-attempt records with parent execution, distinct timeout states, jitter/backoff policy, circuit health, dead-letter handling, alternative delegation and unified Failure Centre absent/incomplete. |
| Workflow recovery | Persisted snapshots; restart pauses running demo workflows; model requests now require manual review if interrupted. | Durable versioned checkpoints for every task and external outcome, reconciliation protocol and complete multi-worker/restart tests still required. |
| Database reliability | Transaction rollback, row lock in mutations, connection wait limits and readiness query. | No versioned migrations, restore verification or deployment-grade concurrency/failover tests. Readiness is not a complete recovery/backup system. |
| Tenant isolation | [Store](../backend/store.py) has one `main` workspace; queries are not tenant-scoped. Entra issuer/tenant checks restrict identity, not data rows. | Tenant keys, tenant-scoped authorization/queries/objects/retrieval/reports/audit, database constraints/RLS where applicable and cross-tenant record access tests are mandatory. |
| Data classification and access | New incident/evidence sensitivity metadata, inheritance and outbound provider allowlist. | No sensitivity-based read/export authorization, owners/stewards/agent context ACLs or systematic classification of every entity/legacy record. |
| Evidence provenance/files | Allowlisted bounded text/JSON/CSV, safe filenames, redaction and new hashes/collector metadata. | Tenant provenance, access history, object storage, original/derivative retention policy and malware scanner enforcement are not implemented. |
| Retention/deletion | A declared `retentionDays` field and UI warning. | No category-specific retention job, legal hold, controlled deletion or expiry enforcement. Store currently upserts and does not reconcile deletions. |
| Audit governance | Action audit events are inserted separately; no ordinary UI audit-edit route. | Database-admin tamper resistance, access/export completeness, cryptographic verification/append-only database controls and protected retention are missing. |
| AI data governance | Structured provider boundary, untrusted-input instruction, evidence references, redaction and new egress deny rules. | Prompt/model/agent version lineage, comprehensive sensitive-data detection, residency/contracts, tenant retrieval, evaluation outcomes and actual provider usage still required. |
| UX and accessibility | Existing light dashboards, tables, controls and responsive navigation tested. | New dark War Room/workforce experience and complete keyboard/screen-reader/reduced-motion/performance acceptance not implemented or verified. |

## Dependency-Aware Implementation Plan

1. Finish Phase 1 tenant/persistence design first: tenant identity mapping from verified authorization, tenant-owned schema/queries and object namespaces, explicit versioned migration from the current single-workspace store. Require a reviewed mapping for legacy data rather than assigning an invented production tenant. Add cross-tenant read/write/export/audit/knowledge tests and PostgreSQL migration/concurrency checks.
2. Extend the existing workflow engine, not replace it: versioned execution/attempt/failure/checkpoint records and a transactional event outbox. Define status, sequence, correlation/causation IDs, mode, evidence and dependency references. Persist before reporting completion. Require idempotency and manual intervention for uncertain external outcomes.
3. Complete foundational governance: immutable original/derivative object references where authorized, classification/access controls, provider context minimization, malware adapter policy, retention/holds/deletion, append-only or tamper-evident audit and verified backup/restore procedures. Do not turn a declared setting into a claim of enforcement.
4. Add authenticated event delivery with bounded reconnect, replay and deduplication, plus authoritative snapshot resynchronization. Test lost/duplicate events, provider failure/backoff and restart reconciliation. Complete Phase 1's acceptance report before moving to 3D.
5. Phase 2: reuse existing agent identities with R3F/Drei/Three.js. Keep XY Flow topology. Introduce a shared agent inspector and keyboard-accessible 2D workforce first, then lazy-load 3D with cleanup, reduced motion and WebGL fallback. Only recorded events/dependencies may produce connections. Verify screenshots and canvas pixels on desktop/mobile as well as event-state tests.
6. Phase 3: tenant-authorized incident similarity, dependency-path impact/blast radius, then a read-only multi-plan simulation/recommendation contract. These services must never invoke the workflow's execution actions. Return method, evidence, alternatives and uncertainty.
7. Phase 4: record provider usage before cost estimates; version pricing and evaluation datasets/formulas. Replace severity-based SLA defaults with configured policies. Extend reviewed learning with versions, sensitivity lineage and requests for changes. Show Unavailable when inputs do not exist.
8. Phase 5: isolated assurance workers/databases/object namespaces, explicit target authorization and no production routing. Implement the required fault matrix, recovery evidence and assessment reports with actual PASS/FAIL/WARN/NOT RUN/NOT CONFIGURED statuses.
9. Phase 6: complete BEHAVE Kyndryl rebranding, professional dark/light layouts, accessibility/performance tests and a reliable demonstration of Detect -> Investigate -> Correlate -> Understand -> Assess Risk -> Simulate -> Recommend -> Approve -> Execute -> Validate -> Learn. Preserve simulation/estimate/unconfigured labels.

Redis is not currently used. Add it only if delivery/coordination requirements justify it; do not introduce unnecessary microservices. Existing Foundry provider abstraction and the 17 actions remain authoritative.

## Phase 1 Increment Report

### 1. Features Implemented

- Database readiness actually queries the workspace table and returns 503/UNAVAILABLE on a storage failure. Database exceptions return a sanitized failure rather than a success claim. Connection/pool wait limits are bounded; no automatic write retry was added.
- Production SQLite is rejected before application initialization. PostgreSQL and configured Entra identity remain prerequisites, not production certification.
- Entra tokens require a matching tenant claim, valid object identifier and explicit known application role; an unassigned identity no longer silently receives Viewer access.
- New incident/evidence inputs carry Public/Internal/Confidential/Restricted sensitivity separately from evidence reliability. Default is Internal. Evidence cannot downgrade its parent incident's sensitivity.
- Provider egress requires an explicitly configured classification allowlist, default empty. Restricted/unknown sensitivity is blocked. Checks apply both at the assessment API and Foundry boundary. Denials are audited without dispatching the provider. Integration status discloses a missing data policy.
- New manual/uploaded evidence includes collector, collection time, byte count, original and derivative hashes, hash scope, MIME, pattern-filter status and a database derivative reference. Raw originals are not retained; malware scanning is explicitly NOT CONFIGURED. Uploaded log derivatives inherit sensitivity and their trace/severity fields are redacted.
- Upload MIME mismatches are rejected. Linked-incident environment permissions apply to manual test intake and repository replay. Checkout fixture findings cannot be attached to unrelated incidents.
- Model requests retain execution references, evidence IDs, sensitivity, activity times and failed outcomes. Invalid schema/unexpected provider failures do not add findings or approvals. Interrupted requests become MANUAL_INTERVENTION_REQUIRED; no provider call is automatically repeated at restart.
- The existing favicon is referenced from the HTML head, resolving the previously failing navigation-console test.

### 2. Files Created

- [backend/data_governance.py](../backend/data_governance.py): shared sensitivity, outbound policy and provenance functions.
- [docs/upgrade-audit.md](upgrade-audit.md): this comparison, plan and phase report.

### 3. Files Modified

- [backend/app.py](../backend/app.py): production guard, readiness/error responses, identity checks, evidence policy/provenance, linked-record permissions and model failure handling.
- [backend/domain.py](../backend/domain.py): typed sensitivity and provider classification configuration.
- [backend/providers.py](../backend/providers.py): policy validation at the provider boundary.
- [backend/store.py](../backend/store.py): connection waits and lightweight readiness query.
- [backend/tests/test_workflow.py](../backend/tests/test_workflow.py): storage, identity, authorization, provenance, MIME and preserved-contract regressions.
- [backend/tests/test_providers.py](../backend/tests/test_providers.py): allowlist, restricted-data, failure, interrupted-request and integration-status regressions.
- [index.html](../index.html): existing favicon reference.
- [.env.example](../.env.example): explicit empty provider classification allowlist.
- [README.md](../README.md): verified setup, configuration, testing and security boundaries.

### 4. Existing Modules Preserved

All 14 navigation modules and the incident-detail route remain in place. No frontend page was rebuilt. Existing XY Flow topology and all 14 agent definitions/17 action names are unchanged. The original governed workflow suite and browser flow pass.

### 5. APIs Added or Changed

No duplicate APIs or workflow actions added. Existing APIs gained the following behavior:

| API | Change |
| --- | --- |
| `GET /api/v1/health` | Adds database readiness; returns 503 on a failed query. |
| Authenticated production APIs | Require matching `tid`, nonempty `oid` and an assigned known role in addition to JWT verification. |
| `GET /api/v1/workspace` | Foundry entry exposes allowed sensitivity categories and blocked-policy status; model execution failure metadata is retained in the snapshot. |
| `POST /api/v1/incidents` and ticket import | Optional typed `dataClassification`, default Internal. |
| `POST /api/v1/incidents/{id}/evidence` | Sensitivity inheritance and provenance for validated manual input. |
| `POST /api/v1/incidents/{id}/evidence/upload` | Optional multipart `dataClassification`, MIME validation, provenance and derivative sensitivity. |
| `POST /api/v1/incidents/{id}/assessment` | Audited 403 before dispatch for disallowed data; persisted failed/incomplete outcomes; schema validation before recording. |
| `POST /api/v1/incidents/{id}/tests` | Enforces the linked incident's actual environment permission. |
| `POST /api/v1/repositories/analyses` | Enforces linked incident authorization and exact fixture association. |

SQLAlchemy failures across APIs receive a sanitized 503. Clients must inspect authoritative state and reuse the original idempotency key where supported rather than blindly retry non-idempotent operations.

### 6. Database Changes and Migrations

No schema migration or tenant backfill was run. No user database was deleted or recreated. New fields are additive JSON record metadata within the existing store. Pre-existing records do not acquire fabricated collection identities or hashes. Old sensitivity metadata defaults to Internal for outbound checks; invalid values fail closed.

The `main` workspace and unscoped entity queries remain a major gap. PostgreSQL runtime/concurrency/migration/restore testing is NOT RUN. PostgreSQL selection enforcement alone is not multi-tenancy or durable-queue architecture.

### 7. Tests Executed

- `python -m pytest backend/tests -q` with `DATABASE_URL=sqlite:///:memory:` and demo mode, including isolated module import.
- Focused storage tests first reproduced both readiness/production-SQLite gaps, then passed after repairs.
- Focused provider/workflow suites after each substantive backend increment.
- `npm run typecheck`, `npm run lint`, `npm run test:e2e` and the focused all-modules navigation test.
- Editor diagnostic checks on modified Python files and HTML.

### 8. Actual Test Results

| Check | Result |
| --- | --- |
| Pre-change backend baseline | PASS: 26 tests. |
| First new readiness/production tests before fix | FAIL: 2 reproduced gaps, subsequently corrected. |
| Final complete backend suite | PASS: 48 tests, 8.43 seconds. |
| Initial full browser run | FAIL: 7 passed, 1 failed on missing `/favicon.ico`. |
| Focused navigation after favicon fix | PASS: 1 test. |
| Final complete browser suite | PASS: 8 tests, 49.4 seconds. |
| Production frontend build | PASS as part of the final browser command. |
| TypeScript and lint baseline | PASS; later builds also typechecked. |
| Modified-file editor diagnostics | PASS: no reported errors. |
| 3D rendering/events/fallback/accessibility/resource cleanup | NOT RUN: not implemented. |
| Cross-tenant data access, retention/holds, protected audit and object storage | NOT RUN: foundation incomplete. |
| Live PostgreSQL, Entra tenant, Foundry, telemetry, runner, scanner, deployment | NOT CONFIGURED in this verification environment. |

Runtime: Windows, Node 26.7.0, Python 3.14.7, installed Microsoft Edge. Browser tests used isolated in-memory storage and ports 15173/18001, not the persistent demo store. Signed-token tests use generated local RSA keys and stubbed database/JWKS boundaries, not a live Entra/PostgreSQL deployment.

### 9. Security Checks

PASS for the executed checks: anonymous/viewer write rejection, CSRF/cross-origin checks, environment checks, separate-human approval, stable-ID self-approval rejection, explicit deployment confirmation, idempotent action replay, critical-finding gates, redaction, filename/format/MIME rejection, sensitivity inheritance, disallowed provider dispatch, restricted-data denial, role/identity-tenant rejection, transaction rollback and sanitized failure responses.

These checks cover local boundaries only. There is no full penetration test, tenant row-isolation test, production DLP/malware scan, secret audit of the entire workspace or comprehensive accessibility certification.

### 10. Known Limitations

Phase 1 is not complete. The largest remaining risks are unscoped single-workspace data access, no migration framework, no durable event/attempt contracts, no object storage/access-history controls, no retention/legal holds and insufficient audit tamper protection. Classification metadata and provider egress restrictions do not implement classification-based read/export permissions. Legacy record provenance cannot be retroactively verified.

Model failures are recorded, but unified Failure Centre, circuit breaking, detailed SDK attempt accounting, dead-letter handling, calibrated timeout states and full recovery testing remain outstanding. The application still has legacy severity-derived SLA defaults and synthetic root-cause/validation fixtures; these must not be described as live intelligence.

### 11. Unconfigured Integrations

Live Microsoft Foundry/Entra, PostgreSQL deployment, persistent object storage, malware scanning, OpenTelemetry collector, repository adapter, isolated code runner, security scanners and deployment provider are NOT CONFIGURED or not implemented here. Redis is absent by design unless a later requirement justifies it. No cloud IDs/endpoints/credentials were provisioned or invented for deployment.

### 12. Remaining Work

Follow the dependency plan above. Finish and test Phase 1 before Phase 2. Keep Phase 2-6 acceptance checks NOT RUN until each implementation is verified. The visible Agentica-to-BEHAVE Kyndryl transition and all new workforce/intelligence pages remain pending; existing functionality must remain usable throughout.

### 13. Real, Simulated or Estimated

**Real local behavior:** persistence, form validation, role/environment enforcement, review decisions, failure responses, metadata/hash calculation and outbound policy checks. **Simulated:** specialist workflow execution, checkout analysis/testing, release/rollback/recovery, seeded telemetry and findings. **Estimated:** the existing Reports scenario estimator; it is not AI usage billing or a remediation simulator. **Unconfigured:** external adapters listed above. **Failed/incomplete:** persisted provider failures and interrupted requests are explicitly recorded and never promoted to success merely because a retry is possible.