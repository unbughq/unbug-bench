"""Archive and plaintext lifecycle for one factory run.

Owns evidence collection, atomic encryption and cleanup ordering. The composition
root supplies deployment paths and the pilot/retained-delivery operations.
"""
import hashlib
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import processes
import slot_state


def shred_tree(path, sudo=False):
    if sudo:  # inside an isolated user's private home the runner cannot even stat the path: let root do it all
        processes.run(["sudo", "sh", "-c", 'if [ -f "$1" ]; then shred -u -z "$1"; elif [ -d "$1" ]; then '
                        'find "$1" -type f -exec shred -u -z {} +; rm -rf "$1"; fi', "sh", str(path)], capture_output=True)
        return
    if not path.exists(): return
    if path.is_file(): processes.run(["shred", "-u", "-z", str(path)], capture_output=True)
    else:
        processes.run(["find", str(path), "-type", "f", "-exec", "shred", "-u", "-z", "{}", "+"], capture_output=True)
        processes.run(["rm", "-rf", str(path)], capture_output=True)



@dataclass
class RunArtifacts:
    home: Path
    bench: Path
    sealed: Path
    statements_recipient: Path
    agent_state: tuple
    pilot_homes: Callable
    pilot_wall: Callable
    factory_slots: Callable
    retain_delivery: Callable
    cleanup: Callable = shred_tree

    def results_since(self, c, *, include_state=False):
        """Bench files written during this run: evidence only, unless include_state (the wipe).
        slot_state.is_state names what a slot or a running bench still uses (readiness receipt, compose
        and port overrides, inventory services, pending decisions, temporaries, progress, seed IDs); the
        gather leaves it, as gate_state.inventory does. The lock and seed IDs stay even for the wipe.
        Written since t0 by ctime, not mtime: bench.py freezes inventory services with shutil.copytree, which
        keeps the case files' old mtimes (8acb5c, 19 November: those copies stayed out of the snapshot, so
        G13-G15 missed their evidence on every restored attempt, and the wipe left them on the bench)."""
        results = self.bench / "results"
        def kept(rel):
            return (slot_state.always_kept(rel.as_posix())
                    or (not include_state and slot_state.is_state(rel.as_posix())))
        return [f for f in results.rglob("*") if f.is_file() and f.stat().st_ctime >= c.t0
                and not kept(f.relative_to(results))]


    def result_dirs_since(self, c):
        """Bench result directories made during this run, deepest first (their names come from the case)."""
        return sorted((d for d in (self.bench / "results").rglob("*") if d.is_dir() and d.stat().st_ctime >= c.t0), key=lambda d: -len(d.parts))


    @processes.deadline(600, independent=True)
    def seal(self, c, *, checkpoint=False):
        """G12: gather bench evidence and transcripts into the work dir, tar | age, sha256, shred."""
        work = c.work
        for f in self.results_since(c):  # bench evidence written during this run (holds case copies)
            dest = work / "bench-results" / f.relative_to(self.bench / "results")
            dest.parent.mkdir(parents=True, exist_ok=True); shutil.move(f, dest)
        for d in self.agent_state:
            if (self.home / d).exists():
                (work / "agent-state").mkdir(exist_ok=True)
                processes.run(["cp", "-a", "--parents", d, str(work / "agent-state")], cwd=self.home, capture_output=True)
        for user, home in self.pilot_homes():
            if home.exists():
                (work / "agent-state").mkdir(exist_ok=True)
                processes.run(["sudo", "cp", "-a", str(home), str(work / f"agent-state/{user}-home")], capture_output=True, check=True)
                processes.run(["sudo", "chown", "-R", f"{os.getuid()}:{os.getgid()}", str(work / "agent-state")], capture_output=True, check=True)
        if not c.args.dry_run and not checkpoint and not c.card.get("failed_gate"):
            self.retain_delivery(c)
        self.sealed.mkdir(exist_ok=True)
        c.card.pop("statement_cipher_sha256", None)
        if (not hasattr(c, "audit_source") and hasattr(c, "statement") and not getattr(c, "precheck_problems", None) and
                self.statements_recipient.is_file()):
            recipient = self.statements_recipient.read_text().strip()
            if recipient:
                with tempfile.TemporaryDirectory(dir=self.sealed) as tmp:
                    staged = pathlib.Path(tmp) / "statement.age"
                    c.card['statement_sha256'] = hashlib.sha256(c.statement.encode()).hexdigest()
                    encrypted = processes.run(["age", "-r", recipient, "-o", str(staged)],
                                               input=c.statement.encode(), capture_output=True)
                    if encrypted.returncode: raise RuntimeError("statement encryption failed")
                    c.card["statement_cipher_sha256"] = hashlib.sha256(staged.read_bytes()).hexdigest()
                    staged.replace(self.sealed / f"{c.case_id}.statement.age")
                    receipt = work / "public-search.json"
                    if receipt.is_file() and c.card.get("public_search"):
                        staged = pathlib.Path(tmp) / "search.age"
                        encrypted = processes.run(["age", "-r", recipient, "-o", str(staged)],
                                                   input=receipt.read_bytes(), capture_output=True)
                        if encrypted.returncode: raise RuntimeError("search receipt encryption failed")
                        c.card["public_search"]["cipher_sha256"] = hashlib.sha256(staged.read_bytes()).hexdigest()
                        staged.replace(self.sealed / f"{c.case_id}.search.age")
        if hasattr(c, 'job_money'):
            from copy import deepcopy
            c.card['job_money'] = deepcopy(c.job_money)
        # Bind the exact statement ciphertext inside the encrypted checkpoint too.
        (work / "scorecard.json").write_text(json.dumps(c.card, indent=2))
        out = self.sealed / f"{c.case_id}{'.checkpoint' if checkpoint else ''}.tar.gz.age"
        import r2_upload  # 2026-10-20: also sealed to the case's own key, so a restore can fetch it from R2
        try:
            vm_recipient = (Path(__file__).with_name('control-recipient.txt').read_text().strip()
                            if getattr(c.args, 'batch_release_sha256', None) else None)
            if getattr(c.args, 'batch_release_sha256', None) and not vm_recipient:
                raise RuntimeError('batch checkpoint requires VM restore recipient')
            case_key = None if c.args.dry_run and not vm_recipient else r2_upload.case_recipient(
                work, self.sealed, c.case_id, c.recipient,
                **({'restore_recipient': vm_recipient} if vm_recipient else {}))
        except (OSError, subprocess.CalledProcessError):
            if c.card.get('batch_release_sha256'):
                raise RuntimeError('batch checkpoint requires a wrapped case key') from None
            case_key = None  # Legacy restores retain their streaming path until migration.
        # Streamed, then atomically replaced: a resumed stop must not lose its previous checkpoint.
        with tempfile.TemporaryDirectory(dir=self.sealed) as tmp:
            staged = pathlib.Path(tmp) / "archive.age"
            q = lambda value: shlex.quote(str(value))
            extra = f" -r {q(case_key)}" if case_key else ""
            p = processes.run(f"set -o pipefail; tar -C {q(work.parent)} -czf - {q(work.name)} | age -r {q(c.recipient)}{extra} -o {q(staged)}",
                               shell=True, executable="/bin/bash", capture_output=True, timeout=600)
            if p.returncode: raise RuntimeError("encryption failed")
            staged.replace(out)
        c.card["sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
        c.card["archive"] = str(out)
        c.card.pop("r2_object", None)  # only a copy of exactly this archive may be named
        if case_key and (obj := r2_upload.upload(out, checkpoint)): c.card["r2_object"] = obj
        if c.args.dry_run:  # prove the round trip with the throwaway key, then compare every file
            with tempfile.TemporaryDirectory(dir=self.home) as tmp:
                d = processes.run(f"set -o pipefail; age -d -i {c.keyfile} {out} | tar -C {tmp} -xzpf - --no-same-owner", shell=True, executable="/bin/bash", capture_output=True)
                same = d.returncode == 0 and processes.run(["diff", "-r", "--no-dereference", str(work), str(pathlib.Path(tmp) / work.name)], capture_output=True).returncode == 0
                c.card["dry_run_roundtrip"] = {"decrypted": d.returncode == 0, "identical": same,
                                               "files": sum(1 for f in work.rglob("*") if f.is_file())}
                self.cleanup(pathlib.Path(tmp) / work.name)


    @processes.deadline(120, independent=True)
    def wipe(self, c):
        factory_cleanup = []
        for slot in range(1, max(self.factory_slots(c), getattr(c, 'prepared_factory_slots', 1))):
            import factory_pool
            result = processes.run([sys.executable, "-c", "import bench, processes; bench.stop_inventory_services(); bench.dc('down', '-v', '--remove-orphans'); processes.run(['docker', 'image', 'rm', '-f', bench.GUARD_IMAGE], capture_output=True); assert not bench.command(['docker', 'images', '-q', bench.GUARD_IMAGE])"],
                                    cwd=self.bench / "bin", env=factory_pool.worker_env(slot), capture_output=True)
            factory_cleanup.append(result.returncode == 0)
        for user, home in self.pilot_homes():
            if home.exists(): self.pilot_wall(c, user, 0, remove=True)
        self.cleanup(c.work)
        for d in self.agent_state: self.cleanup(self.home / d)
        for user, home in self.pilot_homes():
            if home.exists():
                self.cleanup(home, sudo=True)
                processes.run(["sudo", "pkill", "-KILL", "-u", user], capture_output=True)
                processes.run(["sudo", "userdel", "-r", user], capture_output=True)
        processes.run(["chmod", "755", str(self.home)], capture_output=True)
        for f in self.results_since(c, include_state=True): self.cleanup(f)
        for d in self.result_dirs_since(c):
            if d.exists() and not any(f.is_file() for f in d.rglob("*")): shutil.rmtree(d)
        processes.run(["docker", "image", "rm", "-f", "unbug-bench-medusa:guard"], capture_output=True)
        processes.run(["docker", "compose", "-f", str(self.bench / "projects/medusa/compose.yaml"), "down", "-v"], capture_output=True)  # the database held case data
        processes.run(["docker", "builder", "prune", "-af"], capture_output=True)  # layers held patched source
        left = sum(1 for p in [c.work, *(home for _, home in self.pilot_homes()), *(self.home / d for d in self.agent_state)] if p.exists() for f in ([p] if p.is_file() else p.rglob("*")) if f.is_file())
        left += len(self.results_since(c, include_state=True))
        c.card["wipe"] = {"plaintext_files_left": left,
                          "named_dirs_left": sum(1 for d in self.result_dirs_since(c) if not any(f.is_file() for f in d.rglob("*"))),
                          "guard_image_left": bool(processes.run(["docker", "images", "-q", "unbug-bench-medusa:guard"], capture_output=True, text=True).stdout.strip()),
                          "db_volume_left": "unbug-bench_postgres-data" in processes.run(["docker", "volume", "ls", "-q"], capture_output=True, text=True).stdout}
        if factory_cleanup: c.card["wipe"]["factory_cleanup_ok"] = all(factory_cleanup)


