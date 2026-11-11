# BEHAVE KYNDRYL — Client Demo Guide

A 10-minute live demo of **agentic incident response with humans in the loop**, plus how it works underneath so you can answer questions confidently.

---

## 1. The story in one paragraph

A payment service shipped **release v3.8.1** with a new feature (a payment summary endpoint), but the release also lowered the **database connection pool from 20 to 5**. Under load, requests queue for a connection, wait longer than the 2-second limit, and fail with **real HTTP 500 errors**.

In the demo you:
1. reproduce the failure live;
2. let the **Orchestrator AI** analyse it and form a team of specialist agents;
3. **approve each important decision as a human**;
4. watch the approved fix get applied to the running service;
5. **prove the recovery with a real measurement**.

---

## 2. Before the demo (5 minutes, once)

1. **Start the app** in two terminals, from the project folder:
   ```
   python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
   npm run dev -- --host 127.0.0.1 --port 5173
   ```
   (Use `python`, `python3` or `py`, whichever runs Python on your laptop.) Then open **http://127.0.0.1:5173**.
2. **Reset the demo data:**
   - sign in as **Administrator** (profile menu → *Administrator*);
   - go to **Administration → Reset demo data → Back up and reset**;
   - then switch back to **Incident Manager**.
   This restores 13 realistic incidents and backs up whatever was there before (`data/backups/`).
3. **Optional, for real AI:** `.env` contains your Azure OpenAI settings (`gpt-4.1-mini`).
   - Without them the agents use the free **SIMULATED** planner. The demo still works, and is labelled honestly.
   - A full demo uses only about **3–6 AI calls (well under 1 cent)**.
4. **Tip:** open a second browser window (or a private window) signed in as **Change Approver**. It shows separation of duties more convincingly than switching personas.

---

## 3. The 10-minute script

### Step 1 · The command centre (1 min)
Open **Command centre**.

> "This is an Application Managed Services workspace. 13 incidents across checkout, payments, inventory, gateway, cache and more, each with its own evidence, hypotheses and fixes."

Click into a couple of incidents (e.g. **INC-1041** payment latency, **INC-1036** profile migration) to show that the data tells a consistent story.

### Step 2 · Reproduce the failure live (2 min)
Go to **AI War Room** → select **INC-1043 · Payment summary endpoint failing after v3.8.1 release**.

1. In **Live Payment API sandbox**, click **Start sandbox**. It shows *Release 3.8.1 · Pool size 5 · Feature X on*.
2. Click **Run workload (50 requests)**.

> "We just fired 50 simultaneous requests at the real service. Each green bar is a success, each red bar a real HTTP 500. About 8 of 50 failed: a 16% error rate. Nothing here is simulated."

The result is **saved as evidence**: a metric, plus the real error lines from the service log.

### Step 3 · The Orchestrator forms a team (2 min)
Click **Start agent mission**.

> "The Orchestrator reads the ticket and the measured evidence and decides which specialists it needs. Not all 13: only the ones this problem requires."

Point at the **Human decision required** card:
- each chosen agent has a **reason**;
- every left-out agent has a reason too;
- the mission is tagged **AI-generated plan**;
- the usage meter shows the cost (e.g. "1/40 calls today · 1.7k tokens").

You can **untick or tick agents** before approving; the human edits the team. Click **Approve team**.

### Step 4 · The team works, humans decide (2 min)
Watch the command view:
- **squads light up** and agents run;
- dots flow along the lines;
- the **Activity** feed streams findings and hand-offs.

1. **Root cause gate:** *"Connection pool size 5 with no overflow → QueuePool timeout under 50 concurrent requests… confidence 0.95."* Click **Approve root cause**.
2. **Fix gate:** it states the **exact action**: *"set the live Payment API sandbox to release 3.8.1 with pool size 20, then re-measure."*
   - As Incident Manager the button is **locked**: *separation of duties*, because you started the mission.
   - Switch to the **Change Approver** window and click **Approve fix**.

> "The AI can propose, but it cannot change anything. A different, authorised human must approve the exact action, and it's recorded in the audit trail."

### Step 5 · Apply and prove (2 min)
Right after the approval:
- **Release coordination** applies the change to the **running service**. The panel now shows **Pool size 20**.
- **Validation** re-runs the same 50-request workload: **50/50 OK, 0 errors, p95 ~0.9 s**.
- The outcome card reads **MEASURED: 0/50 requests failed…** and recommends **Confirm resolved**.

> "Recovery isn't claimed by an AI; it's measured. Same workload, before and after: 8 failures, then zero."

Click **Confirm resolved**.

### Step 6 · Wrap-up (1 min)
- **Audit trail** page: every decision with who, what and when.
- **Iterations:** if the outcome hadn't been resolved, the next iteration would start with the **learnings** carried forward, and could add specialists. There are at most 3 iterations, then it escalates to a human.

---

## 4. What happens underneath (for questions)

```
Browser (React)  ──REST──►  BEHAVE API (FastAPI)  ──►  SQLite (demo data, missions, audit)
                                   │
                                   ├─ Mission engine (backend/mission.py): plan → gates → steps → measure → gates
                                   ├─ AI brain (backend/foundry_brain.py): Azure OpenAI gpt-4.1-mini, strict JSON answers
                                   └─ Sandbox controller (backend/payment_local.py)
                                            │  starts / reconfigures / measures
                                            ▼
                                   Payment API (payment_api/app.py) on 127.0.0.1:18080 + its own SQLite file
```

| Question | Answer |
|---|---|
| Is the failure real? | Yes. The Payment API is a real web service with a real connection pool: **5 connections, no overflow, 2 s wait limit, 0.3 s per request**. 50 parallel requests need more than 5 connections, so some time out with HTTP 500. |
| Why does pool 20 fix it? | Needed connections ≈ requests × hold time ÷ wait limit. With 20 connections, every request gets one well within 2 s. |
| What can the AI change? | Nothing by itself. The controller accepts only 3 pre-approved configurations (v3.8.1/pool 5, v3.8.1/pool 20, previous/pool 20), for this one local service, and only after a different human approves. |
| How is the AI kept honest? | Answers must match a strict JSON format. Only real agent roles and evidence IDs that actually exist are accepted. Every item is labelled AI-GENERATED, SIMULATED or MEASURED. |
| What if Azure is down or the budget is used up? | The free simulated planner takes over automatically, clearly labelled "Simulated fallback". There's a daily limit of 40 calls (configurable). |
| What does it cost? | About 3–6 AI calls per mission with gpt-4.1-mini: a fraction of a cent. |
| Docker? | Not needed: "local mode" runs the Payment API as a normal process. A Podman/Docker setup is also included for production-like runs. |

### Useful API endpoints (for technical audiences)
- `GET /api/v1/sandbox/payment`: live status and recent measurements.
- `POST /api/v1/sandbox/payment/start` · `/workload` · `/reset`.
- `POST /api/v1/incidents/{id}/missions` · `POST /api/v1/missions/{id}/decision`.
- API docs: http://127.0.0.1:8000/api/docs

---

## 5. Reset between demos

- In the app: **Administration → Reset demo data** (Administrator). It also stops the sandbox.
- In the War Room: **Reset to faulty release** puts the sandbox back to v3.8.1 / pool 5 without touching other data.
- From a terminal, with the backend stopped: `python -m backend.demo_reset`.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| "Port 18080 is already used" | Another program uses the port. Stop it, or set `PAYMENT_LOCAL_PORT=18090` in `.env` and restart the backend. |
| Mission shows "Simulated fallback" | Azure wasn't reachable or the daily limit was reached; see the reason in the Activity feed. The demo still works. |
| "Approve fix" is disabled | Expected: the person who started the mission can't approve its fix. Use the Change Approver. |
| Nothing moves after a decision made in another window | The page refreshes every 4 s while a decision is pending; wait a moment. |
