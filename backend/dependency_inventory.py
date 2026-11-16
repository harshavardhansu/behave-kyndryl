"""The dependencies a project declares, read from its manifest files.

This is a real inventory of what the project's own files declare (requirements.txt, pyproject.toml,
package.json, pom.xml, go.mod, composer.json, Gemfile). It is not a resolved dependency graph and not a
vulnerability scan: transitive packages and installed versions are not known without building the
project, and the page says so.
"""

import json
import re
from typing import Any

MANIFEST_NAMES = ("requirements.txt", "pyproject.toml", "package.json", "pom.xml", "go.mod", "composer.json", "Gemfile")


def _row(name: str, version: str, ecosystem: str, scope: str, manifest: str) -> dict:
    return {"name": name.strip()[:120], "version": (version or "").strip()[:60] or "not pinned", "ecosystem": ecosystem, "scope": scope, "manifest": manifest}


def _requirements(text: str, path: str) -> list[dict]:
    rows = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*((?:[<>=!~]=?|===)\s*[^;\s]+(?:\s*,\s*[<>=!~]=?\s*[^;\s,]+)*)?", line)
        if match:
            rows.append(_row(match.group(1), (match.group(3) or "").replace(" ", ""), "PyPI", "runtime", path))
    return rows


def _pyproject(text: str, path: str) -> list[dict]:
    rows = []
    block = re.search(r"(?ms)^\[project\].*?^dependencies\s*=\s*\[(.*?)\]", text)
    for item in re.findall(r"[\"']([^\"']+)[\"']", block.group(1) if block else ""):
        rows += _requirements(item, path)
    poetry = re.search(r"(?ms)^\[tool\.poetry\.dependencies\]\s*(.*?)(?=^\[|\Z)", text)
    for name, version in re.findall(r"(?m)^([A-Za-z0-9._-]+)\s*=\s*[\"']([^\"']*)[\"']", poetry.group(1) if poetry else ""):
        if name.lower() != "python":
            rows.append(_row(name, version, "PyPI", "runtime", path))
    return rows


def _package_json(text: str, path: str) -> list[dict]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    rows = []
    for key, scope in (("dependencies", "runtime"), ("devDependencies", "development"), ("peerDependencies", "peer"), ("optionalDependencies", "optional")):
        for name, version in (data.get(key) or {}).items():
            rows.append(_row(name, str(version), "npm", scope, path))
    return rows


def _pom(text: str, path: str) -> list[dict]:
    rows = []
    for block in re.findall(r"(?s)<dependency>(.*?)</dependency>", text):
        group = re.search(r"<groupId>\s*([^<]+)</groupId>", block)
        artifact = re.search(r"<artifactId>\s*([^<]+)</artifactId>", block)
        version = re.search(r"<version>\s*([^<]+)</version>", block)
        scope = re.search(r"<scope>\s*([^<]+)</scope>", block)
        if group and artifact:
            rows.append(_row(f"{group.group(1).strip()}:{artifact.group(1).strip()}", version.group(1) if version else "", "Maven", (scope.group(1).strip() if scope else "compile"), path))
    return rows


def _go_mod(text: str, path: str) -> list[dict]:
    rows = []
    inside = False
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if line.startswith("require ("):
            inside = True
            continue
        if inside and line == ")":
            inside = False
            continue
        match = re.match(r"^(?:require\s+)?([\w.\-/]+\.[\w.\-/]+)\s+(v[\w.\-+]+)", line) if (inside or line.startswith("require ")) else None
        if match:
            rows.append(_row(match.group(1), match.group(2), "Go", "indirect" if "// indirect" in raw else "runtime", path))
    return rows


def _composer(text: str, path: str) -> list[dict]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    rows = []
    for key, scope in (("require", "runtime"), ("require-dev", "development")):
        for name, version in (data.get(key) or {}).items():
            if name != "php" and not name.startswith("ext-"):
                rows.append(_row(name, str(version), "Packagist", scope, path))
    return rows


def _gemfile(text: str, path: str) -> list[dict]:
    return [_row(name, version, "RubyGems", "runtime", path) for name, version in re.findall(r"(?m)^\s*gem\s+[\"']([^\"']+)[\"'](?:\s*,\s*[\"']([^\"']+)[\"'])?", text)]


PARSERS = {"requirements.txt": _requirements, "pyproject.toml": _pyproject, "package.json": _package_json, "pom.xml": _pom,
           "go.mod": _go_mod, "composer.json": _composer, "Gemfile": _gemfile}


def inventory(code: Any) -> dict:
    """Declared dependencies from every manifest of the connected source code."""
    manifests: list[dict] = []
    rows: list[dict] = []
    for path in code.paths():
        name = path.rsplit("/", 1)[-1]
        parser = PARSERS.get(name) or (PARSERS["requirements.txt"] if re.match(r"^requirements[\w.-]*\.txt$", name) else None)
        if parser is None or "node_modules/" in path:
            continue
        found = parser(code.read(path) or "", path)
        manifests.append({"path": path, "dependencies": len(found)})
        rows += found
    unpinned = sum(1 for row in rows if row["version"] == "not pinned" or row["version"].startswith(("^", "~", ">", "*", "latest")))
    return {"source": getattr(code, "label", ""), "manifests": manifests, "dependencies": rows[:1000], "total": len(rows), "unpinned": unpinned,
            "note": "Declared in the project's manifest files. Transitive packages, installed versions and known vulnerabilities are not resolved here."}
