"""Katalog pomiarów i krzywych docelowych AutoEq dla aplikacji Position."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import urllib.error
import urllib.request
import zlib
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from urllib.parse import quote

GIT_REPO_URL = "https://github.com/jaakkopasanen/AutoEq.git"
RAW_BASE_URL = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master"
MAX_INDEX = 16 * 1024 * 1024
MAX_CURVE = 2 * 1024 * 1024
OBJ_COMMIT = 1
OBJ_TREE = 2
OBJ_BLOB = 3
OBJ_TAG = 4
OBJ_OFS_DELTA = 6
OBJ_REF_DELTA = 7
_TYPE_NAMES = {OBJ_COMMIT: "commit", OBJ_TREE: "tree", OBJ_BLOB: "blob", OBJ_TAG: "tag"}


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


def _read_https(
    url: str,
    limit: int,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> bytes:
    request_headers = {"User-Agent": "dsp-control"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Serwer AutoEq zwrócił błąd HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"Nie udało się połączyć z repozytorium AutoEq ({exc}).") from exc
    if len(payload) > limit:
        raise ResponseTooLarge("Odpowiedź katalogu AutoEq jest większa niż dopuszczalny rozmiar.")
    return payload


def read_raw(relative: str, limit: int = MAX_CURVE) -> bytes:
    """Pobiera pojedynczy plik z gałęzi master repozytorium AutoEq bez użycia REST API GitHuba."""
    if describe_path(relative) is None:
        raise ValueError("Nieznana ścieżka pomiaru AutoEq.")
    return _read_https(f"{RAW_BASE_URL}/{quote(relative)}", limit, timeout=18)


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


def _pkt_line(payload: bytes) -> bytes:
    return f"{len(payload) + 4:04x}".encode() + payload


def _iter_pkt_lines(data: bytes):
    pos = 0
    while pos + 4 <= len(data):
        length = int(data[pos : pos + 4], 16)
        pos += 4
        if length == 0:
            yield None
            continue
        if length < 4 or pos + length - 4 > len(data):
            raise ValueError("Nieprawidłowa ramka protokołu Git podczas odczytu AutoEq.")
        yield data[pos : pos + length - 4]
        pos += length - 4


def _fetch_master_oid() -> str:
    refs_raw = _read_https(f"{GIT_REPO_URL}/info/refs?service=git-upload-pack", MAX_INDEX, timeout=18)
    for pkt in _iter_pkt_lines(refs_raw):
        if not pkt or pkt.startswith(b"#"):
            continue
        line = pkt.split(b"\x00", 1)[0].strip()
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1] == b"refs/heads/master":
            oid = parts[0].decode("ascii", errors="strict")
            if re.fullmatch(r"[0-9a-f]{40}", oid):
                return oid
    raise ValueError("Repozytorium AutoEq nie zwróciło referencji gałęzi master.")


def _fetch_tree_pack(oid: str) -> bytes:
    body = (
        _pkt_line(f"want {oid} no-progress ofs-delta filter\n".encode())
        + _pkt_line(b"filter blob:none\n")
        + _pkt_line(b"deepen 1\n")
        + b"0000"
        + _pkt_line(b"done\n")
    )
    response = _read_https(
        f"{GIT_REPO_URL}/git-upload-pack",
        MAX_INDEX,
        data=body,
        headers={"Content-Type": "application/x-git-upload-pack-request"},
        timeout=30,
    )
    pack_offset = response.find(b"PACK")
    if pack_offset < 0:
        raise ValueError("Repozytorium AutoEq nie zwróciło paczki drzewa katalogu.")
    return response[pack_offset:]


def _read_delta_varint(delta: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while pos < len(delta):
        byte = delta[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, pos
        shift += 7
    raise ValueError("Nieprawidłowy nagłówek delta w paczce AutoEq.")


def _apply_git_delta(base: bytes, delta: bytes) -> bytes:
    pos = 0
    _src_len, pos = _read_delta_varint(delta, pos)
    dst_len, pos = _read_delta_varint(delta, pos)
    out = bytearray()
    while pos < len(delta):
        cmd = delta[pos]
        pos += 1
        if cmd & 0x80:
            cp_off = 0
            cp_size = 0
            for idx in range(4):
                if cmd & (1 << idx):
                    cp_off |= delta[pos] << (8 * idx)
                    pos += 1
            for idx in range(3):
                if cmd & (1 << (4 + idx)):
                    cp_size |= delta[pos] << (8 * idx)
                    pos += 1
            if cp_size == 0:
                cp_size = 0x10000
            out.extend(base[cp_off : cp_off + cp_size])
        elif cmd:
            out.extend(delta[pos : pos + cmd])
            pos += cmd
        else:
            raise ValueError("Nieprawidłowy opcode delta w paczce AutoEq.")
    if len(out) != dst_len:
        raise ValueError("Nieprawidłowy rozmiar obiektu delta w paczce AutoEq.")
    return bytes(out)


def _unpack_pack_objects(pack: bytes) -> dict[str, tuple[int, bytes]]:
    if len(pack) < 32 or pack[:4] != b"PACK":
        raise ValueError("Nieprawidłowy nagłówek paczki AutoEq.")
    version, count = struct.unpack(">II", pack[4:12])
    if version != 2:
        raise ValueError(f"Nieobsługiwana wersja paczki Git: {version}.")
    if hashlib.sha1(pack[:-20]).digest() != pack[-20:]:
        raise ValueError("Suma kontrolna paczki AutoEq jest nieprawidłowa.")

    payload_end = len(pack) - 20
    objects_by_offset: dict[int, tuple[int, bytes]] = {}
    objects_by_sha: dict[str, tuple[int, bytes]] = {}
    pos = 12
    for _ in range(count):
        if pos >= payload_end:
            raise ValueError("Paczka AutoEq została obcięta.")
        obj_offset = pos
        byte = pack[pos]
        pos += 1
        obj_type = (byte >> 4) & 7
        while byte & 0x80:
            byte = pack[pos]
            pos += 1
        if obj_type == OBJ_OFS_DELTA:
            c = pack[pos]
            pos += 1
            back = c & 0x7F
            while c & 0x80:
                c = pack[pos]
                pos += 1
                back = ((back + 1) << 7) | (c & 0x7F)
            base_type, base_data = objects_by_offset[obj_offset - back]
            decomp = zlib.decompressobj()
            delta = decomp.decompress(pack[pos:payload_end])
            pos = payload_end - len(decomp.unused_data)
            data = _apply_git_delta(base_data, delta)
            real_type = base_type
        elif obj_type == OBJ_REF_DELTA:
            base_sha = pack[pos : pos + 20].hex()
            pos += 20
            base_type, base_data = objects_by_sha[base_sha]
            decomp = zlib.decompressobj()
            delta = decomp.decompress(pack[pos:payload_end])
            pos = payload_end - len(decomp.unused_data)
            data = _apply_git_delta(base_data, delta)
            real_type = base_type
        else:
            decomp = zlib.decompressobj()
            data = decomp.decompress(pack[pos:payload_end])
            pos = payload_end - len(decomp.unused_data)
            real_type = obj_type
        type_name = _TYPE_NAMES.get(real_type)
        if type_name is None:
            raise ValueError(f"Nieznany typ obiektu Git: {real_type}.")
        sha = hashlib.sha1(f"{type_name} {len(data)}\0".encode() + data).hexdigest()
        objects_by_offset[obj_offset] = (real_type, data)
        objects_by_sha[sha] = (real_type, data)
    if pos != payload_end:
        raise ValueError("Nieoczekiwane dane na końcu paczki AutoEq.")
    return objects_by_sha


def _parse_tree(tree_bytes: bytes):
    pos = 0
    while pos < len(tree_bytes):
        space = tree_bytes.index(b" ", pos)
        mode = tree_bytes[pos:space].decode("ascii")
        nul = tree_bytes.index(b"\0", space + 1)
        name = tree_bytes[space + 1 : nul].decode("utf-8", errors="strict")
        sha = tree_bytes[nul + 1 : nul + 21].hex()
        pos = nul + 21
        yield mode, name, sha


def _walk_tree(objects: dict[str, tuple[int, bytes]], tree_sha: str, prefix: str):
    obj_type, data = objects[tree_sha]
    if obj_type != OBJ_TREE:
        raise ValueError("Nieprawidłowy wpis drzewa w katalogu AutoEq.")
    for mode, name, sha in _parse_tree(data):
        path = f"{prefix}/{name}" if prefix else name
        if mode == "40000":
            yield from _walk_tree(objects, sha, path)
        else:
            yield path, sha


def fetch_repo_tree() -> tuple[dict[str, tuple[int, bytes]], str]:
    """Pobiera drzewo katalogów AutoEq przez Git Smart HTTP (filter blob:none)."""
    head_oid = _fetch_master_oid()
    pack = _fetch_tree_pack(head_oid)
    objects = _unpack_pack_objects(pack)
    obj_type, commit_data = objects.get(head_oid, (0, b""))
    if obj_type != OBJ_COMMIT:
        raise ValueError("Brak obiektu commita w paczce AutoEq.")
    root_tree_sha = next(
        (line.split()[1].decode("ascii") for line in commit_data.splitlines() if line.startswith(b"tree ")),
        "",
    )
    if not re.fullmatch(r"[0-9a-f]{40}", root_tree_sha):
        raise ValueError("Commit AutoEq nie wskazuje poprawnego drzewa plików.")
    return objects, root_tree_sha


def download_index(cache: Path) -> list[Entry]:
    """Pobiera aktualny indeks AutoEq przez HTTPS bez limitów REST API GitHuba i zapisuje go atomowo."""
    objects, root_tree_sha = fetch_repo_tree()
    _, root_data = objects[root_tree_sha]
    roots = {
        name: sha
        for mode, name, sha in _parse_tree(root_data)
        if mode == "40000" and name in ("measurements", "targets")
    }
    if roots.keys() != {"measurements", "targets"}:
        raise ValueError("Repozytorium zwróciło niepełną strukturę katalogu AutoEq.")
    entries = [
        entry
        for prefix, revision in roots.items()
        for path, sha in _walk_tree(objects, revision, prefix)
        if (entry := describe_path(path, revision=sha)) is not None
    ]
    if {entry.kind for entry in entries} != {"model", "target"}:
        raise ValueError("Indeks AutoEq musi zawierać pomiary modeli słuchawek i krzywe docelowe.")
    save_index(cache, entries)
    return entries


def load_index(path: Path) -> list[Entry]:
    """Wczytuje i waliduje zapisany indeks JSON katalogu AutoEq."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Indeks AutoEq musi być listą wpisów.")
    return [Entry(**item) for item in raw]


def save_index(path: Path, entries: list[Entry]) -> None:
    payload = json.dumps([asdict(entry) for entry in entries], ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    atomic_write(path, payload)


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


def resolve_curve(entry: Entry, cache: Path, *, bundled_targets: Path | None = None) -> Path:
    if entry.local:
        path = Path(entry.path)
        if not path.is_file():
            raise FileNotFoundError(f"Brak pliku pomiaru: {path.name}")
        return path
    parsed = describe_path(entry.path)
    if parsed is None:
        raise ValueError("Nieznana ścieżka pomiaru AutoEq.")
    if bundled_targets is not None and parsed.kind == "target":
        local_target = bundled_targets / PurePosixPath(entry.path).name
        if local_target.is_file():
            return local_target
    key = sha256(f"{entry.path}\n{entry.revision}".encode()).hexdigest()
    path = cache / f"{key}.csv"
    if not path.exists():
        data = read_raw(entry.path, MAX_CURVE)
        atomic_write(path, data)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Narzędzie indeksu AutoEq.")
    parser.add_argument("--write-index", type=Path, required=True, help="Zapisz bieżący indeks AutoEq do pliku JSON.")
    args = parser.parse_args(argv)
    entries = download_index(args.write_index)
    models = sum(1 for entry in entries if entry.kind == "model")
    targets = sum(1 for entry in entries if entry.kind == "target")
    print(f"Zapisano {len(entries)} wpisów ({models} modeli, {targets} targetów) -> {args.write_index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
