"""Coordinator-owned encrypted candidate reservations. No bug plaintext leaves workers.

Reservations are serialized before semantic screening: each worker screens against
all earlier reservations. Later workers must consider earlier pending candidates too.
The caller transports the exported directory over the trusted worker channel.
"""
import argparse
import fcntl
import hashlib
import json
import os
import pathlib
import re
import secrets
import tempfile


def atomic_json(path, value):
    path = pathlib.Path(path)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        try:
            json.dump(value, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
            os.replace(f.name, path)
        finally:
            pathlib.Path(f.name).unlink(missing_ok=True)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def identifier(value):
    if not re.fullmatch(r"case-[A-Za-z0-9-]+", value):
        raise ValueError("invalid case identifier")
    return value


class Registry:
    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        (self.root / "objects").mkdir(mode=0o700, exist_ok=True)

    def reserve(self, case, statement_sha256, ciphertext, expected_revision=None, *, historical=False):
        identifier(case)
        if not (historical and statement_sha256 is None) and not re.fullmatch(r"[0-9a-f]{64}", statement_sha256 or ""):
            raise ValueError("invalid statement digest")
        data = pathlib.Path(ciphertext).read_bytes()
        if not data.startswith((b"age-encryption.org/v1", b"-----BEGIN AGE ENCRYPTED FILE-----")):
            raise ValueError("statement must be age ciphertext")
        digest = hashlib.sha256(data).hexdigest()
        with (self.root / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.root / "registry.json"
            state = json.loads(path.read_text()) if path.exists() else {"revision": 0, "entries": {}}
            previous = state["entries"].get(case)
            # A candidate that an earlier handoff imported as history is promoted here:
            # same identity, recomputed predecessors, fresh reservation.
            promote = bool(previous and previous["status"] == "completed" and not historical and
                           not previous["complete"] and (previous["statement_sha256"] == statement_sha256 or
                           previous["statement_sha256"] is None and previous["cipher_sha256"] == digest))
            if promote:
                digest = previous["cipher_sha256"]
            elif previous and previous["status"] != "released":
                if previous["statement_sha256"] == statement_sha256 and statement_sha256 is not None:
                    # age uses fresh randomness on each seal. Keep the already stored
                    # ciphertext when the trusted worker reports identical plaintext.
                    return previous
                if historical and previous["cipher_sha256"] == digest:
                    return previous
                if previous["statement_sha256"] != statement_sha256 or previous["cipher_sha256"] != digest:
                    raise ValueError("case already reserved with different content")
                return previous
            if expected_revision is not None and expected_revision != state["revision"]:
                raise ValueError("registry changed; refresh before reserving")
            earlier = {k: v["cipher_sha256"] for k, v in state["entries"].items()
                       if v["status"] != "released" and k != case}
            revision = state["revision"] + 1
            entry = {"version": 1, "case_id": case, "statement_sha256": statement_sha256,
                     "cipher_sha256": digest, "complete": not historical, "reservation": secrets.token_hex(16),
                     "registry_revision": revision, "statements": earlier,
                     "status": "completed" if historical else "screening"}
            obj = self.root / "objects" / (digest + ".age")
            if obj.exists() and hashlib.sha256(obj.read_bytes()).hexdigest() != digest:
                raise ValueError("registry object corrupted")
            if promote and not obj.exists():
                raise ValueError("registry object corrupted")
            if not obj.exists():
                with obj.open("xb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
            state["entries"][case] = entry
            state["revision"] = revision
            atomic_json(path, state)
            return entry

    def import_historical(self, case, ciphertext, statement_sha256=None):
        return self.reserve(case, statement_sha256, ciphertext, historical=True)

    def replace_rejected(self, case, statement_sha256, ciphertext, rejected, *, historical=False):
        """Only an explicitly rejected previous digest permits candidate reselection."""
        if not re.fullmatch(r"[0-9a-f]{64}", statement_sha256 or "") or not pathlib.Path(ciphertext).read_bytes().startswith(
                (b"age-encryption.org/v1", b"-----BEGIN AGE ENCRYPTED FILE-----")):
            return self.reserve(case, statement_sha256, ciphertext, historical=historical)  # refuses before any release
        for attempt in (0, 1):  # the decision is unlocked; one concurrent release/reselect is retried
            state = json.loads((self.root / "registry.json").read_text()) if (self.root / "registry.json").exists() else {"entries": {}}
            previous = state["entries"].get(case)
            old = previous and previous["statement_sha256"]
            # A historical-only entry with an unknown digest falls through to reserve (promotion or refusal).
            if (previous and previous["status"] != "released" and old != statement_sha256 and
                    (previous["complete"] or old is not None)):
                if old is None or old not in rejected or (previous["complete"] and previous["status"] not in ("screening", "building")):
                    raise ValueError("case already reserved with different content")
                try:
                    self.transition(case, previous["reservation"], "released")
                except ValueError as error:
                    if attempt or "stale reservation" not in str(error): raise
                    continue
            return self.reserve(case, statement_sha256, ciphertext, historical=historical)

    def search_receipt(self, case, metadata, ciphertext):
        """Keep opaque worker evidence; the worker validates its verdict and expiry."""
        data = pathlib.Path(ciphertext).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if not data.startswith((b"age-encryption.org/v1", b"-----BEGIN AGE ENCRYPTED FILE-----")):
            raise ValueError("search receipt must be age ciphertext")
        with (self.root / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.root / "registry.json"; state = json.loads(path.read_text())
            entry = state["entries"][identifier(case)]
            binding = metadata.get("binding", {})
            if (metadata.get("cipher_sha256") != digest or binding.get("case_id") != case or
                    binding.get("statement_sha256") != entry["statement_sha256"] or
                    binding.get("reservation") != {k: entry[k] for k in ("reservation", "registry_revision")} or
                    entry["status"] == "released"):
                raise ValueError("stale search receipt")
            obj = self.root / "objects" / (digest + ".age")
            if not obj.exists(): obj.write_bytes(data)
            entry["search_sha256"] = digest
            atomic_json(path, state)

    def export(self, case, destination):
        """Export a fixed reservation snapshot; destination must be new."""
        identifier(case)
        with (self.root / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            entry = json.loads((self.root / "registry.json").read_text())["entries"][case]
            if entry["status"] == "released" or not entry["complete"]:
                raise ValueError("reservation released or historical-only")
            destination = pathlib.Path(destination)
            destination.mkdir(mode=0o700, parents=True, exist_ok=False)
            for other, digest in entry["statements"].items():
                data = (self.root / "objects" / (digest + ".age")).read_bytes()
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError("registry object corrupted")
                (destination / (identifier(other) + ".statement.age")).write_bytes(data)
            if entry.get("search_sha256"):
                data = (self.root / "objects" / (entry["search_sha256"] + ".age")).read_bytes()
                if hashlib.sha256(data).hexdigest() != entry["search_sha256"]: raise ValueError("search object corrupted")
                (destination / "search.age").write_bytes(data)
            atomic_json(destination / "admission.json", entry)
            return entry

    def export_board(self, destination):
        """Advisory occupied statements before selection; never a reservation."""
        with (self.root / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            state = json.loads((self.root / "registry.json").read_text())
            statements = {identifier(case): entry["cipher_sha256"]
                          for case, entry in state["entries"].items() if entry["status"] != "released"}
            destination = pathlib.Path(destination)
            destination.mkdir(mode=0o700, parents=True, exist_ok=False)
            for case, digest in statements.items():
                obj = self.root / "objects" / (digest + ".age")
                if obj.is_symlink() or hashlib.sha256(obj.read_bytes()).hexdigest() != digest:
                    raise ValueError("registry object corrupted")
                (destination / (case + ".statement.age")).write_bytes(obj.read_bytes())
            board = {"version": 1, "scope": "selection_only", "complete": True,
                     "registry_revision": state["revision"], "statements": statements}
            atomic_json(destination / "selection-board.json", board)
            return board

    def transition(self, case, reservation, status):
        if status not in {"building", "completed", "known_public", "released"}:
            raise ValueError("invalid registry status")
        identifier(case)
        with (self.root / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.root / "registry.json"
            state = json.loads(path.read_text())
            entry = state["entries"][case]
            if entry["reservation"] != reservation or entry["status"] == "released":
                raise ValueError("stale reservation")
            entry["status"] = status
            state["revision"] += 1
            atomic_json(path, state)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True)
    sub = p.add_subparsers(dest="command", required=True)
    reserve = sub.add_parser("reserve")
    reserve.add_argument("case")
    reserve.add_argument("statement_sha256")
    reserve.add_argument("ciphertext")
    reserve.add_argument("--expected-revision", type=int)
    export = sub.add_parser("export")
    export.add_argument("case")
    export.add_argument("destination")
    change = sub.add_parser("transition")
    change.add_argument("case")
    change.add_argument("reservation")
    change.add_argument("status")
    history = sub.add_parser("import-historical")
    history.add_argument("case")
    history.add_argument("ciphertext")
    a = p.parse_args()
    registry = Registry(a.root)
    if a.command == "reserve":
        print(json.dumps(registry.reserve(a.case, a.statement_sha256, a.ciphertext, a.expected_revision)))
    elif a.command == "export":
        registry.export(a.case, a.destination)
    elif a.command == "import-historical":
        registry.import_historical(a.case, a.ciphertext)
    else:
        registry.transition(a.case, a.reservation, a.status)


if __name__ == "__main__":
    main()
