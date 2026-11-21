"""Katalog pomiarów i krzywych docelowych AutoEq dla aplikacji Position."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from urllib.parse import quote

REPO = "repos/jaakkopasanen/AutoEq"
MAX_INDEX = 16 * 1024 * 1024
MAX_CURVE = 2 * 1024 * 1024


class ResponseTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    name: str
    source: str
    kind: str
    path: str
    local: bool
    revision: str = ""


def headphone_form(entry: Entry) -> str:
    """Rozpoznaje typ słuchawek z metadanych AutoEq: 'in-ear', 'over-ear' lub 'other'."""
    if entry.kind != "model":
        return "other"
    haystack = f"{entry.source} {entry.path}".casefold()
    if "in-ear" in haystack:
        return "in-ear"
    if "over-ear" in haystack:
        return "over-ear"
    return "other"


def measurement_source(entry: Entry) -> str:
    """Zwraca nazwę głównej bazy pomiarowej dla wpisu AutoEq."""
    return entry.source.split(" · ", 1)[0].strip()


def describe_path(relative: str, *, local_path: Path | None = None, revision: str = "") -> Entry | None:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or path.suffix.casefold() != ".csv":
        return None
    parts = path.parts
    if len(parts) == 2 and parts[0] == "targets":
        name, source, kind = path.stem, "AutoEq", "target"
    elif len(parts) >= 4 and parts[0] == "measurements" and parts[2] == "data":
        name, source, kind = path.stem, parts[1], "model"
        if len(parts) > 4:
            source += " · " + "/".join(parts[3:-1])
    else:
        return None
    return Entry(
        name, source, kind, str(local_path) if local_path is not None else relative, local_path is not None, revision
    )


def read_github(endpoint: str, limit: int, *, raw: bool = False) -> bytes:
    if shutil.which("gh") is not None:
        command = ["gh", "api", "--hostname", "github.com"]
        if raw:
            command += ["-H", "Accept: application/vnd.github.raw+json"]
        try:
            result = subprocess.run(
                [*command, endpoint], capture_output=True, timeout=18, env={**os.environ, "GH_PROMPT_DISABLED": "1"}
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("GitHub CLI przekroczył limit czasu.") from exc
        if result.returncode:
            message = result.stderr.decode(errors="replace").strip()
            raise ValueError(message or "GitHub CLI nie zwrócił danych.")
        data = result.stdout
        if len(data) > limit:
            raise ResponseTooLarge("Odpowiedź katalogu AutoEq jest większa niż dopuszczalny rozmiar.")
        return data

    url = f"https://api.github.com/{endpoint.lstrip('/')}"
    accept = "application/vnd.github.raw+json" if raw else "application/vnd.github+json"
    request = urllib.request.Request(
        url,
        headers={"Accept": accept, "User-Agent": "moondrop-position-dac"},
    )
    try:
        with urllib.request.urlopen(request, timeout=18) as response:
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"GitHub API zwróciło błąd HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"Nie udało się połączyć z GitHubem ({exc}).") from exc
    if len(data) > limit:
        raise ResponseTooLarge("Odpowiedź katalogu AutoEq jest większa niż dopuszczalny rozmiar.")
    return data


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(data)
            temporary.close()
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)


def read_tree(revision: str, *, recursive: bool = False) -> dict:
    query = "?recursive=1" if recursive else ""
    data = json.loads(read_github(f"{REPO}/git/trees/{revision}{query}", MAX_INDEX))
    if not isinstance(data, dict) or not isinstance(data.get("tree"), list):
        raise ValueError("GitHub zwrócił nieprawidłowe drzewo AutoEq.")
    return data


def tree_children(revision: str) -> list[dict]:
    data = read_tree(revision)
    if data.get("truncated"):
        raise ValueError("GitHub zwrócił niepełną listę plików pojedynczego katalogu AutoEq.")
    return data["tree"]


def catalog_blobs(revision: str, prefix: str):
    """List CSV files, splitting a truncated measurements branch by data directory."""
    if prefix == "targets":
        items = tree_children(revision)
    else:
        try:
            data = read_tree(revision, recursive=True)
        except ResponseTooLarge:
            data = {"truncated": True}
        if data.get("truncated"):
            for child in tree_children(revision):
                if child.get("type") != "tree":
                    continue
                path = f"{prefix}/{child['path']}"
                parts = PurePosixPath(path).parts
                # Each source can contain generated graphs and other assets.
                if len(parts) == 2:
                    for directory in tree_children(child["sha"]):
                        if directory.get("type") == "tree" and directory.get("path") == "data":
                            yield from catalog_blobs(directory["sha"], f"{path}/data")
                else:
                    yield from catalog_blobs(child["sha"], path)
            return
        items = data["tree"]
    for item in items:
        if item.get("type") == "blob":
            yield f"{prefix}/{item['path']}", item.get("sha", "")


def download_index(cache: Path) -> list[Entry]:
    roots = {
        item["path"]: item["sha"]
        for item in tree_children("master")
        if item.get("type") == "tree" and item.get("path") in ("measurements", "targets")
    }
    entries = [
        entry
        for prefix, revision in roots.items()
        for path, sha in catalog_blobs(revision, prefix)
        if (entry := describe_path(path, revision=sha)) is not None
    ]
    if not any(entry.kind == "model" for entry in entries):
        raise ValueError("Indeks AutoEq nie zawiera pomiarów modeli słuchawek.")
    save_index(cache, entries)
    return entries


def save_index(path: Path, entries: list[Entry]) -> None:
    atomic_write(path, json.dumps([asdict(entry) for entry in entries], ensure_ascii=False).encode())


def scan_checkout(root: Path) -> list[Entry]:
    if root.name in ("measurements", "targets"):
        root = root.parent
    entries = []
    for subtree in ("measurements", "targets"):
        for path in (root / subtree).rglob("*.csv"):
            if path.is_file():
                entry = describe_path(path.relative_to(root).as_posix(), local_path=path)
                if entry is not None:
                    entries.append(entry)
    if not entries:
        raise ValueError("Wybierz katalog repozytorium AutoEq zawierający measurements lub targets.")
    return entries


def resolve_curve(entry: Entry, cache: Path) -> Path:
    if entry.local:
        path = Path(entry.path)
        if not path.is_file():
            raise FileNotFoundError(f"Brak pliku pomiaru: {path.name}")
        return path
    if describe_path(entry.path) is None:
        raise ValueError("Nieznana ścieżka pomiaru AutoEq.")
    key = sha256(f"{entry.path}\n{entry.revision}".encode()).hexdigest()
    path = cache / f"{key}.csv"
    if not path.exists():
        if re.fullmatch("[0-9a-f]{40}", entry.revision):
            endpoint = f"{REPO}/git/blobs/{entry.revision}"
        else:
            endpoint = f"{REPO}/contents/{quote(entry.path)}?ref=master"
        data = read_github(endpoint, MAX_CURVE, raw=True)
        atomic_write(path, data)
    return path
