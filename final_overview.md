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
| **Logo** | "BEHAVE KYNDRYL" text replaced by a Bridge-style lowercase wordmark, **behave kyndryl**: **behave** in grey and **kyndryl** in red, followed by a "Command Centre" label after a divider. |
| **Search fields** | Fixed a double border: a second box was drawn inside every search field. |
| **AI War Room** | The 3D scene was replaced by an animated **agent command view** in the site's light theme: the Orchestrator hub, four lifecycle squads, live squad dashboards, real project items and a human-approval gate. |
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
| Frontend | React 19, TypeScript 7, Vite 8, Tailwind CSS 4, React Router 7, TanStack Query and Table, Radix UI, Recharts, XY Flow; Roboto and IBM Plex Mono fonts | `src/` |
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
  components/war-room/  Agent command view (AgentCommandView.tsx, agent-command.css, war-room-3d.css)
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
| AI War Room | Agent command view, 2D list and XY Flow service graph |
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
| Logo | `BrandMark` component in `src/components/ui.tsx`: **behave** in grey followed by **kyndryl** in red (`#ff462d`), then a divider and "Command Centre" |
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

## 9. Change details: AI War Room agent command view

The War Room's workforce panel was redesigned from scratch, inspired by a reference video of a mission-control style AI dashboard. It was adapted to this project's purpose rather than copied: no third-party apps, names or icons, only incident-response concepts and real data from the backend.

**Files:**
- `src/components/war-room/AgentCommandView.tsx` and `agent-command.css` are new.
- `src/pages/WarRoom.tsx` wires in the new view.
- `war-room-3d.css` gained the full-width layout rules.
- The old three.js scene (`AgentWorkforce3D.tsx`) was removed, and the unused `three`, `@react-three/fiber` and `@react-three/drei` packages were uninstalled.

### Layout

```
   [items]  [ Investigate card ]  (Investigate)              (Diagnose)  [ Diagnose card ]  [items]
                                          \                    /
                                           [  ORCHESTRATOR  ]
                                          /   (human approval) \
   [items]  [ Govern card ]   (Govern & Release)       (Remediate & Validate)  [ Remediate card ]  [items]

                          [ Search agents, evidence or gates… ]
```

- **Theme:** matches the rest of the site (Kyndryl Bridge style): a light dotted canvas with a soft teal glow, white cards with a coloured top edge, teal controls and a teal search focus. The Orchestrator keeps its Kyndryl red.
- **Full width:** in Workforce mode the panel spans the full width of the page. Incident context and Findings/Agent inspector move below it. XY Flow mode keeps the original three-column layout.
- **Orchestrator hub:** an extruded hexagon tile in Kyndryl red, in the centre. Its caption shows the real workflow state, for example `AWAITING INPUT`, `ORCHESTRATING · Investigation` or `WORKFLOW COMPLETED`.
- **Four lifecycle squads,** read clockwise, each with its own colour and icon:

| Squad | Colour | Specialists | Lifecycle stages |
|---|---|---|---|
| Investigate | Blue (`#1192e8`) | Intake, log analysis, observability, repository | Detection, Investigation |
| Diagnose | Violet (`#8a3ffc`) | Knowledge retrieval, root-cause analysis | Root cause |
| Remediate & Validate | Amber (`#d2a106`) | Remediation, testing, security, validation | Proposal, Validation |
| Govern & Release | Green (`#24a148`) | Change risk, release coordination, incident summary | Approval, Deployment, Recovery, Closure |

- **Squad dashboard cards:** each squad has a card listing its specialists with status dots, a progress bar, a completed count and a state tag (Upcoming, Active or Done) derived from the incident's current stage. Clicking a specialist opens it in the Agent inspector.
- **Item fans:** the round icons on the outer edges come from real backend data:
  - Investigate: linked **evidence records** (log, metric, trace…). Clicking one opens the evidence.
  - Diagnose: **hypotheses**, with confidence.
  - Remediate & Validate: the change's **quality gates** (passed or failed).
  - Govern & Release: **human approval, deployment, recovery and closure** status.
- **Human approval gate:** a badge on the line to Govern & Release. It shows **locked** (amber) until a separate human approves the change, then **open** (green). This reflects the project's human-governed objective.
- **Connectors:** dotted curves from the hub to each squad, and from each card to its items. The line to the active squad animates while a workflow runs.
- **Animations:**
  - **Intro:** the hub appears, squads fly in from the edges with a slight spin and blur, each connector *draws itself*, cards slide in, progress bars grow, and item icons pop in one by one. **Replay intro** plays it again.
  - **Data packets:** dots travel continuously from the hub to every squad, and from each item icon to its card. They move faster and larger toward the active squad, and slower and grey toward upcoming ones.
  - **Hub:** a heartbeat pulse, expanding ripples (faster while a workflow runs), and a dashed orbit ring with a travelling dot.
  - **Squads:** the hexagon tiles float gently out of step with each other. The active squad has a ripple ring, a glowing "Active" tag and a shimmering progress bar. The connector ports blink.
  - **Live states:** status dots of running or waiting agents ping. Waiting items (such as a pending approval) pulse, and the locked approval gate gives an occasional lock wiggle.
  - **Interaction:**
    - cards lift on hover, and agent rows slide slightly;
    - the selected squad glows and its connector thickens;
    - toolbar icons spin on hover;
    - the "<agent> details" button nudges downward.
  - **Background:** a slow drifting glow across the canvas.
  - **Reduced motion:** all motion is switched off when the user's system asks for it.
- **Command bar:** "Search agents, evidence or gates…" dims everything that doesn't match, and Enter selects the first matching agent. This is a real search, not a fake chat; the footer says "Recorded task states only · no live agent execution".
- **Other controls:**
  - a status filter;
  - a **2D list** view;
  - **Fullscreen**;
  - a "<agent> details" button that scrolls to the inspector.
- **Narrow screens** (panel under 900 px wide, including tablets and phones): the canvas switches to a stacked layout, with the hub on top and each squad's tile next to its card and items as a row of icons.

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
- the War Room command view: hub, four squads, 13 specialists, the human approval gate, agent selection with evidence, search and status filter, and the 2D list
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
| 2 Workforce view and replay | WARN | The agent command view replaces the 3D scene; full acceptance (dynamic selection, replay) depends on 1B |
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
