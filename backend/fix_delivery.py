"""Delivering a fix to a connected project: exact code edits, a reviewable diff and a pull request.

The remediation agent proposes its fix as a list of **edits**: ``{path, find, replace}``, where ``find``
is one or more complete lines copied from the current file. Nothing the agent says is trusted:

1. ``build_patch`` checks every edit against the real file (it must be an existing, readable source
   file and the lines must be found exactly once) and produces the diff people review at the fix gate.
2. Only **after a human approved the fix**, ``open_pull_request`` re-applies the same edits to the
   latest files, pushes them to a **new branch** and opens a pull request. It never writes to the
   base branch, never merges, and never touches files the agents cannot read (hidden files, ``.env``,
   pipelines under ``.github``, vendored code).

The project's own pipeline then tests the pull request and its owners merge it. A project gets pull
requests only when its ``projects.json`` entry says ``"pull_requests": true`` and a token is set.
"""

import base64
import difflib
import re
from typing import Any

import httpx

from .connectors import GitHubCode

MAX_EDITS = 8
MAX_FILES = 5
MAX_REPLACE_CHARS = 6000
MAX_DIFF_CHARS = 6000


def _lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").split("\n")


def replace_lines(text: str, find: str, replace: str) -> tuple[str, str]:
    """Replace the block of complete lines ``find`` in ``text``. Returns (new text, problem).

    Matching ignores line endings and trailing spaces, but the block must exist exactly once.
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = _lines(text)
    wanted = [line.rstrip() for line in _lines(find)]
    while wanted and not wanted[0]:
        wanted.pop(0)
    while wanted and not wanted[-1]:
        wanted.pop()
    if not wanted:
        return text, "'find' is empty: copy the complete lines to change from the file."
    hay = [line.rstrip() for line in lines]
    hits = [index for index in range(len(hay) - len(wanted) + 1) if hay[index:index + len(wanted)] == wanted]
    if not hits:
        return text, "the lines in 'find' are not in the file: copy complete lines exactly, including indentation."
    if len(hits) > 1:
        return text, f"the lines in 'find' appear {len(hits)} times: include more surrounding lines so they match once."
    added = _lines(replace)
    while added and not added[-1].strip():
        added.pop()
    start = hits[0]
    result = lines[:start] + added + lines[start + len(wanted):]
    if not added:  # a deleted block must not leave its surrounding blank lines doubled up
        while start > 0 and not result[start - 1].strip() and (start >= len(result) or not result[start].strip()):
            del result[start - 1]
            start -= 1
    if [line.rstrip() for line in result] == hay:
        return text, "the edit changes nothing."
    return newline.join(result), ""


def _diff(path: str, before: str, after: str) -> dict:
    rows = list(difflib.unified_diff(_lines(before), _lines(after), f"a/{path}", f"b/{path}", lineterm="", n=3))
    text = "\n".join(rows)
    return {
        "path": path,
        "additions": sum(1 for row in rows[2:] if row.startswith("+")),
        "deletions": sum(1 for row in rows[2:] if row.startswith("-")),
        "diff": text if len(text) <= MAX_DIFF_CHARS else text[:MAX_DIFF_CHARS] + "\n… (diff shortened)",
    }


def _apply(edits: list[dict], known: list[str], read) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Apply edits in order. Returns ({path: (before, after)}, problems)."""
    problems: list[str] = []
    changed: dict[str, tuple[str, str]] = {}
    if len(edits) > MAX_EDITS:
        problems.append(f"Too many edits ({len(edits)}); at most {MAX_EDITS} are accepted.")
    for number, edit in enumerate(edits[:MAX_EDITS], start=1):
        path = str(edit.get("path", "")).strip().lstrip("./")
        if path not in known:
            problems.append(f"Edit {number}: {path or '(no path)'} is not an editable file of this repository.")
            continue
        if len(str(edit.get("replace", ""))) > MAX_REPLACE_CHARS:
            problems.append(f"Edit {number}: the replacement for {path} is too large.")
            continue
        before = changed[path][0] if path in changed else read(path)
        current = changed[path][1] if path in changed else before
        if current is None:
            problems.append(f"Edit {number}: {path} could not be read.")
            continue
        after, problem = replace_lines(current, str(edit.get("find", "")), str(edit.get("replace", "")))
        if problem:
            problems.append(f"Edit {number} ({path}): {problem}")
            continue
        changed[path] = (before, after)
    if len(changed) > MAX_FILES:
        problems.append(f"The fix touches {len(changed)} files; at most {MAX_FILES} are accepted.")
    return changed, problems


def build_patch(code: Any, edits: list[dict]) -> dict:
    """Check the agent's edits against the real files and build the diff shown at the fix gate."""
    edits = [{"path": str(e.get("path", "")), "find": str(e.get("find", "")), "replace": str(e.get("replace", ""))} for e in edits if isinstance(e, dict)]
    if not edits:
        return {"edits": [], "files": [], "problems": [], "valid": False, "deliverable": False}
    changed, problems = _apply(edits, code.paths(), code.read)
    valid = bool(changed) and not problems
    return {
        "edits": edits,
        "files": [_diff(path, before, after) for path, (before, after) in changed.items()],
        "problems": problems,
        "valid": valid,
        "deliverable": valid and bool(getattr(code, "pull_requests", False)),
        "source": getattr(code, "label", ""),
    }


def _branch_name(incident_id: str, mission_id: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", f"{incident_id}-{mission_id}".lower()).strip("-")
    return f"behave/{slug[:60]}"


def open_pull_request(code: Any, edits: list[dict], incident_id: str, mission_id: str, title: str, body: str) -> dict:
    """Push the approved edits to a new branch and open a pull request. Never raises."""
    if not isinstance(code, GitHubCode) or not code.pull_requests:
        return {"status": "SKIPPED", "error": "Pull requests are not enabled for this project."}
    if not code.token:
        return {"status": "SKIPPED", "error": "No GitHub token is configured (AGENTICA_GITHUB_TOKEN), so the pull request was not opened."}
    api, headers = f"{code.api}/repos/{code.repo}", code._headers()
    full = (lambda path: f"{code.subfolder}/{path}") if code.subfolder else (lambda path: path)
    branch = _branch_name(incident_id, mission_id)
    created = False
    try:
        with code._client() as client:
            def call(method: str, url: str, **kwargs) -> httpx.Response:
                response = client.request(method, url, headers=headers, **kwargs)
                response.raise_for_status()
                return response

            base = code.ref or call("GET", api).json()["default_branch"]
            head = call("GET", f"{api}/git/ref/heads/{base}").json()["object"]["sha"]

            # Re-apply the edits to the files as they are on the base branch right now.
            shas: dict[str, str] = {}

            def read(path: str) -> str | None:
                item = call("GET", f"{api}/contents/{full(path)}", params={"ref": base}).json()
                shas[path] = item["sha"]
                return base64.b64decode(item["content"]).decode("utf-8")

            changed, problems = _apply(edits, code.paths(), read)
            if problems or not changed:
                return {"status": "FAILED", "error": "The approved change no longer applies to the latest code: " + ("; ".join(problems) or "nothing to change") + "."}

            for attempt in range(3):  # a branch from an earlier mission keeps its name; pick a free one
                name = branch if attempt == 0 else f"{branch}-{attempt + 1}"
                response = client.post(f"{api}/git/refs", headers=headers, json={"ref": f"refs/heads/{name}", "sha": head})
                if response.status_code == 201:
                    branch, created = name, True
                    break
                if response.status_code != 422:
                    response.raise_for_status()
            if not created:
                return {"status": "FAILED", "error": f"Could not create the branch {branch}."}

            for path, (_, after) in changed.items():
                call("PUT", f"{api}/contents/{full(path)}", json={
                    "message": f"{title}\n\n{incident_id}: change proposed by AI agents and approved by a human reviewer.",
                    "content": base64.b64encode(after.encode("utf-8")).decode("ascii"), "sha": shas[path], "branch": branch,
                })
            pull = call("POST", f"{api}/pulls", json={"title": title[:200], "head": branch, "base": base, "body": body[:60000]}).json()
            return {"status": "OPENED", "url": pull["html_url"], "number": pull["number"], "branch": branch, "base": base,
                    "repository": code.repo, "files": list(changed), "error": ""}
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        reason = {401: "the token was rejected", 403: "the token may not write to this repository", 404: "the repository, branch or file was not found (or the token cannot see it)",
                  422: "GitHub refused the request"}.get(status, f"GitHub answered {status}")
        problem = f"The pull request could not be opened: {reason}."
    except (httpx.HTTPError, KeyError, ValueError) as error:
        problem = f"The pull request could not be opened: {type(error).__name__}."
    if created:  # do not leave a half-written branch behind
        try:
            with code._client() as client:
                client.delete(f"{api}/git/refs/heads/{branch}", headers=headers)
        except httpx.HTTPError:
            problem += f" The branch {branch} may need to be deleted by hand."
    return {"status": "FAILED", "error": problem}
