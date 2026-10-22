import hashlib
import json
import logging
import os
import re
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from api.service import Store


logger = logging.getLogger("azdemy.publication")
FILES = ("courses.synthetic.json", "learners.synthetic.json", "recommendations.synthetic.json")


def safe_name(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", value) is None:
        raise ValueError("Invalid publication identifier")
    return value


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def publication_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".publish.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def write_manifest(directory: Path) -> dict:
    snapshot = json.loads((directory / FILES[2]).read_text(encoding="utf-8"))
    manifest = {
        "schema_version": 1, "version": safe_name(snapshot["data_version"]),
        "files": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                  for name in FILES},
    }
    atomic_json(directory / "manifest.json", manifest)
    return manifest


def validate_directory(directory: Path) -> tuple[Store, dict]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != 1
            or set(manifest.get("files", {})) != set(FILES)):
        raise ValueError("Invalid release manifest")
    safe_name(manifest["version"])
    for name in FILES:
        path = directory / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != manifest["files"][name]:
            raise ValueError(f"Release checksum mismatch: {name}")
    store = Store(directory)
    if store.snapshot.data_version != manifest["version"]:
        raise ValueError("Release version mismatch")
    return store, manifest


def stage_release(root: Path, source: Path) -> str:
    _, manifest = validate_directory(source)
    version = manifest["version"]
    with publication_lock(root):
        releases = root / "releases"
        releases.mkdir(exist_ok=True)
        target = releases / version
        if target.exists():
            _, existing = validate_directory(target)
            if existing != manifest:
                raise ValueError("Conflicting immutable release version")
            return version
        with TemporaryDirectory(prefix="stage-", dir=root) as temporary:
            stage = Path(temporary) / "release"
            stage.mkdir()
            for name in (*FILES, "manifest.json"):
                shutil.copyfile(source / name, stage / name)
            validate_directory(stage)
            os.rename(stage, target)
    return version


def _read_pointer(root: Path) -> dict:
    pointer = root / "active.json"
    if not pointer.exists():
        return {}
    value = json.loads(pointer.read_text(encoding="utf-8"))
    safe_name(value["version"])
    return value


def read_active_pointer(root: Path) -> dict:
    with publication_lock(root):
        return _read_pointer(root)


def active_version(root: Path) -> str | None:
    return read_active_pointer(root).get("version")


def load_release(root: Path, version: str, now: datetime) -> Store:
    safe_name(version)
    store, _ = validate_directory(root / "releases" / version)
    return store


def activate_release(root: Path, version: str, expected_current: str | None, now: datetime) -> None:
    with publication_lock(root):
        store = load_release(root, version, now)
        if not store.snapshot.generated_at <= now <= store.snapshot.valid_until:
            raise ValueError("Cannot activate future or expired release")
        current = _read_pointer(root).get("version")
        if current != expected_current:
            raise ValueError("Active version changed; publication compare-and-swap rejected")
        if current == version:
            return
        atomic_json(root / "active.json", {"version": version, "previous": current})


def read_active_store(root: Path, now: datetime) -> Store:
    version = active_version(root)
    if version is None:
        raise ValueError("No active published release")
    return load_release(root, version, now)


def process_pending(root: Path, now: datetime) -> dict | None:
    pending = root / "pending.json"
    if not pending.exists():
        return None
    try:
        raw = pending.read_bytes()
        request = json.loads(raw)
        if set(request) != {"request_id", "version", "expected_current", "incoming"}:
            raise ValueError("Invalid publication request shape")
        request_id = safe_name(request["request_id"])
        safe_name(request["version"])
        safe_name(request["incoming"])
        if request["expected_current"] is not None:
            safe_name(request["expected_current"])
        request_hash = hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.error("Malformed pending publication; active version unchanged: %s", error)
        result = {"status": "failed", "error": f"{type(error).__name__}: {error}"}
        atomic_json(root / "invalid-request.json", result)
        return result
    results = root / "requests"
    results.mkdir(exist_ok=True)
    result_path = results / f"{request_id}.json"
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("request_hash") != request_hash:
            error = "Publication request ID reused with different input"
            logger.error("Snapshot activation rejected request_id=%s: %s", request_id, error)
            rejected = {"request_id": request_id, "status": "failed", "error": error}
            atomic_json(root / "invalid-request.json", rejected)
            return rejected
        return result
    result = {"request_id": request_id, "request_hash": request_hash,
              "version": request["version"], "status": "failed"}
    try:
        source = root / "incoming" / safe_name(request["incoming"])
        version = stage_release(root, source)
        if version != request["version"]:
            raise ValueError("Publication request version mismatch")
        store = load_release(root, version, now)
        if not store.snapshot.generated_at <= now <= store.snapshot.valid_until:
            raise ValueError("Cannot activate future or expired release")
        pointer = read_active_pointer(root)
        already_active = (pointer.get("version") == version
                          and pointer.get("previous") == request["expected_current"])
        if not already_active:
            activate_release(root, version, request["expected_current"], now)
        result["status"] = "completed"
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.error("Snapshot activation failed request_id=%s: %s", request_id, error)
        result["error"] = f"{type(error).__name__}: {error}"
    atomic_json(result_path, result)
    return result
