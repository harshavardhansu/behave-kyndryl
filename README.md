# BEHAVE KYNDRYL

The existing React/TypeScript and FastAPI application is being upgraded incrementally to the BEHAVE KYNDRYL specification, "Your Problem. Their Mission."

**Current status:** functional single-workspace local demonstration with persisted records, 14 specialist role definitions, 17 governed actions and 14 navigation modules. Stage 0 is audited. The isolated Payment API Stage 1A implementation is present, but Docker/PostgreSQL runtime acceptance and the required three consecutive runs are **NOT RUN** in this environment. The visible product name is BEHAVE KYNDRYL. Dynamic agent execution, durable events, the 3D workforce and the later enterprise roadmap are not complete. See the [audit and phase report](docs/upgrade-audit.md).

## Run Locally on Windows

Install Node.js with npm and Python. Verification on 2026-10-31 used Node 26.7.0, Python 3.14.7 and Microsoft Edge; other runtime versions were not certified in this audit.

Open PowerShell in the project root. For a fresh copy only:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm ci
```

Create your local configuration only if it does not already exist:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Terminal 1, backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2, frontend:

```powershell
npm run dev -- --host 127.0.0.1 --port 5173
```

Open the URL printed by Vite, normally http://127.0.0.1:5173/. API documentation is at http://127.0.0.1:8000/api/docs and database readiness at http://127.0.0.1:8000/api/v1/health. Keep both terminals running. Activation of the Python virtual environment is optional when using its executable explicitly.

## Payment API Sandbox (Stage 1A)

The sandbox is an independent PostgreSQL-backed service. The existing BEHAVE backend and Vite frontend continue to run with the commands above so the sandbox adapter can invoke its fixed, allowlisted Podman Compose project from the host. Do not mount the Podman socket into the BEHAVE backend container.

Install and start Podman Desktop first. Confirm the Podman machine is running with `podman machine list`. Install the native Compose provider into the project virtual environment, then initialize the sandbox-only environment file if it does not exist:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements-podman.txt
if (!(Test-Path payment_api\.env.sandbox)) { Copy-Item payment_api\sandbox.env.example payment_api\.env.sandbox }
$env:PODMAN_COMPOSE_PROVIDER = (Resolve-Path .\.venv\Scripts\podman-compose.exe).Path
podman compose --project-name behave-payment-sandbox --env-file payment_api\.env.sandbox --file compose.yaml --profile release-build build payment-api payment-api-previous
podman compose --project-name behave-payment-sandbox --env-file payment_api\.env.sandbox --file compose.yaml up -d payment-db payment-api
```

The API is bound to `127.0.0.1:18080`; PostgreSQL is bound to `127.0.0.1:15432`. The previous release is built separately and is only started by the acceptance runner on `127.0.0.1:18081`. The example password is for local development only and must not be reused outside this isolated sandbox.

The sandbox uses native Podman commands only; the adapter explicitly selects the pinned `podman-compose` provider and does not fall back to Docker Compose. In this workspace Podman 5.8.1 and `podman-compose` 1.6.0 were verified, but the image build is currently blocked by `x509: certificate signed by unknown authority` from `docker.io`. Do not mark Stage 1A acceptance complete until your company-approved registry mirror or CA trust is configured and the three-cycle runner succeeds. Do not disable TLS verification or mark the registry insecure.

Run the measured three-cycle acceptance sequence from another PowerShell terminal:

```powershell
& .\.venv\Scripts\python.exe -m scripts.stage1a_acceptance
```

The runner resets the active release/pool to v3.8.1 and 5, verifies PostgreSQL and Feature X, starts the previous release to confirm `GET /payments/summary` is absent, runs the same 50-request workload before and after pool restoration, checks actual service logs for SQLAlchemy `TimeoutError`, and retains each run under `test-results\stage1a\<sequence>\`. A failed run stops that sequence; correct the cause and run the complete three-cycle sequence again. The runner leaves v3.8.1 active at pool size 20 after a successful sequence.

To run the workload once without the acceptance assertions:

```powershell
& .\.venv\Scripts\python.exe -m payment_api.workload --expect-errors --output test-results\stage1a\pool-5.json
```

The adapter sets `PODMAN_COMPOSE_PROVIDER` explicitly for its child processes. For manual Compose commands in a new terminal, set it to the project venv's provider executable as shown above. To stop the sandbox without deleting its database volume:

```powershell
podman compose --project-name behave-payment-sandbox --env-file payment_api\.env.sandbox --file compose.yaml down
```

To reset only the isolated sandbox database, add `--volumes` to `down`. This deletes the sandbox's named PostgreSQL volume and must not be used against another Compose project. The project owner must independently run Podman Compose, the workload and tests before accepting Stage 1A; see [the stage roadmap](docs/implementation-roadmap.md).

Do not run `npm ci` while this project's Vite server is running. Windows can lock the Tailwind/Rolldown native modules; stop the project server with Ctrl+C before reinstalling dependencies. Do not stop unrelated Node processes or delete the lockfile.

## Demo Boundaries

- Initial access uses a local Incident Manager persona. The profile menu switches demo roles. These are not real organizational identities.
- Records and audit events persist in SQLite, under the default `data` directory. The backend seeds a new empty demo database automatically.
- Workflow coordination, test replay, deployment, rollback and recovery verification are explicitly synthetic. No repository, test runner, scanner or production infrastructure is executed.
- Real manual incident/evidence entry, backend permission checks, validation, redaction and persisted review decisions work locally. Manually entered test outcomes are not independently executed or verified by this platform.
- The application is single-workspace, not tenant-isolated. Do not put production secrets, restricted records or unnecessary personal data in the demo.
- Pattern-based redaction is not comprehensive DLP or malware scanning. The local database is not tamper-proof storage. Declared retention is not an automated deletion policy.

For handoff, include source, public assets, configuration examples, dependency manifests and the npm lockfile. Reinstall dependencies on the receiving computer; do not transfer the virtual environment or `node_modules`. Exclude real environment files, credentials, generated reports and database contents unless explicitly authorized. To transfer approved demo state, stop the backend before copying the database. Backup/restore and migration procedures have not been production-certified.

## Optional Foundry Assessment

Provider calls are read-only assessments, not automatic approvals or execution. Configure an actual authorized project endpoint, deployment and managed identity/Azure CLI identity using the existing settings in [.env.example](.env.example). No live cloud resources were connected during this upgrade.

`AGENTICA_AI_ALLOWED_CLASSIFICATIONS` defaults to `[]`: provider data access is denied. After organizational approval, use a JSON list such as `["Internal"]` for the permitted data categories. Public, Internal and Confidential require explicit allowlisting; Restricted is always blocked until the necessary policy controls exist. User consent alone does not bypass this backend check.

Evidence reliability (`classification`: Observed/Inferred/Unverified) is separate from sensitivity (`dataClassification`: Public/Internal/Confidential/Restricted). New incident/evidence records default to Internal; legacy records without sensitivity metadata are handled as Internal for outbound policy checks. Unknown sensitivity values fail closed as Restricted. Raw original uploads are not retained; new evidence records include collector, ingestion time, byte count, original/derivative hashes and a database derivative reference. This is not an object-storage implementation or a classification-based read-access system.

Production mode requires PostgreSQL plus the Entra tenant and audience settings. Signed identity tokens must match the configured issuer, audience and tenant and contain an assigned application role. **Those checks do not make the application production-ready:** tenant-scoped records/queries, migrations, object storage, stronger audit governance and operational adapters are still required. Keep `AGENTICA_MODE=demo` for local use. Existing `AGENTICA_*` configuration names remain unchanged for compatibility.

## Verification

```powershell
npm run typecheck
npm run lint
npm run test:e2e
```

Run backend tests against isolated storage, including the module-level application import:

```powershell
& {
  $previousDatabase = $env:DATABASE_URL
  $previousMode = $env:AGENTICA_MODE
  try {
    $env:DATABASE_URL = 'sqlite:///:memory:'
    $env:AGENTICA_MODE = 'demo'
    & .\.venv\Scripts\python.exe -m pytest backend/tests -q
  } finally {
    $env:DATABASE_URL = $previousDatabase
    $env:AGENTICA_MODE = $previousMode
  }
}
```

Browser tests build the frontend and own isolated servers on ports 15173 and 18001, with a fresh in-memory backend. Leave these ports free. On Windows they use installed Microsoft Edge and the project virtual environment; they do not mutate the user-facing demo database. These are development tests, not an implemented in-app Resilience Lab.

Final verification for this increment: **48 backend tests passed; 8 browser tests passed; build, typecheck and lint passed.** This does not certify the unimplemented enterprise acceptance criteria listed in the [phase report](docs/upgrade-audit.md).
