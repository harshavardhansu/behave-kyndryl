"""What a person can hand to an engineering task: logs, a source file, a project ZIP or a GitHub repository.

- ``inspect_zip`` checks an uploaded archive **without unpacking it**: no entry may point outside the
  archive (path traversal), be a link or be encrypted; size, entry count and compression ratio are
  capped (zip bombs). Only source/configuration files and logs are ever read from it.
- ``TaskStorage`` keeps the uploaded sources of one task on the server's data disk, under a name the
  server chooses (never a name from the upload).
- ``UploadedCode`` is the connector that lets the agents' read-only tools read those sources exactly
  like a GitHub repository.
- ``profile_project`` works out what the project is (languages, frameworks, entry points, tests,
  dependency files) from its files, so nothing has to be guessed.

Uploaded content is untrusted data. It is never executed, and it is never given to an AI model
without redaction.
"""

import io
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

from .connectors import MAX_FILE_BYTES, MAX_FILES, NoCode, readable

MAX_ZIP_ENTRIES = 5000
MAX_UNPACKED_BYTES = 80_000_000
MAX_RATIO = 200                      # unpacked / packed size of one entry
MAX_LOG_MEMBERS = 10
LOG_SUFFIXES = {".log", ".out", ".err", ".jsonl"}
INCIDENT_ID = re.compile(r"^INC-[A-Za-z0-9]{1,40}$")

LANGUAGES = {
    ".py": "Python", ".java": "Java", ".kt": "Kotlin", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".php": "PHP", ".go": "Go", ".cs": "C#", ".rb": "Ruby", ".rs": "Rust", ".swift": "Swift",
    ".scala": "Scala", ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".sh": "Shell",
}
MANIFESTS = {"requirements.txt", "pyproject.toml", "Pipfile", "setup.py", "package.json", "pom.xml", "build.gradle", "build.gradle.kts",
             "go.mod", "Cargo.toml", "composer.json", "Gemfile", "Dockerfile", "Containerfile"}
ENTRY_NAMES = {"manage.py", "app.py", "main.py", "wsgi.py", "asgi.py", "server.js", "index.js", "app.js", "main.go", "Program.cs", "index.php", "Application.java", "Main.java"}
FRAMEWORK_MARKS = [
    ("Django", r"\bdjango\b"), ("FastAPI", r"\bfastapi\b"), ("Flask", r"\bflask\b"), ("Express", r'"express"'), ("React", r'"react"'),
    ("Next.js", r'"next"'), ("Vue", r'"vue"'), ("Angular", r'"@angular/core"'), ("NestJS", r'"@nestjs/core"'), ("Spring Boot", r"spring-boot"),
    ("Laravel", r"laravel/framework"), ("Gin", r"gin-gonic/gin"), ("ASP.NET", r"Microsoft\.AspNetCore"), ("Rails", r"\brails\b"),
]
TEST_MARKS = [("pytest", r"\bpytest\b"), ("unittest", r"\bimport unittest\b"), ("Jest", r'"jest"'), ("Vitest", r'"vitest"'), ("Mocha", r'"mocha"'),
              ("JUnit", r"junit"), ("Playwright", r"playwright"), ("Go test", r"_test\.go$")]


class UnsafeArchive(ValueError):
    """The archive is refused. The message is safe to show to the person who uploaded it."""


def _clean_name(name: str) -> str | None:
    """A normalised relative path, or None for an entry that must be skipped. Raises for an unsafe one."""
    if "\x00" in name or name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name):
        raise UnsafeArchive("The archive contains an absolute path. Re-create it from inside the project folder.")
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if ".." in parts:
        raise UnsafeArchive("The archive contains a path that points outside it ('..'). It was refused.")
    if not parts or parts[0] == "__MACOSX" or name.endswith("/"):
        return None
    return "/".join(parts)


def inspect_zip(content: bytes) -> dict:
    """Read an uploaded ZIP safely. Returns {"sources": {path: text}, "logs": {path: text}, "skipped": n, "entries": n}."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, ValueError):
        raise UnsafeArchive("The file is not a valid ZIP archive.") from None
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise UnsafeArchive(f"The archive has more than {MAX_ZIP_ENTRIES} entries.")
        if sum(info.file_size for info in infos) > MAX_UNPACKED_BYTES:
            raise UnsafeArchive("The archive is too large when unpacked (limit 80 MB).")
        members: list[tuple[str, zipfile.ZipInfo]] = []
        for info in infos:
            name = _clean_name(info.filename)
            if name is None:
                continue
            if info.flag_bits & 0x1:
                raise UnsafeArchive("The archive is password-protected. Upload it without a password.")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                continue  # a symbolic link is never followed
            if info.file_size > 1_000_000 and info.file_size > MAX_RATIO * max(info.compress_size, 1):
                raise UnsafeArchive("The archive contains a suspiciously compressed file. It was refused.")
            members.append((name, info))
        tops = {name.split("/")[0] for name, _ in members if "/" in name}
        strip = f"{next(iter(tops))}/" if len(tops) == 1 and all("/" in name for name, _ in members) else ""  # one wrapping folder
        sources: dict[str, str] = {}
        logs: dict[str, str] = {}
        skipped = 0
        for name, info in sorted(members, key=lambda item: item[0]):
            path = name[len(strip):] if strip else name
            suffix = Path(path).suffix.lower()
            is_log = suffix in LOG_SUFFIXES or (suffix == ".txt" and "log" in path.lower())
            wanted = (is_log and len(logs) < MAX_LOG_MEMBERS) or (readable(path) and len(sources) < MAX_FILES)
            if not wanted or info.file_size > (2_000_000 if is_log else MAX_FILE_BYTES) or info.file_size == 0:
                skipped += 1
                continue
            with archive.open(info) as handle:
                data = handle.read(info.file_size + 1)
            if b"\x00" in data[:4096]:
                skipped += 1  # binary
                continue
            (logs if is_log else sources)[path] = data.decode("utf-8", errors="replace")
        return {"sources": sources, "logs": logs, "skipped": skipped, "entries": len(members)}


def pack_sources(sources: dict[str, str]) -> bytes:
    """Store only the files that were accepted, as a fresh archive written by the server."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, text in sources.items():
            archive.writestr(path, text)
    return buffer.getvalue()


class TaskStorage:
    """Uploaded sources of engineering tasks, on the server's data disk."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def folder(self, incident_id: str) -> Path:
        if not INCIDENT_ID.match(incident_id):
            raise ValueError("Invalid task identifier.")
        return self.root / incident_id

    def save(self, incident_id: str, upload_id: str, sources: dict[str, str]) -> Path:
        if not re.match(r"^[A-Za-z0-9-]{1,60}$", upload_id):
            raise ValueError("Invalid upload identifier.")
        folder = self.folder(incident_id)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{upload_id}.zip"
        target.write_bytes(pack_sources(sources))
        return target

    def files(self, incident_id: str) -> dict[str, str]:
        """Every stored source file of the task; a later upload replaces an earlier file of the same path."""
        try:
            folder = self.folder(incident_id)
        except ValueError:
            return {}
        merged: dict[str, str] = {}
        for stored in sorted(folder.glob("*.zip"), key=lambda path: path.stat().st_mtime) if folder.is_dir() else []:
            try:
                with zipfile.ZipFile(stored) as archive:
                    for info in archive.infolist():
                        merged[info.filename] = archive.read(info).decode("utf-8", errors="replace")
            except (zipfile.BadZipFile, OSError):
                continue
        return dict(sorted(merged.items()))


class UploadedCode(NoCode):
    """The source files a person uploaded for one task, readable through the same tools as a repository."""

    def __init__(self, storage: TaskStorage, incident_id: str):
        self.storage = storage
        self.incident_id = incident_id
        self.label = "uploaded source files"
        self._cache: dict[str, str] | None = None

    def _files(self) -> dict[str, str]:
        if self._cache is None:
            self._cache = self.storage.files(self.incident_id)
        return self._cache

    def paths(self) -> list[str]:
        return list(self._files())

    def read(self, path: str) -> str | None:
        return self._files().get(path)


def profile_project(code) -> dict:
    """What the connected source is: languages, frameworks, entry points, dependency files and tests."""
    paths = code.paths()
    if not paths:
        return {"files": 0, "languages": [], "frameworks": [], "entryPoints": [], "manifests": [], "tests": {"frameworks": [], "files": 0}}
    counts: dict[str, int] = {}
    for path in paths:
        language = LANGUAGES.get(Path(path).suffix.lower())
        if language:
            counts[language] = counts.get(language, 0) + 1
    manifests = [path for path in paths if path.rsplit("/", 1)[-1] in MANIFESTS][:12]
    manifest_text = "\n".join((code.read(path) or "")[:20000] for path in manifests)
    entry = [path for path in paths if path.rsplit("/", 1)[-1] in ENTRY_NAMES][:8]
    manifest_text += "\n" + "\n".join((code.read(path) or "")[:3000] for path in entry)  # e.g. manage.py names Django
    for path in manifests:
        if path.endswith("package.json"):
            try:
                package = json.loads(code.read(path) or "{}")
                start = (package.get("scripts") or {}).get("start") or package.get("main")
                if isinstance(start, str) and f"{path}: {start}" not in entry:
                    entry.append(f"{path}: {start}"[:120])
            except ValueError:
                pass
    test_files = [path for path in paths if re.search(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$|Tests?\.java$", path)]
    sample = manifest_text + "\n".join((code.read(path) or "")[:2000] for path in test_files[:5]) + "\n".join(test_files)
    return {
        "files": len(paths),
        "languages": [{"name": name, "files": number} for name, number in sorted(counts.items(), key=lambda item: -item[1])][:8],
        "frameworks": [name for name, pattern in FRAMEWORK_MARKS if re.search(pattern, manifest_text, re.IGNORECASE)],
        "entryPoints": entry[:8],
        "manifests": manifests,
        "tests": {"frameworks": [name for name, pattern in TEST_MARKS if re.search(pattern, sample, re.IGNORECASE)], "files": len(test_files)},
        "source": getattr(code, "label", ""),
    }
