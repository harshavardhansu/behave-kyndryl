# BEHAVE KYNDRYL Specialist Role Mapping

Audit date: 2026-11-03. These are 14 logical roles, not a requirement for 14 model deployments. `backend/seed.py` currently provides static role metadata and demo task records. It does not dynamically select agents or execute specialist tools. The implementation status below describes current code, not planned behavior.

| # | Prompt role | Current role ID | Existing capability description | Target Stage 1B responsibility | Current status |
| ---: | --- | --- | --- | --- | --- |
| 1 | Orchestrator | `orchestrator` | Coordinates bounded tasks and workflow dependencies. | Build a plan, delegate eligible specialist tasks, collect/validate results, identify conflicts and determine investigation completion. | Defined; current task is synthetic. |
| 2 | Intake and Classification | `intake` | Normalizes the issue and establishes incident context. | Classify actual incident input and identify required evidence/capabilities. | Defined; current task is synthetic. |
| 3 | Log Analysis | `logs` | Groups recurring exceptions in the authorized time window. | Call read-only `query_logs`; derive findings from returned, provenance-bearing log evidence. | Defined; no live tool. |
| 4 | Observability Correlation | `observability` | Correlates metrics, traces and dependency evidence. | Call read-only `query_metrics`; correlate actual sandbox measurements and available traces. | Defined; no live tool. |
| 5 | Repository Analysis | `repository` | Inspects the provided read-only source fixture. | Call read-only `read_repo_diff` and relate actual release differences to incident evidence. | Defined; only seeded fixtures exist. |
| 6 | Knowledge Retrieval | `knowledge` | Retrieves approved runbooks and prior resolutions. | Retrieve authorized, approved knowledge only and report missing/insufficient knowledge. | Defined; current data is seeded. |
| 7 | Root-Cause Analysis | `root-cause` | Evaluates competing hypotheses and missing evidence. | Form bounded competing hypotheses with authorized evidence IDs, counter-evidence and missing evidence. | Defined; seeded hypotheses are synthetic. |
| 8 | Remediation | `remediation` | Prepares a reviewable proposal without executing code. | Compare Option A pool restoration with Option B release rollback; provide exact proposed action/payload and validation plan. | Defined; current proposal is a fixture. |
| 9 | Test Engineering | `testing` | Evaluates the explicitly synthetic validation fixture. | Define/run only authorized sandbox validation and preserve actual test provenance. | Defined; current validation replay is synthetic. |
| 10 | Security Analysis | `security` | Reviews synthetic security evidence and unresolved findings. | Evaluate actual incident/change security context and applicable tool/data permissions. | Defined; no scanner is configured. |
| 11 | Validation | `validation` | Checks mandatory quality gates and acceptance criteria. | Independently assess active release, pool size, endpoint behavior, workload status and acceptance thresholds. | Defined; current checks are synthetic. |
| 12 | Change Risk | `risk` | Assesses blast radius and rollback readiness. | Analyze the scenario-scoped Payment API/database dependency fixture and compare remediation risks. | Defined; current risk data is seeded. |
| 13 | Release Coordination | `release` | Prepares the human-approved simulated release. | Request a separate human's exact-action approval and invoke only the sandbox adapter after authorization. | Defined; current deploy/rollback is simulated. |
| 14 | Incident Summary | `summary` | Captures the recorded outcome and evidence references. | Summarize actual findings, actions, approval, validation and unresolved limitations with provenance. | Defined; current summary is synthetic. |

## Planner Contract

The planned Stage 1B planner must return a validated plan containing:

- Planner mode and decision timestamp.
- Selected role IDs with input-derived selection reasons and required capabilities.
- Skipped role IDs with input-derived skip reasons.
- Task inputs, dependencies and bounded execution policy.
- Incident/evidence references used to make each selection.

For the mock provider, this is a deterministic rule-based planner and must be displayed as `SIMULATED — RULE-BASED PLANNER`. It must inspect actual incident fields and available evidence; it must not return one fixed team for every case. Generalization tests must cover the Payment API connection-pool incident, a security-flagged change, an incident without repository evidence, and at least two additional materially distinct fixtures. Those cases must prove that relevant team membership and skip reasons change with inputs.

If a real planner provider is configured later, it must emit the same validated contract and display its actual provider mode. A provider failure must remain a failure; it must not silently fall back to the rule-based result.

## Execution and State Integrity

Role identity and planner selection are not evidence that a task ran. Stage 1B execution records must include version, validated inputs/outputs, tool permissions, data-access permissions, timeout/retry policy, evidence references, provider metadata, timestamps and actual status. The workforce UI may display only backend-authoritative task/event status. Manual agent additions must pass backend authorization, capability/input validation, duplicate-active-task protection, audit and event publication; the frontend must never create local-only activity.