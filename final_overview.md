# BEHAVE KYNDRYL — Final Project Overview

*Updated 2026-11-11. Covers the project as it stands, plus every change made in this round of work. Tagline: "Your Problem. Their Mission."*

---

## 1. What the project is

BEHAVE KYNDRYL is a hackathon demonstration of an **agentic AI incident-response platform**. It shows how a team of 14 specialist AI "agents" could:

1. take an operational incident,
2. investigate it using evidence,
3. propose a fix,
4. validate the fix,
5. send it to a **separate human** for approval,
6. deploy it or roll it back,
7. verify that the service recovered, then close the incident with a full audit trail.

The project is open about what is real and what isn't:

- **Real and persisted locally:** the incident lifecycle, role-based permissions, approvals, evidence handling and the audit trail.
- **Synthetic or seeded:** the agents' investigation work, test runs and deployments. The one exception is the isolated Payment API sandbox.

All UI and API labels use a fixed set of truthfulness terms: `REAL`, `MEASURED`, `SIMULATED`, `SYNTHETIC`, `ESTIMATED`, `AI-GENERATED`, `DETERMINISTIC` and `NOT CONFIGURED`.

---

## 2. Summary of changes in this round

| Area | What changed |
|---|---|
| **Visual theme** | The whole UI was restyled to match the Kyndryl Bridge developer console: white header, teal accent, dark-teal page banners, light grey page background, white cards and the Roboto font. |
| **Logo** | "BEHAVE KYNDRYL" text replaced by a Bridge-style lowercase wordmark: **kyndryl** in red and **behave** in grey, followed by a "Command Centre" label after a divider. |
| **Search fields** | Fixed a double border: a second box was drawn inside every search field. |
| **AI War Room (3D)** | The dark sci-fi scene was rebuilt as a clean, light, professional view that matches the theme. |
| **Tests** | Browser tests updated for the new header, wordmark and War Room background. All suites pass. |
| **Developer setup** | Dependencies reinstalled, `.env` created, a working `.venv` created for the backend and browser tests, and the Playwright Chromium browser installed. |

Details of each change are in sections 7–9.

---

## 3. High-level architecture

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
| Frontend | React 19, TypeScript 7, Vite 8, Tailwind CSS 4, React Router 7, TanStack Query and Table, Radix UI, Recharts, XY Flow, React Three Fiber/Drei (3D); Roboto and IBM Plex Mono fonts | `src/` |
| Theme | Kyndryl Bridge-style override layer | `src/theme-bridge.css` |
| Backend API | FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2, PyJWT, azure-identity, azure-ai-projects, openai | `backend/` |
| Sandbox service | FastAPI and SQLAlchemy service on PostgreSQL 17, containerised with Podman | `payment_api/`, `compose.yaml`, `Containerfile` |
| Tests | pytest (backend and sandbox), Playwright (browser end-to-end) | `backend/tests/`, `payment_api/tests/`, `tests/` |
| Tooling | oxlint, Prettier, `tsc -b` | `package.json` |

---

## 4. Repository layout

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
  tests/              pytest suites
payment_api/          Isolated "broken" Payment API used as the real incident target
scripts/stage1a_acceptance.py   Three-cycle sandbox acceptance runner
src/
  App.tsx             Router + shell
  main.tsx            Entry point; loads fonts, styles.css and theme-bridge.css
  styles.css          Base styles and layout
  theme-bridge.css    Kyndryl Bridge theme layer (new)
  context.tsx         Session, workspace snapshot, polling, role switching
  lib/                API client and formatting helpers
  components/         Shell, forms, incident widgets, UI kit (incl. BrandMark)
  components/war-room/  3D agent workforce (AgentWorkforce3D.tsx, war-room-3d.css)
  pages/              14 modules
tests/                Playwright specs + global setup
docs/                 architecture.md, agent-mapping.md, implementation-roadmap.md, upgrade-audit.md
final_overview.md     This document
initial_overview.md   Earlier overview written at the start of this work
```

---

## 5. Backend

### 5.1 API (`backend/app.py`, prefix `/api/v1`)

| Method and path | Purpose |
|---|---|
| `GET /health` | Database readiness, mode, execution type |
| `POST /auth/demo`, `GET /auth/session`, `POST /auth/logout` | Demo persona sign-in and session |
| `GET /workspace` | The full workspace snapshot the UI renders |
| `POST /incidents`, `POST /incidents/import` | Create or bulk-import incidents |
| `POST /incidents/{id}/actions` | Run one of the 17 governed lifecycle actions |
| `POST /incidents/{id}/assessment` | Optional AI provider assessment (read-only) |
| `POST /incidents/{id}/evidence`, `.../evidence/upload` | Add evidence (validated and redacted) |
| `POST /incidents/{id}/tests` | Record manually entered test results |
| `PATCH /security/{finding_id}` | Review a security finding |
| `POST /knowledge`, `POST /knowledge/{id}/review` | Knowledge and runbook records |
| `GET /admin/access`, `PUT /admin/policy` | Access overview and workspace policy |
| `POST /repositories/analyses` | Record a repository analysis |
| `POST /reports/export` | Export reports |

Interactive docs: `http://127.0.0.1:8000/api/docs`.

### 5.2 Incident lifecycle (`backend/workflow.py`)

Every action is permission-checked against the incident's environment and is idempotent.

| Action | Main rule |
|---|---|
| `start-investigation` | Needs at least one evidence record; starts the background demo workflow |
| `pause` / `resume` / `cancel` / `retry` | State-guarded; retries limited by `maxRetries` |
| `generate-fix` | Only after root cause is identified |
| `run-validation` | Records a **synthetic** validation replay |
| `request-approval` | Quality gates must pass: build/regression, security, rollback readiness, evidence provenance |
| `approve` / `reject` | **Separation of duties**: you cannot decide your own request. Approval needs the confirmation word `APPROVE`; a rejection needs a written reason |
| `deploy` / `rollback` | Needs a current approval from a different person, and the target environment typed as confirmation |
| `verify`, `close`, `reopen`, `assign`, `escalate` | Recovery verification, closure and incident management |

Incident statuses move roughly like this: `Open → Investigating → Root Cause Identified → Fix Proposed → Testing → Awaiting Approval → Approved → Deploying → Monitoring → Resolved → Closed`.

### 5.3 Roles and demo personas

| Role | Persona | Key permissions |
|---|---|---|
| Incident Manager (default) | Alex Morgan | Full operational lifecycle except approval decisions |
| Change Approver | Sam Rivera | Approval decisions only |
| Administrator | Taylor Chen | Everything |
| SRE / Operator | James Wilson | Same as Incident Manager |
| Developer | Maya Patel | Create, investigate, validate, request approval (Development and Staging only) |
| QA Engineer | Olivia Brooks | Create, evidence, validation |
| Security Analyst | Noah Kim | Evidence and security review |
| Viewer | Jordan Lee | Read and export |

You switch personas from the profile menu. A typical demo uses the Incident Manager to request approval and the Change Approver to approve it.

### 5.4 Persistence, governance and AI provider

- **Storage:** SQLAlchemy tables `workspace`, `entities`, `audit_events` and `auth_sessions`. The default database is SQLite at `./data/agentica.db`, seeded automatically on first start.
- **Redaction:** passwords, tokens, API keys, private keys, JWTs and credentials in URLs are redacted from evidence.
- **Two labels on each record:**
  - *Reliability*: Observed, Inferred or Unverified.
  - *Sensitivity*: Public, Internal, Confidential or Restricted.
- **AI provider:** an optional Microsoft Foundry read-only assessment. It is effectively off by default, because `AGENTICA_AI_ALLOWED_CLASSIFICATIONS=[]` allows no data to be sent out.

---

## 6. The 14 specialist agents and 14 modules

**Agents** (`backend/seed.py`): orchestrator, intake, logs, observability, repository, knowledge, root-cause, remediation, testing, security, validation, risk, release and summary. These are logical roles with static metadata and seeded tasks.

**Modules** (`src/pages/`):

| Module | Purpose |
|---|---|
| Command centre (`/`) | Dashboard: KPIs, active incidents, health |
| Issues & incidents | Incident list, detail, evidence, lifecycle actions |
| AI War Room | 3D agent workforce, 2D list and XY Flow service graph |
| Root cause analysis | Hypotheses and investigations |
| Agent orchestration | The specialist roles and their task status |
| Project & repositories | Repository analyses |
| Testing & validation | Test runs and validation results |
| Security centre | Findings and reviews |
| Change & release | Changes, quality gates, approvals, deploy and rollback |
| Observability & logs | Metrics and charts |
| Knowledge centre | Runbooks and knowledge review |
| Reports & analytics | Report generation and export |
| Audit trail | Audit event log |
| Administration | Access, policy, configuration |

---

## 7. Change details: Kyndryl Bridge theme and logo

Most of the restyle lives in one override file, **`src/theme-bridge.css`**, which loads after `styles.css`. It changes colours, fonts and surfaces and leaves the existing layout rules alone. The exception is the main content padding, which it sets through shared variables so the banners can run edge to edge.

| Element | New look |
|---|---|
| Header | White with a thin bottom border and soft shadow; always-visible hamburger menu; dark grey icons; red notification badge |
| Logo | `BrandMark` component in `src/components/ui.tsx`: **kyndryl** in red (`#ff462d`) followed by **behave** in grey, then a divider and "Command Centre" |
| Accent colour | Teal `#29707a` for primary buttons, the active sidebar item, active tabs, links, focus rings and progress bars |
| Red | Kept only for the wordmark and for critical or error states |
| Page headers | Full-width dark-teal gradient banner with a dotted texture, light-weight white title, and white or teal buttons |
| Surfaces | Light grey page (`#f8f8f8`), white cards with a `#e3e3e3` border and 4 px corners |
| Tabs | Grey tabs with a teal underline on the active tab |
| Sidebar | White; dark grey items; active item in teal with a teal left bar |
| Sign-in screen | White card on the teal gradient background |
| Font | Roboto (`@fontsource/roboto`) replaces Manrope; IBM Plex Mono is still used for code |

**Where the wordmark appears:** the header, and the sign-in, loading and error screens. The browser tab title and footer still read "BEHAVE KYNDRYL".

**Files touched:**
- `src/main.tsx`: font and theme imports.
- `src/components/ui.tsx`: new `BrandMark` component.
- `src/components/Shell.tsx`, `src/context.tsx`, `src/App.tsx`: use the wordmark.
- `package.json`: added `@fontsource/roboto`.

**Responsive behaviour:** on phones the header tightens its spacing and shrinks the wordmark so every control stays on screen. The "Command Centre" label hides below 1100 px.

**To undo:** remove the `theme-bridge.css` and Roboto imports from `src/main.tsx`, restore the Manrope imports, and put back the previous brand markup.

---

## 8. Change details: search field fix

The generic input style applied a border to every text input. It was more specific than the search field's own rule, so each search field showed a second box inside its outer border. `theme-bridge.css` now removes the inner border with a more specific selector, and gives the field a teal focus state.

This affects:
- the table search fields (`.search-input`),
- the workspace search dialog,
- the War Room graph search (`.graph-search`).

---

## 9. Change details: AI War Room 3D workforce

Files: `src/components/war-room/AgentWorkforce3D.tsx` and `src/components/war-room/war-room-3d.css`.

| Aspect | Before | After |
|---|---|---|
| Scene | Near-black background, glowing grid, floating particles, fog | Light background (`#f4f6f6`), soft circular floor with faint guide rings |
| Orchestrator | Spiky metallic polyhedron with red rings | Teal hub on a white plinth, with a thin Kyndryl-red ring as the brand accent |
| Specialists | Mixed polyhedra at different heights | 13 identical white "pucks" evenly spaced on one ring, each with a status-coloured band and a soft contact shadow |
| Status colours | Red for running | Teal running, green completed, amber queued/waiting, red failed, grey idle |
| Links | Many red and grey lines | Faint spokes from the hub; dependency lines turn teal, with a moving dot, only while an agent is running |
| Labels | Dark monospace boxes that overlapped | White cards with a status-coloured left edge and status dot; back-of-ring labels staggered so they don't collide |
| Evidence | Floating diamonds with always-on ID tags | Small markers beside each agent; ID chips appear only for the selected agent |
| Selection | White glow | Teal ring on the floor, a slight lift, and the camera eases toward the agent |
| Camera | Low side angle | Higher, more top-down angle; pulls back on narrow panels so the whole ring fits |
| Toolbar | Dark | White, with a teal segmented control and standard selects and buttons |
| Overlays | Dark floating boxes | Orchestrator status card at top-left; counts and snapshot note in a white footer strip |
| 2D list | Dark cards | White cards with a status-coloured edge and status dot |
| Narrow panels (≤ 640 px) | Overlapping labels | Name-only compact labels, and a two-row footer |

The XY Flow service graph already matched the light theme and was left as is. All existing behaviour is unchanged: filters, labels toggle, focus, reset, fullscreen, the 2D fallback when WebGL is unavailable, and opening agent evidence.

---

## 10. Payment API sandbox (Stage 1A)

This is a real, deliberately faulty service that gives the agents a genuine incident to resolve.

- **Release v3.8.1:** DB pool size **5**, so it times out under concurrent load. It adds `GET /payments/summary`.
- **Previous release:** pool size **20**, without that endpoint.
- **Adapter:** `backend/payment_sandbox.py` may only change the release and pool size of the fixed `behave-payment-sandbox` project.
- **Status: NOT RUN.** It needs Podman and `podman-compose`, which are not part of the local setup used here, and the original build was blocked by a registry certificate error.

---

## 11. Configuration (`.env`)

`.env` was created from `.env.example`. Key settings:

| Key | Default | Meaning |
|---|---|---|
| `AGENTICA_MODE` | `demo` | `demo` or `production` |
| `DATABASE_URL` | `sqlite:///./data/agentica.db` | Main app database |
| `AGENTICA_ALLOWED_ORIGINS` | `127.0.0.1:5173, localhost:5173` | CORS |
| `AGENTICA_DEMO_STEP_SECONDS` | `1.2` | Speed of the synthetic workflow |
| `AGENTICA_AI_ALLOWED_CLASSIFICATIONS` | `[]` | Data classes allowed to leave for the AI provider |
| `AZURE_*`, `AGENTICA_AUTH_AUDIENCE` | empty | Foundry provider and Entra auth (production) |
| `PAYMENT_*` | ports 18080/18081/15432, pool 5 | Sandbox settings (dev-only password) |

---

## 12. Running the project

**One-time setup:**

```
npm ci
cp .env.example .env          # or copy it manually
```

Then create a Python virtual environment in `.venv` and install `backend/requirements.txt` into it. The browser tests start the backend from `.venv`.

**Start the app** in two terminals, using your Python interpreter (`python`, `python3` or `py`, depending on your system):

```
python -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
npm run dev -- --host 127.0.0.1 --port 5173
```

- App: http://127.0.0.1:5173/
- API docs: http://127.0.0.1:8000/api/docs
- Health: http://127.0.0.1:8000/api/v1/health

**Notes:**
- `.venv-windows` holds the Windows-specific virtual environment that came with the project. `.venv` is the active one.
- The README contains step-by-step PowerShell instructions for Windows.

---

## 13. Verification (2026-11-11, after all changes)

| Check | Command | Result |
|---|---|---|
| Backend tests | `pytest backend/tests` (in-memory DB) | **60 passed** |
| Sandbox tests | `pytest payment_api/tests` | **8 passed** |
| Typecheck | `npm run typecheck` | **Passed** |
| Lint | `npm run lint` | **Passed** |
| Browser tests | `npm run test:e2e` | **12 passed** |

**What the browser tests cover:**
- all 14 modules and the Kyndryl Bridge theme (white header, red wordmark)
- the service graph
- the War Room in 3D, with agent selection and evidence, and in the 2D fallback
- incident intake with redacted evidence upload
- the Payment API sandbox proposal
- the full checkout workflow, including separate-person approval
- Viewer permissions
- search, filters and export
- recovery from an API failure
- the mobile sign-in wordmark
- desktop, tablet and mobile layouts with no horizontal overflow

The Python tests ran against an in-memory database, so the demo data in `data/agentica.db` was not touched. The browser tests use their own temporary servers on ports 15173 and 18001.

---

## 14. Roadmap and status

| Stage | Status | Scope |
|---|---|---|
| 0 Repository audit | PASS | Audit, architecture and mapping docs |
| 1A Payment API sandbox | WARN | Code complete; runtime acceptance NOT RUN |
| 1B Agents, evidence, events, security | NOT RUN | Planner that picks agents from the incident inputs, real read-only tools, durable events, approval bound to the exact action |
| 2 3D workforce and replay | WARN | 3D workforce UI exists and is now restyled; full acceptance depends on 1B |
| 3 Golden scenario | NOT RUN | Full end-to-end Payment API recovery |
| 4 Business value and benchmark | NOT RUN | Human baseline vs BEHAVE |
| Enterprise expansion | NOT STARTED | Tenant isolation, migrations, object storage |

---

## 15. Known limitations

- Investigation, testing, scanning and deployment are synthetic except in the Payment API sandbox.
- There is a single workspace with no tenant isolation, so don't use real secrets or production data.
- Redaction is pattern-based, not full DLP. There's no malware scanning, and the local database isn't tamper-proof.
- There are no database migrations, no object storage and no durable event stream.
- The AI provider isn't connected or verified.
- The wordmark is an approximation built from text in the Roboto font. It is not the official Kyndryl logo artwork.
- The production build warns that one JavaScript bundle is larger than 500 kB. This is a performance hint, not an error.

---

## 16. Suggested reading order

1. `README.md`, then `docs/architecture.md` and `docs/implementation-roadmap.md`
2. `backend/domain.py`, then `backend/workflow.py`, then `backend/app.py`
3. `backend/seed.py` for the demo data
4. `src/App.tsx`, `src/context.tsx`, `src/theme-bridge.css`
5. `src/pages/WarRoom.tsx` and `src/components/war-room/AgentWorkforce3D.tsx`
6. `payment_api/app.py` and `backend/payment_sandbox.py`
