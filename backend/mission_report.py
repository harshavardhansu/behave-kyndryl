"""Detailed investigation and resolution report (PDF) for an agent mission.

Everything in the report comes from what actually happened in the mission: the ticket and
evidence, the team the Orchestrator chose, every read-only tool call each agent made, the findings,
the human decisions, the measured outcomes and the validation. Nothing is invented: when something
did not happen (no fix applied, no measurement), the report says so.
"""

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .pdf_generator import NumberedCanvas, _escape, _get_styles

NAVY, ACCENT, ZEBRA, GRID = "#0F172A", "#0284C7", "#F8FAFC", "#E2E8F0"
WIDTH = 532


def pick_mission(state: dict, incident_id: str) -> dict | None:
    """The mission to report on: the most recent one for this incident."""
    missions = [m for m in state.get("missions", []) if m.get("incidentId") == incident_id]
    return max(missions, key=lambda m: m.get("createdAt", ""), default=None)


def _source_kind(source: str | None) -> str:
    text = source or ""
    if "Foundry agent" in text and "unavailable" not in text:
        return "Foundry agent"
    if text.startswith("MEASURED"):
        return "Measured"
    if text.startswith("SIMULATED"):
        return "Simulated"
    if "Azure OpenAI" in text:
        return "Azure OpenAI model"
    return "Unlabelled"


def generate_mission_report_pdf(incident: dict, mission: dict, state: dict) -> bytes:
    styles = _get_styles()
    story: list[Any] = []
    incident_id = incident["id"]
    iterations = mission.get("iterations", [])
    last = iterations[-1] if iterations else {}
    outcome = last.get("outcome") or {}
    resolved = mission.get("status") == "Resolved" or bool(mission.get("resolution"))
    evidence = [e for e in state.get("evidence", []) if e.get("incidentId") == incident_id]
    all_findings = [(it["number"], m) for it in iterations for m in it.get("team", []) if m.get("findings")]
    kinds: dict[str, int] = {}
    for _, member in all_findings:
        kind = _source_kind(member["findings"].get("source"))
        kinds[kind] = kinds.get(kind, 0) + 1
    tool_calls = sum(len(m["findings"].get("toolCalls") or []) for _, m in all_findings)

    def heading(text: str) -> None:
        story.append(Spacer(1, 8))
        story.append(Paragraph(_escape(text), styles["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor(ACCENT), spaceAfter=6))

    def para(text: str, style: str = "Body") -> None:
        story.append(Paragraph(text, styles[style]))

    def table(rows: list[list[str]], widths: list[int], mono: set[int] | None = None) -> None:
        mono = mono or set()
        header = [Paragraph(f"<b>{_escape(cell)}</b>", styles["TableHeader"]) for cell in rows[0]]
        body = [[Paragraph(_escape(cell), styles["TableCellMono" if i in mono else "TableCell"]) for i, cell in enumerate(row)] for row in rows[1:]]
        grid = Table([header, *body], colWidths=widths, repeatRows=1)
        grid.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(ZEBRA)]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(GRID)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(grid)

    # ---- Title and summary ------------------------------------------------
    para("INCIDENT INVESTIGATION &amp; RESOLUTION REPORT", "DocTitle")
    para(f"<b>{_escape(incident_id)}</b> · {_escape(incident.get('title'))} · Mission {_escape(mission['id'])}", "DocSubtitle")
    verdict = "RESOLVED (confirmed by a human)" if resolved else {"Escalated": "ESCALATED to a human team", "Cancelled": "CANCELLED"}.get(mission.get("status"), f"NOT YET RESOLVED ({mission.get('status')})")
    colour = "#16A34A" if resolved else "#D97706"
    story.append(Paragraph(f'<font color="{colour}"><b>Outcome: {_escape(verdict)}</b></font>', styles["Body"]))
    table([
        ["Service", "Environment", "Severity", "Iterations", "Agents used", "Tool calls", "Requested by"],
        [str(incident.get("service")), str(incident.get("environment")), str(incident.get("severity")), f"{len(iterations)} of {mission.get('maxIterations', 3)}", str(len(all_findings)), str(tool_calls), str(mission.get("requestedBy"))],
    ], [70, 70, 55, 65, 70, 55, 147])
    story.append(Spacer(1, 6))
    summary = [f"The Orchestrator ran {len(iterations)} iteration{'s' if len(iterations) != 1 else ''} with a team chosen for this ticket. {len(all_findings)} agent findings were produced using {tool_calls} read-only tool calls (reading evidence, logs, status, changes, source files and runbooks)."]
    summary.append("Where the findings came from: " + ", ".join(f"{count} × {name}" for name, count in sorted(kinds.items())) + ".")
    if outcome.get("detail"):
        summary.append(f"Final assessment: {outcome['detail']}")
    for line in summary:
        para(_escape(line))

    # ---- The issue --------------------------------------------------------
    heading("1. The issue (the input we were given)")
    for label, key in (("Description", "description"), ("Business impact", "impact"), ("Observed error", "error"), ("Expected behaviour", "expected")):
        if incident.get(key):
            para(f"<b>{label}:</b> {_escape(incident[key])}")
    if evidence:
        table([["ID", "Type", "Evidence", "Classification"], *[[e["id"], str(e.get("type")), str(e.get("title")), str(e.get("classification"))] for e in evidence]], [70, 60, 300, 102], mono={0})

    # ---- What was done, per iteration -------------------------------------
    heading("2. What the agents did, iteration by iteration")
    for iteration in iterations:
        story.append(Paragraph(f"<b>Iteration {iteration['number']}</b>", styles["Body"]))
        plan = iteration.get("plan") or {}
        if plan.get("analysis"):
            para(f"<i>Orchestrator's reasoning ({_escape(_source_kind(plan.get('source')))}):</i> {_escape(plan['analysis'])}")
        if iteration.get("team"):
            rows = [["Agent", "Why it was chosen", "Source", "Confidence"]]
            for member in iteration["team"]:
                finding = member.get("findings") or {}
                rows.append([member["name"], member.get("reason", ""), _source_kind(finding.get("source")), f"{finding['confidence']:.2f}" if "confidence" in finding else "-"])
            table(rows, [105, 265, 90, 72])
        if iteration.get("skipped"):
            para("<b>Left out on purpose:</b> " + _escape("; ".join(f"{item.get('name') or item.get('role')} ({item.get('reason', '')})" for item in iteration["skipped"][:8])))
        story.append(Spacer(1, 6))

    # ---- Investigation trail ----------------------------------------------
    heading("3. Investigation trail: what each agent looked at and concluded")
    if not all_findings:
        para("<i>No agent findings were produced.</i>")
    for number, member in all_findings:
        finding = member["findings"]
        block: list[Any] = [Paragraph(f"<b>{_escape(member['name'])}</b> · iteration {number} · {_escape(finding.get('source', ''))}", styles["Body"])]
        calls = finding.get("toolCalls") or []
        if calls:
            rows = [["Tool", "Input", "Result"]] + [[c["tool"], ", ".join(f"{v}" for v in c.get("arguments", {}).values()) or "-", c.get("found", "")] for c in calls]
            header = [Paragraph(f"<b>{_escape(cell)}</b>", styles["TableHeader"]) for cell in rows[0]]
            grid = Table([header, *[[Paragraph(_escape(cell), styles["TableCellMono" if i == 0 else "TableCell"]) for i, cell in enumerate(row)] for row in rows[1:]]], colWidths=[110, 190, 232], repeatRows=1)
            grid.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(GRID)), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
            block.append(grid)
        else:
            block.append(Paragraph("<i>No tool calls recorded for this finding.</i>", styles["Body"]))
        cited = ", ".join(finding.get("evidenceIds") or []) or "none"
        block.append(Paragraph(f"<b>Finding:</b> {_escape(finding.get('summary'))} <i>(confidence {finding.get('confidence', 0):.2f}; evidence cited: {_escape(cited)})</i>", styles["Body"]))
        block.append(Spacer(1, 6))
        story.append(KeepTogether(block))

    # ---- Issues found vs solved --------------------------------------------
    heading("4. Issues found and what was solved")
    issues: list[list[str]] = []
    root = next((m["findings"] for _, m in reversed(all_findings) if m["role"] == "root-cause"), None)
    if root:
        issues.append(["Root cause", root["summary"], "Solved and confirmed" if resolved else "Open"])
    sandbox_change = next((it["sandboxChange"] for it in reversed(iterations) if it.get("sandboxChange")), None)
    if sandbox_change:
        active = sandbox_change.get("active") or {}
        issues.append(["Fix applied to the sandbox", f"Requested release {sandbox_change['requested'].get('release')} with pool size {sandbox_change['requested'].get('pool_size')}; running service reports {active or sandbox_change.get('error') or 'no confirmation'}.", "Applied and verified" if sandbox_change.get("status") == "SUCCEEDED" else "Failed: human must inspect"])
    for it in iterations:
        out = it.get("outcome") or {}
        gaps = out.get("missing") or []
        report = out.get("validationReport") or {}
        failed = [label for key, label in (("technical_correctness", "correctness"), ("completeness", "completeness"), ("cross_agent_consistency", "consistency"), ("security_and_risk_acceptable", "security and risk"), ("human_approval_satisfied", "human approvals")) if report and not report.get(key)]
        if failed or gaps:
            later = it["number"] < len(iterations)
            issues.append([f"Gap after iteration {it['number']}", "Validation failed on: " + (", ".join(failed) or "no failed check") + ". Not yet covered: " + (", ".join(gaps) or "nothing specific") + ".", "Addressed in a later iteration" if later and resolved else "Still open" if not resolved or not later else "Carried forward"])
    measurements = [e for e in evidence if str(e.get("title", "")).startswith("Measured workload")]
    for e in measurements:
        issues.append([f"Measurement {e['id']}", f"{e.get('title')}. {str(e.get('excerpt', ''))[:240]}", "Recorded"])
    if issues:
        table([["Item", "What we found", "Status"], *issues], [105, 337, 90])
    else:
        para("<i>No issues or measurements were recorded.</i>")

    # ---- Human decisions ----------------------------------------------------
    heading("5. Human decisions (every key step needed a person)")
    decisions = [[f"Iteration {it['number']}", d["type"], d["decision"], d["by"], d.get("note") or "-", str(d.get("at", ""))[:19].replace("T", " ")] for it in iterations for d in it.get("decisions", [])]
    if decisions:
        table([["When", "Gate", "Decision", "By", "Note", "Time (UTC)"], *decisions], [60, 70, 62, 90, 160, 90])
    else:
        para("<i>No human decisions were recorded yet.</i>")

    # ---- Validation --------------------------------------------------------
    heading("6. Final validation")
    report = outcome.get("validationReport")
    if report:
        table([["Check", "Result"], *[[label, "PASS" if report.get(key) else "FAIL"] for key, label in (("technical_correctness", "Technical correctness"), ("completeness", "Completeness"), ("cross_agent_consistency", "Cross-agent consistency"), ("security_and_risk_acceptable", "Security and risk acceptable"), ("human_approval_satisfied", "Human approvals satisfied"))]], [380, 152])
        para(_escape(report.get("summary", "")))
    elif outcome:
        detail = str(outcome.get("detail", ""))
        para(_escape(detail if detail.startswith(str(outcome.get("source", "?"))) else f"{outcome.get('source', '')}: {detail}"))
    else:
        para("<i>The mission has not reached the outcome review.</i>")

    # ---- Learnings and follow-ups -------------------------------------------
    heading("7. Learnings carried between iterations and open items")
    for learning in mission.get("learnings", []) or ["Resolved without another iteration, so there were no learnings to carry forward." if resolved else "No learnings recorded yet."]:
        para("• " + _escape(learning))
    if not resolved and outcome.get("missing"):
        para("<b>Still to do:</b> " + _escape(", ".join(outcome["missing"])))
    para("<i>All findings are AI-generated proposals for human review. Agents can read but never change anything; every change in this mission was approved by a person.</i>")

    # ---- Timeline --------------------------------------------------------------
    heading("8. Mission timeline (latest events)")
    events = [[str(e.get("timestamp", ""))[11:19], e.get("actor", ""), e.get("message", "")] for e in mission.get("events", [])[-40:]]
    if events:
        table([["Time", "Actor", "Event"], *events], [52, 110, 370])

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=letter, leftMargin=40, rightMargin=40, topMargin=50, bottomMargin=50, title=f"{incident_id} investigation report").build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()
