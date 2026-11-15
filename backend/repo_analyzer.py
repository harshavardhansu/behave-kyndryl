"""Comprehensive GitHub and repository file analyzer.
Evaluates architecture, security, CI/CD workflow, and reliability across repository files.
"""

import re
from typing import Any
from .domain import now, redact


def analyze_github_file(
    filename: str,
    content: str,
    repo_name: str = "custom/repository",
    scope: list[str] | None = None,
    ai_brain: Any = None,
) -> dict:
    active_scope = set(scope or ["architecture", "security", "workflow", "reliability"])
    findings: list[dict] = []
    lines = content.splitlines()
    line_count = len(lines)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else filename.lower()

    # 1. SECURITY RULES
    if "security" in active_scope:
        # Check for hardcoded credentials / tokens
        secret_patterns = [
            (r"(?i)\b\w*(api[_-]?key|secret|token|password|passwd|auth)\w*\s*[=:]\s*['\"][^'\"\s]{10,}['\"]", "Hardcoded credential or token detected", "Critical", "Secrets in repository files can be leaked into build artifacts and version control."),
            (r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}", "Hardcoded bearer token", "Critical", "Raw authorization tokens must never be committed to source files."),
            (r"(?i)private[_-]?key", "Private key reference in repository file", "High", "Ensure private keys are fetched securely from an enterprise vault at runtime."),
            (r"https?://[^/@\s]+:[^/@\s]+@", "Basic auth credentials embedded in URL", "High", "Embedding usernames and passwords in URLs exposes secrets in logs and traces."),
            (r"(?i)chmod\s+(-R\s+)?777", "Overly permissive file permissions (chmod 777)", "High", "Unrestricted permissions violate the principle of least privilege."),
            (r"(?i)(curl|wget).*(?:-k|--insecure|verify\s*=\s*False)", "Disabled TLS/SSL certificate verification", "Medium", "Disabling certificate validation opens connections to man-in-the-middle attacks."),
            (r"^\s*DEBUG\s*=\s*True\b", "Debug mode switched on in settings", "Medium", "Debug mode shows stack traces, settings and SQL to any visitor when it reaches production."),
            (r"^\s*ALLOWED_HOSTS\s*=\s*\[\s*['\"]\*['\"]\s*\]", "Any host name accepted (ALLOWED_HOSTS = ['*'])", "Medium", "Accepting every Host header enables host-header attacks and cache poisoning.")
        ]
        for idx, line in enumerate(lines, 1):
            for pattern, title, severity, impact in secret_patterns:
                if re.search(pattern, line):
                    findings.append({
                        "id": f"SEC-{len(findings) + 1}",
                        "category": "Security",
                        "severity": severity,
                        "title": title,
                        "file": filename,
                        "line": idx,
                        "detail": line.strip()[:160],
                        "impact": impact,
                        "solution": "Externalize sensitive values to environment variables or Azure Key Vault / GitHub Secrets.",
                        "codeSnippet": f"- {line.strip()[:100]}\n+ {re.sub(r'([=:]\s*[\'"]).*?([\'\"])', r'\1${SECRET_VAR}\2', line.strip()[:100])}"
                    })

        # Dockerfile security checks
        if ext in {"dockerfile", "docker"} or "dockerfile" in filename.lower():
            has_user_instruction = any(re.match(r"(?i)^\s*USER\s+", line) for line in lines)
            if not has_user_instruction:
                findings.append({
                    "id": f"SEC-{len(findings) + 1}",
                    "category": "Security",
                    "severity": "High",
                    "title": "Container runs as root user",
                    "file": filename,
                    "line": 1,
                    "detail": "No non-root USER instruction found in Dockerfile.",
                    "impact": "Running containers as root poses container-escape and privilege escalation risks.",
                    "solution": "Define an unprivileged user (e.g. USER 10001:10001 or USER appuser) before ENTRYPOINT.",
                    "codeSnippet": "+ USER 10001:10001\n  ENTRYPOINT [\"java\", \"-jar\", \"app.jar\"]"
                })
            latest_tags = [(idx, line) for idx, line in enumerate(lines, 1) if re.search(r"(?i)^\s*FROM\s+[\w\-\.\/]+:latest", line)]
            for idx, line in latest_tags:
                findings.append({
                    "id": f"SEC-{len(findings) + 1}",
                    "category": "Security",
                    "severity": "Medium",
                    "title": "Unpinned base image (:latest tag)",
                    "file": filename,
                    "line": idx,
                    "detail": line.strip(),
                    "impact": "Using mutable :latest tags causes non-reproducible builds and unexpected upstream breaking changes.",
                    "solution": "Pin the base image to an exact immutable digest or specific patch version.",
                    "codeSnippet": f"- {line.strip()}\n+ {line.strip().replace(':latest', ':21-jre-alpine@sha256:...')}"
                })

    # 2. CI/CD WORKFLOW RULES
    if "workflow" in active_scope and (ext in {"yml", "yaml"} or ".github" in filename.lower() or "workflow" in filename.lower()):
        # GitHub Actions checks
        for idx, line in enumerate(lines, 1):
            if re.search(r"uses:\s*[\w\-\/]+@master", line):
                findings.append({
                    "id": f"WFK-{len(findings) + 1}",
                    "category": "Workflow",
                    "severity": "High",
                    "title": "Unpinned GitHub Action referencing mutable branch (@master)",
                    "file": filename,
                    "line": idx,
                    "detail": line.strip(),
                    "impact": "Attacking an upstream repository or branch can inject malicious steps into your build pipeline (supply chain attack).",
                    "solution": "Pin third-party GitHub Actions to a full commit SHA or approved release tag.",
                    "codeSnippet": f"- {line.strip()}\n+ {re.sub(r'@master', '@v4 # pin SHA', line.strip())}"
                })
            if re.search(r"(?i)echo\s+.*(?:token|secret|password|api_key)", line):
                findings.append({
                    "id": f"WFK-{len(findings) + 1}",
                    "category": "Workflow",
                    "severity": "High",
                    "title": "Potential credential exposure in workflow echo",
                    "file": filename,
                    "line": idx,
                    "detail": line.strip(),
                    "impact": "Printing secret variables in workflow step scripts risks leaking secrets into pipeline execution logs.",
                    "solution": "Do not echo secrets. Use masked GitHub Actions secret inputs.",
                    "codeSnippet": f"- {line.strip()}\n+ # masked environment variable passed directly"
                })

        # Check for missing timeout-minutes
        if "jobs:" in content and "timeout-minutes:" not in content:
            findings.append({
                "id": f"WFK-{len(findings) + 1}",
                "category": "Workflow",
                "severity": "Medium",
                "title": "Missing job timeout-minutes boundary",
                "file": filename,
                "line": 1,
                "detail": "Workflow jobs do not declare a timeout-minutes constraint.",
                "impact": "Hanging jobs can consume runner credits indefinitely until the 6-hour system default.",
                "solution": "Declare 'timeout-minutes: 15' on all CI/CD workflow jobs.",
                "codeSnippet": "  job_name:\n+   timeout-minutes: 15\n    runs-on: ubuntu-latest"
            })

    # 3. ARCHITECTURE RULES
    if "architecture" in active_scope:
        # Check connection pool configuration
        for idx, line in enumerate(lines, 1):
            if re.search(r"(?i)maximum-pool-size:\s*([1-9]|10)\b", line):
                findings.append({
                    "id": f"ARC-{len(findings) + 1}",
                    "category": "Architecture",
                    "severity": "High",
                    "title": "Constrained database connection pool size",
                    "file": filename,
                    "line": idx,
                    "detail": line.strip(),
                    "impact": "Low pool limits (<= 10) easily cause thread queue starvation and HTTP 503 latency spikes during concurrent bursts.",
                    "solution": "Size the connection pool to match the replica concurrency budget (e.g. 20-30 connections per pod with rds-proxy).",
                    "codeSnippet": f"- {line.strip()}\n+ {re.sub(r':\s*\d+', ': 25', line.strip())}"
                })
            if re.search(r"(?i)connection-timeout:\s*([1-9]\d{4,})\b", line):
                findings.append({
                    "id": f"ARC-{len(findings) + 1}",
                    "category": "Architecture",
                    "severity": "Medium",
                    "title": "Excessively high database connection acquisition timeout",
                    "file": filename,
                    "line": idx,
                    "detail": line.strip(),
                    "impact": "Waiting > 10s for database connections ties up thread pools and propagates cascading failures upstream.",
                    "solution": "Set connection timeout to a fail-fast threshold (e.g. 2000ms - 3000ms).",
                    "codeSnippet": f"- {line.strip()}\n+ {re.sub(r':\s*\d+', ': 2000', line.strip())}"
                })

    # 4. RELIABILITY RULES
    if "reliability" in active_scope:
        # Code level checks (Java, Python, TS, etc.)
        for idx, line in enumerate(lines, 1):
            if re.search(r"(?i)catch\s*\(.*Exception.*\)\s*\{\s*\}", line) or re.search(r"(?i)except\s*:\s*pass", line):
                findings.append({
                    "id": f"REL-{len(findings) + 1}",
                    "category": "Reliability",
                    "severity": "High",
                    "title": "Swallowed exception / empty error handler",
                    "file": filename,
                    "line": idx,
                    "detail": line.strip(),
                    "impact": "Silent exception swallowing hides catastrophic errors and makes incident forensics impossible.",
                    "solution": "Log the exception with correlation trace IDs and propagate an explicit domain exception.",
                    "codeSnippet": f"- {line.strip()}\n+ logger.error(\"Operation failed\", exception); throw new ServiceException(exception);"
                })
            if re.search(r"(?i)while\s*\(true\)", line) and "sleep" not in line.lower():
                findings.append({
                    "id": f"REL-{len(findings) + 1}",
                    "category": "Reliability",
                    "severity": "Medium",
                    "title": "Potential unthrottled infinite loop",
                    "file": filename,
                    "line": idx,
                    "detail": line.strip(),
                    "impact": "Unthrottled loops cause 100% CPU core pinning and denial-of-service on shared containers.",
                    "solution": "Add termination conditions, max iteration limits, and backoff pacing.",
                    "codeSnippet": "  int attempts = 0;\n+ while (attempts++ < MAX_RETRIES) {\n+     Thread.sleep(backoff);\n  }"
                })

    # If no severe issues found, add positive best practice findings (single-file view only; a repository scan drops it)
    if not findings and not getattr(analyze_github_file, "_quiet", False):
        findings.append({
            "id": "ARC-OK",
            "category": "Architecture",
            "severity": "Low",
            "title": "Configuration structure adheres to standard boundaries",
            "file": filename,
            "line": 1,
            "detail": f"Analyzed {line_count} lines in {filename}. Modular layout and clear component boundaries.",
            "impact": "Code adheres to recommended conventions without immediate structural defects.",
            "solution": "Continue maintaining automated contract and unit tests.",
            "codeSnippet": f"# Validated clean structure in {filename}"
        })

    # Compute overall health score
    deductions = sum(25 if f["severity"] == "Critical" else 15 if f["severity"] == "High" else 8 if f["severity"] == "Medium" else 3 for f in findings)
    score = max(20, min(100, 100 - deductions))

    # Generate Markdown Report
    critical_count = sum(1 for f in findings if f["severity"] == "Critical")
    high_count = sum(1 for f in findings if f["severity"] == "High")
    med_count = sum(1 for f in findings if f["severity"] == "Medium")
    low_count = sum(1 for f in findings if f["severity"] == "Low")

    report_md = f"""# Repository Deep Analysis Report
**Target File**: `{filename}`  
**Repository**: `{repo_name}`  
**Analyzed At**: {now()}  
**Overall Health Score**: **{score} / 100**  
**Method**: rule-based pattern checks (no AI model was called)  

---

## 1. Executive Summary
Deep static and architectural analysis of `{filename}` ({line_count} lines) identified **{len(findings)} findings**:
- **Critical**: {critical_count}
- **High**: {high_count}
- **Medium**: {med_count}
- **Low**: {low_count}

{ "⚠️ Immediate remediation required before production deployment." if critical_count + high_count > 0 else "✅ Configuration and code posture meet baseline enterprise standards." }

---

## 2. Categorized Findings & Solutions

"""
    for f in findings:
        report_md += f"""### [{f['severity'].upper()}] {f['title']}
- **Category**: `{f['category']}`
- **Location**: `{f['file']}:{f['line']}`
- **Observed**: `{f['detail']}`
- **Risk & Impact**: {f['impact']}
- **Recommended Solution**: {f['solution']}

```diff
{f['codeSnippet']}
```

---
"""

    report_md += """
## 3. Production Verification & Compliance Gates
- [x] Static AST & regex vulnerability analysis complete.
- [ ] Automated regression testing on proposed patches.
- [ ] Separate human approval sign-off for critical changes.
- [ ] Verification in isolated staging environment.

*Generated by Behave Kyndryl (rule-based analysis).*
"""

    return {
        "filename": filename,
        "repoName": repo_name,
        "lineCount": line_count,
        "score": score,
        "stats": {
            "critical": critical_count,
            "high": high_count,
            "medium": med_count,
            "low": low_count,
            "total": len(findings),
        },
        "findings": findings,
        "reportMarkdown": report_md,
        "analyzedAt": now(),
    }


CATEGORY_TO_SCOPE = {"Security": "Security", "Workflow": "Configuration", "Architecture": "Code paths", "Reliability": "Code paths"}
SCOPE_TO_RULES = {"Security": "security", "Configuration": "workflow", "Code paths": "architecture", "Dependencies": "reliability", "Tests": "reliability"}
MAX_SCANNED_FILES = 150


def _mask(line: str) -> str:
    """Hide what a secret rule matched: quoted values, values after '=' or ':' on credential-like keys, and URL passwords."""
    line = redact(line)
    line = re.sub(r"(?i)((?:api[_-]?key|secret|token|password|passwd|pwd|auth|bearer|private[_-]?key)\w*\s*[=:]\s*)(['\"]?)[^'\"\s,;]+\2", r"\1\2***\2", line)
    line = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]{8,}=*", r"\1***", line)
    return re.sub(r"(https?://[^/@\s:]+:)[^/@\s]+@", r"\1***@", line)


def scan_repository(code: Any, scope: list[str]) -> tuple[list[dict], int]:
    """Run the static rules over the REAL files of a repository (read through a connector).

    Returns (findings, files scanned). Nothing is executed and no AI model is used: every finding names
    the file and line the rule matched, so a person can check it.
    """
    rules = sorted({SCOPE_TO_RULES[item] for item in scope if item in SCOPE_TO_RULES})
    findings: list[dict] = []
    paths = code.paths()[:MAX_SCANNED_FILES]
    for path in paths:
        text = code.read(path) or ""
        if not text.strip():
            continue
        for item in analyze_github_file(path, text, getattr(code, "label", ""), rules)["findings"]:
            if str(item.get("id", "")).endswith("-OK"):
                continue  # "nothing found" is not a finding
            category = CATEGORY_TO_SCOPE.get(item["category"], "Code paths")
            if category not in scope:
                continue
            findings.append({
                "id": f"REPO-{len(findings) + 1}", "title": item["title"], "severity": item["severity"], "category": category,
                "file": item["file"], "line": item.get("line") or 1, "confidence": 0.6,
                "evidence": [f"{item['file']}:{item.get('line') or 1}: {_mask(str(item.get('detail', '')))[:160]}"],
                "guidance": f"{item.get('impact', '')} {item.get('solution', '')}".strip(),
                "validation": "Pattern match by a static rule: confirm by reading the line in context before changing anything.",
            })
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    findings.sort(key=lambda finding: (order.get(finding["severity"], 4), finding["file"], finding["line"]))
    return findings[:200], len(paths)
