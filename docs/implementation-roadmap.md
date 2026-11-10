# BEHAVE KYNDRYL Implementation Roadmap

Status as of 2026-11-03. Stage gates and stop conditions follow the supplied master engineering prompt. No stage is accepted by documentation alone.

| Stage | Status | Scope and exit condition |
| --- | --- | --- |
| 0: Repository audit | `PASS` | Verified existing application and tests; created audit, architecture, roadmap and role mapping. No blocker prevents the isolated Stage 1A work. |
| 1A: Payment API sandbox | `WARN` | Service, two release behaviors/images, Podman Compose definition, workload runner, sandbox control adapter and governed workflow integration are implemented. Podman is running, but image build is blocked by registry TLS trust; runtime acceptance is `NOT RUN`. Resolve trust through an approved CA or internal mirror, then run three consecutive acceptance cycles and retain each result. The project owner must independently verify Podman Compose, workload and tests. Stop and request confirmation before 1B. |
| 1B: Agents, evidence, events and security | `NOT RUN` | Requires explicit owner confirmation and owner confirmation about Foundry credentials/access. Implement dynamic planning, agent contracts, real sandbox read-only tools, evidence records, authorized manual agent addition, durable events/replay, exact-action approval, adapter integration and provider status. If Foundry is unavailable, report `NOT CONFIGURED`. Stop and request confirmation before Stage 2. |
| 2: 3D workforce and replay | `WARN` | The War Room UI increment adds a lazy React Three Fiber/Drei workforce and accessible 2D fallback, driven by persisted Agent/Evidence snapshots, while preserving XY Flow. Full Stage 2 acceptance is `NOT RUN`: Stage 1B dynamic selection/skip decisions, durable events/replay, manual agent addition UI, and a recorded Stage 1B execution are not available. Complete those after Stage 1B confirmation; verify accessibility and performance on supported hardware before Stage 2 acceptance. Stop and request confirmation before Stage 3. |
| 3: Golden scenario | `NOT RUN` | Requires Stage 2 confirmation. Use the existing Stage 1A failure; compare configuration recovery with rollback in a fully isolated clone; require exact-action human approval for primary remediation; independently validate and persist the full event recording. Stop and request confirmation before Stage 4. |
| 4: Business value and benchmark | `NOT RUN` | Requires Stage 3 confirmation. Freeze one `snapshot-v1`, export raw answer-free evidence, conduct the human baseline and same-snapshot BEHAVE exercise, report measured results and limitations. Live benchmark remains `NOT CONFIGURED` absent a verified provider. Stop and request confirmation. |
| Post-gate enterprise expansion | `NOT STARTED` | Requires explicit approval of Stage 4. Generalize incident intelligence, change impact, blast radius, what-if analysis, tenant isolation, identity, persistence, evidence governance, failure management, evaluations and isolated resilience testing. |

## Immediate Stage 1A Work

1. Add the independently configured Payment API FastAPI service, PostgreSQL database, structured operational signals, health checks and controlled workload.
2. Implement the actual previous release and v3.8.1 behavior, with Feature X (`GET /payments/summary`) available only in v3.8.1.
3. Calibrate a repeatable concurrent workload against pool size 5 (`max_overflow=0`, `pool_timeout=2`, `SELECT pg_sleep(0.3)`) at no less than 15 concurrent requests. Preserve the normal FastAPI exception path for SQLAlchemy acquisition timeout and measure actual HTTP responses.
4. Implement a bounded, audited sandbox control adapter. Connect only Payment API sandbox deploy/rollback actions through the existing `workflow.py` lifecycle and preserve approval checks. Do not add a generic production deployment fallback.
5. Apply pool size 20 through the adapter, restart/reload, and re-run exactly the calibrated workload. Require zero errors, successful API responses, and Feature X availability.
6. Execute three full runs from known initial state and retain each result. A failed run resets the three-run acceptance sequence after its cause is corrected.
7. Report actual results and outstanding owner verification. Do not proceed to Stage 1B until the owner independently verifies Compose, workload and tests and explicitly confirms the next stage.

## Cross-Stage Invariants

- Preserve the current React/Vite, FastAPI, SQLAlchemy, provider boundary, all 14 UI modules, 14 specialist identities and 17 workflow actions.
- Keep `workflow.py` authoritative; do not introduce a parallel lifecycle or approval engine.
- Selection, event states, measurements, provider status and validation must come from actual recorded backend data.
- Never retry non-idempotent operations automatically or claim success when an outcome is uncertain.
- Never silently replace a failed real provider or operation with a mock result.
- Use only the standard truthfulness labels in the master prompt.
- Never remove code until imports, dynamic references, routes, database relationships and tests establish that it is unused.