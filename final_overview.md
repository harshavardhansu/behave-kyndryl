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
| **Realistic demo data** | All 13 incidents now have consistent stories: 44 evidence records, 12 hypotheses, 6 fixes, 9 runbooks, 120 log lines and deployments. **Administration → Reset demo data** (backed up first) restores them for every rehearsal. |
| **Live Payment API sandbox** | The real Payment API now runs **locally with no Docker**. The War Room can start it, fire 50 concurrent requests and record **measured** evidence. Missions on INC-1043 apply the human-approved fix (pool 5 → 20) to the running service and **prove recovery by re-measuring** (8/50 → 0/50 failures). See `DEMO_GUIDE.md`. |
| **Azure OpenAI** | Missions now run on **gpt-4.1-mini** via API key, with a daily call limit, answer cache, usage meter, strict answer formats and automatic labelled fallback to the free simulated planner. Verified with a live mission (about 6 calls, under 1 cent). |
| **Agent missions** | New Orchestrator-led loop: the Orchestrator analyses a ticket, proposes a team of only the specialists it needs, and the team works in steps with human approval at every important decision, iterating with learnings until resolved or escalated. Shown live in the AI War Room. |
| **Tests** | Browser tests updated for the new header, wordmark, War Room and mission flow; 10 new backend mission tests. All suites pass. |
| **Developer setup** | Dependencies reinstalled, `.env` created, a working `.venv` created for the backend and browser tests, and the Playwright Chromium browser installed. |

Details of each change are in sections 7–12.

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

## 10. Agent missions: Orchestrator-led teams with humans in the loop

The core idea of the project: when a ticket comes in, the **Orchestrator** analyses it and forms a **team of only the specialists it needs**. The team works step by step, and **a human approves every important decision**. If the first attempt doesn't resolve the issue, the next iteration builds on what was learned and adds specialists if needed. Everything is visible live in the **AI War Room**.

**Files:**
- `backend/mission.py`: the mission engine (new).
- `backend/app.py`: the mission API endpoints.
- `backend/store.py`: missions are persisted.
- `src/components/war-room/MissionPanel.tsx` and `mission-panel.css`: the mission control panel (new).
- `src/lib/missions.ts`: shared helpers (new).
- `AgentCommandView.tsx`: gained a mission mode.
- `src/pages/WarRoom.tsx`: now driven by the mission team.
- `backend/tests/test_missions.py`: 10 new tests.

### The loop

```
Ticket → Orchestrator analyses → proposes team (chosen + left out, with reasons)
       → ✋ human approves / edits / rejects the team
       → Investigate → Diagnose → ✋ human approves the root cause
       → Remediate & validate → ✋ a DIFFERENT person approves the fix
       → Govern & release → Orchestrator evaluates the outcome
       → ✋ human: confirm resolved / start another iteration / escalate
Next iteration: re-plan with the learnings, keep or add specialists (max 3 iterations, then escalate)
```

| Human gate | Who can decide | Notes |
|---|---|---|
| Approve the team | `workflow:run` (Incident Manager, SRE, Admin) | Tick or untick agents to add or remove them; rejecting needs a reason, and the Orchestrator re-plans |
| Approve the root cause | `workflow:run` | Rejecting ends the iteration and starts the next one with that learning |
| Approve the fix | `approval:decide` (Change Approver, Admin), **not** the person who started the mission | Separation of duties is enforced by the API, not just the UI |
| Confirm the outcome | `workflow:run` | Resolve, iterate (up to 3), or escalate |

Every decision is recorded in the mission and in the **Audit trail**.

### API

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/incidents/{id}/missions` | Start a mission (one open mission per incident; evidence required) |
| `POST /api/v1/missions/{id}/decision` | Decide the pending gate: `gateId`, `decision` (approve, reject, resolve, iterate, escalate), optional `addRoles`, `removeRoles` and `note` |
| `POST /api/v1/missions/{id}/cancel` | Cancel an open mission |
| `POST /api/v1/missions/{id}/resume` | Resume a mission paused by a restart or error |

Missions come back in the normal workspace snapshot (`missions`). While a mission is analysing or working, the frontend refreshes every second.

### The "brain": Azure OpenAI with a free simulated fallback

The logic that plans, works and evaluates is pluggable (`MissionBrain`). The backend chooses it at startup:

| Brain | When it's used | Label shown |
|---|---|---|
| **`FoundryBrain`** (`backend/foundry_brain.py`) | An Azure model is configured **and** the data rule allows the incident's data | **AI-GENERATED / Azure OpenAI gpt-4.1-mini** |
| **`SimulatedBrain`** (`backend/mission.py`) | No AI configured, in all automated tests, and as the automatic fallback | **SIMULATED / rule-based planner** (or **Simulated fallback** with the reason) |

**How the AI brain works:**
- **One call per job:**
  - one call to plan the team;
  - **one call per mission step**, not per agent: all of that step's specialists are answered together;
  - one call to review the outcome.
  That's at most 6 calls per iteration.
- **Strict answer formats:** every answer must match a fixed JSON format (team plan, step findings, outcome).
- **The backend checks every answer:**
  - only the 13 real specialist roles are accepted;
  - evidence IDs that don't exist for the incident are dropped;
  - confidence is clamped to 0–1;
  - left-out specialists are always listed with a reason;
  - a specialist with no finding gets a labelled simulated one.
- **What the AI receives:** only the ticket, trimmed evidence (at most 8 records, 400 characters each), the specialist catalog, the learnings so far, earlier findings and the human decisions. Secrets are redacted first.
- **Safety instructions:** ticket and evidence content is untrusted data and never instructions; the AI cannot approve, deploy or execute anything; it may cite only supplied evidence IDs.
- **Fallback:** if a call can't be made or its answer fails the checks, the free simulated planner answers instead. The mission panel shows **Simulated fallback**, and the Activity feed says why.
- **No blocking:** AI calls run *outside* the database lock, so the app stays responsive while Azure answers.

**Cost controls** (`backend/ai_client.py`):

| Control | Setting | Default |
|---|---|---|
| Daily call limit (UTC); after that, the simulated planner is used | `AGENTICA_AI_DAILY_CALL_LIMIT` | 40 |
| Maximum answer length | `AGENTICA_AI_MAX_OUTPUT_TOKENS` | 900 |
| Answer cache: identical requests are answered from the cache for free (last 150 answers) | — | on |
| Usage meter: calls, tokens and cache hits, shown in the mission panel | — | on |
| Data rule: only allowed data classes are ever sent | `AGENTICA_AI_ALLOWED_CLASSIFICATIONS` | `["Internal"]` for the demo |
| Tests never call Azure (`backend/tests/conftest.py` and `tests/global-setup.ts` blank the AI settings) | — | on |

**Live check (2026-11-11):** one full iteration on INC-1042 used **6 calls, about 5,900 input and 1,000 output tokens**, well under 1 cent.
- **Team:** the AI proposed a lean team of 4 (logs, observability, root cause, remediation).
- **Root cause:** it identified the v2.18.0 change cutting the DB pool from 30 to 10 (EVD-304), with 0.95 confidence.
- **Fix:** it proposed restoring the pool, with a rollback plan.
- **Outcome:** it recommended another iteration adding validation, testing, release and summary.

**Configuration** (in `.env`, which is git-ignored and never pushed):

```
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/openai/v1
AZURE_OPENAI_API_KEY=<key>
AZURE_AI_MODEL_DEPLOYMENT=gpt-4.1-mini
AGENTICA_AI_ALLOWED_CLASSIFICATIONS=["Internal"]
AGENTICA_AI_DAILY_CALL_LIMIT=40
AGENTICA_AI_MAX_OUTPUT_TOKENS=900
```

Other cheap deployments available on the resource: `gpt-4.1-nano` (cheapest), `gpt-4o-mini`, `gpt-5-mini` and `gpt-5-nano`. The gpt-5 models spend extra hidden reasoning tokens. The "Model assessment" button on the Root cause analysis page uses the same API-key connection.

### In the AI War Room

- **Mission panel:**
  - **Header:** mission ID, mode, status, a live indicator, the iteration stepper and Cancel or Resume.
  - **Analysis:** the Orchestrator's analysis line.
  - **Decision card:** a highlighted **human decision card**: amber for team and root cause, red for the fix, teal for the outcome. The team card is an editable list with reasons; the separation-of-duties message appears when it applies.
  - **Learned so far:** carried between iterations.
  - **Activity feed:** a live timeline of every step, finding, hand-off and decision.
- **Command view:**
  - shows the actual mission team;
  - proposed agents wait "awaiting approval";
  - left-out agents show greyed as "Held back", "Removed" or "Not needed", with the reason on hover;
  - squads with nobody on the team are marked "Not needed";
  - the hub caption follows the mission ("Team proposed · awaiting approval", "Team at work · iteration 2", "Awaiting human decision", …).
- **Agent details:** clicking an agent opens it in the inspector, showing why it was chosen, its finding, the evidence it cited and whether the finding was AI-generated or a simulated fallback.
- **AI labels:** the header shows **AI-GENERATED** or **SIMULATED**, and the provider reads "Azure OpenAI gpt-4.1-mini (API key)". The mission panel shows the usage meter ("2/40 calls today · 1.9k tokens") and tags each plan as **AI-generated plan** or **Simulated fallback**.

The existing 17-action incident workflow (`workflow.py`) is unchanged; a mission records proposals, findings, decisions and learnings but does not change the incident's lifecycle status by itself.

---

## 11. Payment API sandbox: live, local and measurable

A real payment service (`payment_api/app.py`) that fails for real and recovers for real. It's the "testable thing" in the demo. Full talk track: **[DEMO_GUIDE.md](DEMO_GUIDE.md)**.

| Release | Pool size | Feature X (`GET /payments/summary`) | 50 concurrent requests (measured) |
|---|---|---|---|
| v3.8.1 (faulty) | 5 | available | about 8–9 of 50 fail with HTTP 500, p95 about 2.4 s |
| v3.8.1 (approved fix) | 20 | available | 0 of 50 fail, p95 about 0.9 s |
| previous (approved rollback) | 20 | not available (404) | 0 failures, but the feature is gone |

**How it works:**
- **Local mode (default, no Docker)** — `backend/payment_local.py`:
  - runs the Payment API as a local process on `127.0.0.1:18080` with its own SQLite file;
  - uses the same bounded connection pool as the container deployment (no overflow, 2 s wait limit, 0.3 s hold per request);
  - accepts only the 3 approved configurations, and verifies each change against the live `/control/config`;
  - writes each change to `data/payment-sandbox-audit.jsonl`;
  - starts it as a separate process, so stopping the backend stops it too.
- **API** (`backend/app.py`): status, start, run workload and reset endpoints under `/api/v1/sandbox/payment` (Incident Manager, SRE or Administrator).
- **Evidence** (`backend/sandbox_records.py`): each run is saved as a **MEASURED** metric on INC-1043, plus the real error lines from the service log, so agents and the AI reason over observed numbers.
- **Missions:** on the sandbox incident, the fix gate states the **exact action**. After a *different* person approves it, the mission:
  1. applies it to the running service;
  2. re-runs the workload;
  3. decides the outcome from the **measurement** (not an AI or simulated guess).
- **The classic workflow** (Changes → deploy) uses the same controller.
- **Container mode:** `PAYMENT_SANDBOX_MODE=container` selects the original Podman Compose adapter (`backend/payment_sandbox.py`, `compose.yaml`).
- **War Room panel:** shows running state, release, pool size, Feature X, a 50-bar result chart, the error rate and p95, and a history of runs.

**Live verification (2026-11-11):**
- Before: pool 5 gave **8/50 failed** (16%, p95 2,459 ms).
- The AI mission proposed a team of 3, root cause at confidence 0.95, and the fix *pool 5 → 20*. The Change Approver approved it.
- The mission applied it, and the live service reported pool 20.
- After: **0/50 failed**, p95 942 ms, Feature X available.
- AI cost: 3 calls, about 3,800 tokens.

---

## 12. Realistic demo data and reset

**What the demo data contains** (`backend/seed_stories.py`, on top of `backend/seed.py`):
- every incident has a coherent story that matches its service, status and impact;
- 44 evidence records (logs, metrics, traces, change records, tests);
- 12 hypotheses with supporting and contradicting evidence;
- 6 remediation proposals, 4 test runs, 9 runbooks, 7 deployments, 120 log lines and an audit timeline.

**How to reset it:**
- **Administration → Reset demo data** (Administrator, demo mode only):
  - backs up the current database to `data/backups/agentica-<time>.db`;
  - restores the stories;
  - keeps you signed in;
  - stops the sandbox.
- **From a terminal** (with the backend stopped): `python -m backend.demo_reset`.

---

## 13. Configuration (`.env`)

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

## 14. Running the project

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

## 15. Verification (2026-11-11, after all changes)

| Check | Command | Result |
|---|---|---|
| Backend tests | `pytest backend/tests` (in-memory DB) | **84 passed** (incl. mission, Foundry-brain, live sandbox process and reset tests) |
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

## 16. Roadmap and status

| Stage | Status | Scope |
|---|---|---|
| 0 Repository audit | PASS | Audit, architecture and mapping docs |
| 1A Payment API sandbox | WARN | Code complete; runtime acceptance NOT RUN |
| 1B Agents, evidence, events and security | IN PROGRESS | **Done:** Orchestrator-led missions with dynamic team selection and skip reasons, human gates, iterations with learnings, persisted events, all shown live in the War Room (simulated rule-based planner). **Also done:** Azure OpenAI brain (gpt-4.1-mini) with cost limits, verified live. **Next:** real read-only tools |
| 2 Workforce view and replay | WARN | The agent command view replaces the 3D scene; full acceptance (dynamic selection, replay) depends on 1B |
| 3 Golden scenario | NOT RUN | Full end-to-end Payment API recovery |
| 4 Business value and benchmark | NOT RUN | Human baseline vs BEHAVE |
| Enterprise expansion | NOT STARTED | Tenant isolation, migrations, object storage |

---

## 17. Known limitations

- Investigation, testing, scanning and deployment are synthetic except in the Payment API sandbox.
- There is a single workspace with no tenant isolation, so don't use real secrets or production data.
- Redaction is pattern-based, not full DLP. There's no malware scanning, and the local database isn't tamper-proof.
- There are no database migrations, no object storage and no durable event stream.
- The AI provider isn't connected or verified.
- The wordmark is an approximation built from text in the Roboto font. It is not the official Kyndryl logo artwork.
- The production build warns that one JavaScript bundle is larger than 500 kB. This is a performance hint, not an error.

---

## 18. Suggested reading order

1. `README.md`, then `docs/architecture.md` and `docs/implementation-roadmap.md`
2. `backend/domain.py`, then `backend/workflow.py`, then `backend/app.py`
3. `backend/seed.py` for the demo data
4. `src/App.tsx`, `src/context.tsx`, `src/theme-bridge.css`
5. `src/pages/WarRoom.tsx` and `src/components/war-room/AgentWorkforce3D.tsx`
6. `payment_api/app.py` and `backend/payment_sandbox.py`
