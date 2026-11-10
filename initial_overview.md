# BEHAVE KYNDRYL — Initial Project Overview

*Prepared 2026-11-11 from the code and documentation in this folder. Tagline: "Your Problem. Their Mission."*

## 1. What the project is

BEHAVE KYNDRYL is a hackathon demonstration of an **agentic AI incident-response platform**. It shows how a team of 14 specialist AI "agents" could:

1. take an operational incident,
2. investigate it using evidence,
3. propose a fix,
4. validate the fix,
5. send it to a **separate human** for approval,
6. deploy it or roll it back,
7. verify that the service recovered, then close the incident with a full audit trail.

The documentation is unusually honest about what is real and what isn't. Today, the **lifecycle, permissions, approvals, evidence handling and audit trail are real** and persist locally. The **agent investigation work, test runs and deployments are synthetic or seeded**, apart from one isolated Payment API sandbox. Every UI and API label follows a fixed set of truthfulness terms: `REAL`, `MEASURED`, `SIMULATED`, `SYNTHETIC`, `ESTIMATED`, `AI-GENERATED`, `DETERMINISTIC`, `NOT CONFIGURED`.

## 2. High-level architecture

```
 Operator (browser)
      │
      ▼
 React 19 + TypeScript + Vite  (port 5173)
      │  REST: workspace snapshot + governed actions (React Query polling)
      ▼
 FastAPI backend  (port 8000, /api/v1)
      ├─ Authentication / role-based authorization (demo personas or Entra JWT)
      ├─ workflow.py  ── the only engine for incident lifecycle rules (17 actions)
      ├─ Evidence + data governance (validation, redaction, sensitivity)
      ├─ Optional Microsoft Foundry read-only assessment (off by default)
      ├─ Payment sandbox adapter ──► Podman Compose ──► Payment API (18080) + PostgreSQL (15432)
      └─ SQLAlchemy store (SQLite in demo; PostgreSQL required in production mode)
```

| Layer | Technology | Location |
|---|---|---|
| Frontend | Kyndryl Bridge-style theme (Roboto font, teal accent), React 19, TypeScript 7, Vite 8, Tailwind CSS 4, React Router 7, TanStack Query and Table, Radix UI, Recharts, XY Flow, React Three Fiber/Drei (3D) | `src/` |
| Backend API | FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2, PyJWT, azure-identity, azure-ai-projects, openai | `backend/` |
| Sandbox service | FastAPI and SQLAlchemy service on PostgreSQL 17, containerised with Podman | `payment_api/`, `compose.yaml`, `Containerfile` |
| Tests | pytest (backend and sandbox), Playwright (browser end-to-end) | `backend/tests/`, `payment_api/tests/`, `tests/` |
| Tooling | oxlint, Prettier, `tsc -b` | `package.json` |

Size: about 2,000 lines of Python in the backend, about 370 in the sandbox, and about 13,000 lines of TSX/TS in the frontend.

## 3. Repository layout

```
backend/              FastAPI application (main product API)
  app.py              Routes, auth/session handling, audit helper, app factory
  workflow.py         Authoritative incident lifecycle: 17 actions + background demo workflow
  domain.py           Settings, Pydantic contracts, redaction, roles/permissions, personas
  store.py            SQLAlchemy persistence (entities, workspace, audit_events, auth_sessions)
  seed.py             14 specialist agent roles + seeded demo workspace data
  data_governance.py  Evidence validation, sensitivity and provenance metadata
  providers.py        Optional Microsoft Foundry read-only assessment provider
  payment_sandbox.py  Allowlisted control adapter for the Payment API sandbox
  tests/              pytest suites (domain, workflow, providers, sandbox)
payment_api/          Isolated "broken" Payment API used as the real incident target
  app.py              /health, /control/config, /metrics, /payments/summary (v3.8.1 only)
  workload.py         50-request concurrent load generator
  tests/
scripts/stage1a_acceptance.py   Three-cycle sandbox acceptance runner
src/                  React frontend
  App.tsx             Router + shell, lazy-loaded pages
  context.tsx         Session, workspace snapshot, polling, role switching
  lib/api.ts          Fetch wrapper for /api/v1
  lib/format.ts       Formatting helpers
  components/         Shell, forms, incident widgets, UI kit, 3D war-room workforce
  pages/              14 modules (see §6)
tests/                Playwright specs + global setup (isolated ports 15173/18001)
docs/                 architecture.md, agent-mapping.md, implementation-roadmap.md, upgrade-audit.md
compose.yaml, Containerfile, requirements-podman.txt   Sandbox container setup
.env.example          All configuration keys (copied to .env)
```

## 4. Backend in detail

### 4.1 API surface (`backend/app.py`, prefix `/api/v1`)

| Method and path | Purpose |
|---|---|
| `GET /health` | Database readiness, mode, execution type |
| `POST /auth/demo`, `GET /auth/session`, `POST /auth/logout` | Demo persona sign-in and session |
| `GET /workspace` | The full workspace snapshot the UI renders |
| `POST /incidents`, `POST /incidents/import` | Create or bulk-import incidents |
| `POST /incidents/{id}/actions` | Run one of the 17 governed lifecycle actions |
| `POST /incidents/{id}/assessment` | Optional AI provider assessment (read-only) |
| `POST /incidents/{id}/evidence`, `.../evidence/upload` | Add evidence as text or an uploaded file (validated and redacted) |
| `POST /incidents/{id}/tests` | Record manually entered test results |
| `PATCH /security/{finding_id}` | Review a security finding |
| `POST /knowledge`, `POST /knowledge/{id}/review` | Add and review knowledge or runbook records |
| `GET /admin/access`, `PUT /admin/policy` | Access overview and workspace policy |
| `POST /repositories/analyses` | Record a repository analysis |
| `POST /reports/export` | Export reports |

Interactive docs: `http://127.0.0.1:8000/api/docs`.

### 4.2 Incident lifecycle (`backend/workflow.py`)

`workflow.py` is the **only** place lifecycle rules live. Every action is permission-checked against the incident's environment and is idempotent: reusing an idempotency key with a different request returns 409.

| Action | Permission | Main rule |
|---|---|---|
| `start-investigation` | `workflow:run` | Needs at least one evidence record; queues agent tasks and starts the background demo workflow |
| `pause` / `resume` / `cancel` / `retry` | `workflow:run` | State-guarded; retries limited by the policy's `maxRetries` |
| `generate-fix` | `workflow:run` | Only after root cause is identified; creates a proposed change |
| `run-validation` | `validation:run` | Records a **synthetic** validation replay (48 passed) as evidence |
| `request-approval` | `approval:request` | Quality gates must pass (build/regression, security, rollback readiness, evidence provenance) |
| `approve` / `reject` | `approval:decide` | **Separation of duties**: you cannot decide your own request. Approval needs the confirmation word `APPROVE`; a rejection needs a reason of at least 10 characters. For the sandbox, the action payload is hashed so it can't change after approval |
| `deploy` / `rollback` | `change:deploy` | Needs a current approval from a different identity, and the target environment typed as confirmation. Sandbox incidents call the real adapter; all others are simulated |
| `verify` | `recovery:record` | Needs a deployed change in Monitoring state |
| `close` / `reopen` | `incident:close` / `incident:update` | Closing needs verified recovery and an outcome of at least 12 characters |
| `assign` / `escalate` | `incident:update` | Commander assignment or escalation with a reason |

Incident statuses move roughly like this: `Open → Investigating → Root Cause Identified → Fix Proposed → Testing → Awaiting Approval → Approved → Deploying → Monitoring → Resolved → Closed`.

The background `run_demo_workflow` moves the seeded agent tasks through their phases at `AGENTICA_DEMO_STEP_SECONDS` (default 1.2 s) per step.

### 4.3 Roles and demo personas (`backend/domain.py`)

| Role | Demo persona | Key permissions |
|---|---|---|
| Incident Manager (default) | Alex Morgan | Full operational lifecycle except approval decisions |
| Change Approver | Sam Rivera | `approval:decide` only |
| Administrator | Taylor Chen | Everything, including `admin:write` |
| SRE / Operator | James Wilson | Same as Incident Manager |
| Developer | Maya Patel | Create, investigate, validate, request approval (Development and Staging only) |
| QA Engineer | Olivia Brooks | Create, evidence, validation (Development and Staging only) |
| Security Analyst | Noah Kim | Evidence + `security:review` |
| Viewer | Jordan Lee | Read and export |

You switch personas from the profile menu in the UI. A typical demo uses the **Incident Manager** to request approval and the **Change Approver** to approve it.

In production mode (`AGENTICA_MODE=production`), the backend instead validates Microsoft Entra JWTs: issuer, audience, tenant and an assigned app role.

### 4.4 Persistence (`backend/store.py`)

SQLAlchemy tables: `workspace`, `entities`, `audit_events` and `auth_sessions`. The workspace is held as JSON and changed with a read-modify-write `mutate()`.

The default database is SQLite at `./data/agentica.db`, seeded automatically on first start. There is no migration system and no tenant isolation.

### 4.5 Data governance

- **Redaction:** sensitive keys (password, token, api key, cookie and so on) are redacted, as are secret patterns: private keys, bearer tokens, GitHub/OpenAI-style keys, AWS keys, JWTs and credentials in URLs.
- **Two separate labels on each record:**
  - *Reliability* (`classification`): Observed, Inferred or Unverified.
  - *Sensitivity* (`dataClassification`): Public, Internal, Confidential or Restricted.
- **Defaults:** new records are Internal. Unknown values fail closed as Restricted.
- **Upload provenance:** the collector, ingestion time, byte count and original and derivative hashes are recorded. Raw uploads aren't kept.
- **Upload limit:** `AGENTICA_MAX_UPLOAD_BYTES`, 2 MB by default.

### 4.6 AI provider (`backend/providers.py`)

This is an optional Microsoft Foundry (Azure AI Projects) **read-only assessment**. It is never an approval or an execution. It is effectively disabled by default because `AGENTICA_AI_ALLOWED_CLASSIFICATIONS=[]`, which means no data may be sent out, and Restricted data is always blocked. No live cloud connection has been verified.

## 5. The 14 specialist agents (`backend/seed.py`)

These are logical roles, not 14 model deployments. They currently have static metadata and seeded tasks.

| # | Role ID | Responsibility |
|---|---|---|
| 1 | `orchestrator` | Plan and coordinate tasks and dependencies |
| 2 | `intake` | Normalise and classify the incident |
| 3 | `logs` | Group recurring exceptions in logs |
| 4 | `observability` | Correlate metrics, traces and dependencies |
| 5 | `repository` | Inspect read-only source and release diffs |
| 6 | `knowledge` | Retrieve approved runbooks and prior resolutions |
| 7 | `root-cause` | Weigh competing hypotheses against evidence |
| 8 | `remediation` | Propose a fix (for example, restore the pool size or roll back the release) |
| 9 | `testing` | Define and run validation |
| 10 | `security` | Review security context and findings |
| 11 | `validation` | Check quality gates and acceptance criteria |
| 12 | `risk` | Assess blast radius and rollback readiness |
| 13 | `release` | Get approval from a separate human, then deploy through the adapter |
| 14 | `summary` | Write the final incident summary with provenance |

## 6. Frontend modules (`src/pages/`)

| Route | Module | Purpose |
|---|---|---|
| `/` | Overview | Command-centre dashboard: KPIs, active incidents, health |
| `/incidents`, `/incidents/:id` | Incidents | Incident list, detail, evidence, lifecycle actions |
| `/war-room` | AI War Room | XY Flow service topology plus a lazy-loaded 3D agent workforce (React Three Fiber) with a 2D accessible fallback |
| `/investigations` | Investigations | Hypotheses, root-cause analysis |
| `/agents` | Agents | The 14 specialist roles and their task status |
| `/repositories` | Repositories | Repository analyses and fixtures |
| `/testing` | Testing | Test runs and validation results |
| `/security` | Security | Findings and reviews |
| `/changes` | Changes | Proposed changes, quality gates, approvals, deploy and rollback |
| `/observability` | Observability | Metrics, charts |
| `/knowledge` | Knowledge | Runbooks and knowledge review |
| `/reports` | Reports | Report generation and export |
| `/audit` | Audit | Immutable-style audit event log |
| `/administration` | Administration | Access, policy, configuration |

### Visual theme (Kyndryl Bridge style, added 2026-11-11)

The UI was restyled to match the Kyndryl Bridge developer console. Most of it lives in one override file, [src/theme-bridge.css](src/theme-bridge.css), which loads after `styles.css`. It changes colours, fonts and surfaces and leaves the existing layout rules alone. The exception is the main content padding, which it now sets through shared variables so the banner can stretch edge to edge.

- **Header:** white with a thin border, instead of the old solid red bar. The hamburger menu is always visible, and the right side holds dark grey icons.
- **Logo:** a new `BrandMark` component in `src/components/ui.tsx` shows a lowercase wordmark: **kyndryl** in red (`#ff462d`) followed by **behave** in grey, with a "Command Centre" label after a divider. It's used in the header and on the sign-in, loading and error screens. The browser tab title and footer still say "BEHAVE KYNDRYL".
- **Accent colour:** teal (`#29707a`) for primary buttons, the active sidebar item, active tabs, focus rings, links and progress bars. Red is kept only for the wordmark and for critical or error states.
- **Page headers:** each page's title area is now a full-width dark teal gradient banner with a dotted texture, light-weight white heading and white or teal buttons.
- **Surfaces:** light grey page background (`#f8f8f8`), white cards with a `#e3e3e3` border and 4 px corners, and grey tabs with a teal underline.
- **Font:** Roboto (`@fontsource/roboto`) replaces Manrope. IBM Plex Mono is still used for code.
- **Search fields:** fixed a double border. The generic input style drew a second box inside each search field (`.search-input`, `.graph-search`); the inner input is now borderless.
- **AI War Room 3D workforce** (`src/components/war-room/AgentWorkforce3D.tsx`, `war-room-3d.css`): rebuilt to match the theme instead of the dark sci-fi look.
  - **Scene:** a light scene (`#f4f6f6`) with a soft circular floor and guide rings. The dark grid, star field, fog glow and spiky shapes are gone.
  - **Orchestrator:** a teal hub on a white plinth, with a thin Kyndryl-red ring as the brand accent.
  - **Specialists:** 13 identical white "pucks", evenly spaced around one ring. Each has a coloured status band:
    - teal: running
    - green: completed
    - amber: queued or waiting
    - red: failed
    - grey: idle
  - **Links:** faint spokes from the hub; teal dependency lines (with a moving dot) only while an agent is running.
  - **Labels:** white cards with a status-coloured left edge and status dot. Labels at the back of the ring are staggered so they don't overlap. On narrow panels (640 px wide or less) they shrink to name-only.
  - **Evidence:** small markers beside each agent. Their ID chips appear only for the selected agent, to reduce clutter.
  - **Camera:** a higher, more top-down default angle. It pulls back on narrower panels so the whole ring fits.
  - **Toolbar and surroundings:** a white toolbar with a teal segmented control and standard selects. The orchestrator badge sits top-left, the counts and snapshot note in a footer strip, and the 2D list uses matching white cards.
- **Tests:** the browser tests now check for the white header, the red "kyndryl" wordmark and the `kyndryl behave` logo text instead of the old red header. The 3D pixel check now measures against the new light stage background.
- **Backup:** the pre-theme `src/`, `tests/`, `index.html`, `package.json` and `package-lock.json` were backed up before the theme change.

To undo the theme, remove the `theme-bridge.css` and Roboto imports from `src/main.tsx`, restore the Manrope imports, and put back the old brand markup.

State comes from one backend workspace snapshot fetched through React Query (`src/context.tsx`). It refreshes every **1.2 s while a workflow is running** and every 30 s otherwise. There are no WebSockets or SSE.

## 7. Payment API sandbox (Stage 1A)

This is a real, deliberately faulty service that gives the agents a genuine incident to resolve.

- **Release v3.8.1:** DB pool size **5** (`max_overflow=0`, `pool_timeout=2s`, each request holds a connection about 0.3 s). Under 15 or more concurrent requests it throws SQLAlchemy `TimeoutError`s. It adds "Feature X", `GET /payments/summary`.
- **Previous release:** pool size **20**, without `/payments/summary`.
- **Endpoints:** `/health`, `/control/config`, `/metrics`, `/payments/summary`.
- **Workload:** `payment_api/workload.py` sends 50 concurrent requests and records measured results.
- **Adapter:** `backend/payment_sandbox.py` exposes only `set_release`, `set_pool_size`, `restart` and `get_active_config`. It only touches the fixed Compose project `behave-payment-sandbox` / service `payment-api` and never falls back to any production deployment.
- **Acceptance:** `scripts/stage1a_acceptance.py` runs the workload at pool 5 (errors expected), restores pool 20, and runs it again (zero errors expected), three times in a row.
- **Status: NOT RUN.** The image build was blocked by a docker.io TLS certificate error, and Podman and `podman-compose` are not part of the local setup used here.

## 8. Configuration (`.env`)

| Key | Default | Meaning |
|---|---|---|
| `AGENTICA_MODE` | `demo` | `demo` or `production` (production needs PostgreSQL and Entra) |
| `DATABASE_URL` | `sqlite:///./data/agentica.db` | Main app database |
| `AGENTICA_ALLOWED_ORIGINS` | `127.0.0.1:5173, localhost:5173` | CORS |
| `AGENTICA_DEMO_STEP_SECONDS` | `1.2` | Speed of the synthetic workflow |
| `AGENTICA_MAX_UPLOAD_BYTES` | `2097152` | Evidence upload limit |
| `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT` | empty | Foundry provider |
| `AGENTICA_AI_ALLOWED_CLASSIFICATIONS` | `[]` | Data classes allowed to leave for the AI provider |
| `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AGENTICA_AUTH_AUDIENCE` | empty | Entra auth for production mode |
| `PAYMENT_*` | ports 18080/18081/15432, pool 5, release 3.8.1 | Sandbox settings (dev-only password) |

## 9. Running locally (verified 2026-11-11)

Verified with Node 26.13, npm 11.20 and Python 3.14.

One-time setup:

```
npm ci                         # reinstall dependencies for your own system
cp .env.example .env           # or copy the file manually
```

Then start the app in two terminals, using your Python interpreter (`python`, `python3` or `py`, depending on your system):

```
python -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
npm run dev -- --host 127.0.0.1 --port 5173
```

- App: http://127.0.0.1:5173/. The health check at `/api/v1/health` returned `{"status":"ok","database":"AVAILABLE","mode":"demo","execution":"synthetic only"}`.
- The README has step-by-step PowerShell instructions for Windows. `.venv-windows` holds the Windows-specific virtual environment that came with the project, and `.venv` is the active one.
- The Playwright Chromium browser is installed.
- Podman and `podman-compose` are needed only for the Payment API sandbox.

### Verification commands

```bash
# with DATABASE_URL=sqlite:///:memory: and AGENTICA_MODE=demo set in the environment
python -m pytest backend/tests -q
python -m pytest payment_api/tests -q
npm run typecheck
npm run lint
npm run test:e2e       # see the note on browser tests below
```

### Test results (2026-11-11)

These were run in a way that changes nothing. The Python tests used an in-memory database, so the demo database `data/agentica.db` was left untouched. The production build was written to a temporary folder, so the project's `dist/` wasn't overwritten.

| Check | Result |
|---|---|
| Backend tests (`backend/tests`) | **60 passed** |
| Payment API sandbox tests (`payment_api/tests`; no PostgreSQL needed) | **8 passed** |
| TypeScript typecheck (`tsc -b`) | **Passed** |
| Lint (`oxlint`) | **Passed** |
| Production build (`vite build`) | **Passed**, with one warning: a bundle chunk is over 500 kB (a performance hint, not an error) |
| Browser end-to-end tests (Playwright, Chromium) | **12 passed** in about 31 s; re-run after the Kyndryl Bridge theme change: **12 passed** (backend and sandbox tests, typecheck and lint also re-run and still pass) |

The README's older figures were 48 backend tests and 8 browser tests. Both suites have grown since then, to 60 backend and 12 browser tests.

**The browser tests cover:**
- all 14 modules loading and the brand colour
- the service graph (interactions, health filters, zoom)
- the War Room in both 3D and the 2D fallback
- incident intake with redacted evidence upload
- the Payment API sandbox recovery proposal
- the full checkout workflow: pause and resume, validation, separate-person approval, and closing
- Viewer permissions and environment confirmation
- search, filters and export
- recovering from an API failure
- mobile sign-in branding
- desktop, tablet and mobile layouts

**Setup needed to run them:**
- A `.venv` virtual environment with `backend/requirements.txt` installed, because the test setup starts the backend from `.venv`.
- The Playwright Chromium browser (`npx playwright install chromium`, about 99 MB).
- The tests run their own temporary servers on ports 15173 and 18001 with an in-memory database, and stop them afterwards. The dev servers on 5173 and 8000 and `data/agentica.db` are not touched.
- `npm run test:e2e` rebuilds `dist/` and regenerates `playwright-report/` and `test-results/`.

To re-run them:

```bash
npm run test:e2e
```

## 10. Roadmap and status (`docs/implementation-roadmap.md`)

| Stage | Status | Scope |
|---|---|---|
| 0 Repository audit | PASS | Audit, architecture, mapping docs |
| 1A Payment API sandbox | WARN | Code complete; runtime acceptance NOT RUN |
| 1B Agents, evidence, events, security | NOT RUN | Planner that picks agents from the incident inputs, real read-only tools (`query_logs`, `query_metrics`, `read_repo_diff`), durable events/replay, approval bound to the exact action |
| 2 3D workforce and replay | WARN | 3D workforce UI exists; full acceptance depends on 1B |
| 3 Golden scenario | NOT RUN | Full end-to-end Payment API recovery, comparing pool restore with rollback in an isolated clone |
| 4 Business value and benchmark | NOT RUN | Human baseline vs BEHAVE on a frozen snapshot |
| Enterprise expansion | NOT STARTED | Tenant isolation, migrations, object storage, generalised intelligence |

**Rules that hold across all stages:** keep `workflow.py` as the only lifecycle engine. Keep all 14 modules, 14 roles and 17 actions. Never fake success or silently fall back to mock data. Approval always comes from a distinct human.

## 11. Known limitations

- Investigation, testing, scanning and deployment are synthetic except in the Payment API sandbox.
- There is a single workspace with no tenant isolation, so don't use real secrets or production data.
- Redaction is pattern-based, not full DLP. There's no malware scanning, and the local database isn't tamper-proof.
- There are no database migrations, no object storage and no durable event stream.
- The AI provider isn't connected or verified.
- Production mode adds real identity checks but isn't production-ready.

## 12. Suggested reading order for new contributors

1. `README.md`, then `docs/architecture.md` and `docs/implementation-roadmap.md`
2. `backend/domain.py` (contracts and roles), then `backend/workflow.py` (lifecycle), then `backend/app.py` (routes)
3. `backend/seed.py` to see the demo data the UI shows
4. `src/App.tsx`, then `src/context.tsx`, then `src/pages/Incidents.tsx` and `src/pages/WarRoom.tsx`
5. `payment_api/app.py` and `backend/payment_sandbox.py` for the real incident scenario
