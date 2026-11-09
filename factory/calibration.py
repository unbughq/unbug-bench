"""Calibration receipts and content-free diagnostics; never infer causes from transcripts."""
import hashlib
import contextlib
import copy
import json
import os
import pathlib
import re
import shutil
import subprocess
import time
from registry import atomic_json

GUARD_FILES = ("db.sql", "app.patch", "services.patch")
_PRIVATE_NAMES = {"guards", "judge.py", "hooks.mjs", "key.json", "answer-key.json",
                  "fact-sheet.md", "responder", "solution", "provenance.json", "case.json",
                  "statement.md", "scenarios", "credentials.json", "secrets.json",
                  "credentials", "secrets", "reference", "answer-key", "judge"}
_INFRA_FILES = {"adapter.py", "compose.yaml", "Dockerfile", "scenario.json"}
_SOURCE_SUFFIXES = {".py", ".js", ".ts", ".mjs", ".cjs", ".json", ".md", ".txt"}

# Runs entirely on contestant-visible files; no private runner paths or credentials.
CHECK_PATCHES = '''import pathlib, shutil, subprocess, sys, tempfile
root = pathlib.Path(__file__).resolve().parents[1]
guard = (root / (sys.argv[1] if len(sys.argv) > 1 else "guard")).resolve()
with tempfile.TemporaryDirectory() as temporary:
    work = pathlib.Path(temporary)
    for artifact, source in (("app.patch", "app"), ("services.patch", "services")):
        patch = guard / artifact
        if not patch.is_file(): continue
        original = root / source
        if not original.is_dir(): raise SystemExit("No source for " + artifact)
        target = work / source
        shutil.copytree(original, target)
        if artifact == "services.patch":
            rows = subprocess.check_output(["git", "apply", "--numstat", str(patch)], text=True)
            for row in rows.splitlines():
                path = pathlib.PurePosixPath(row.split("\\t", 2)[2])
                if (path.is_absolute() or ".." in path.parts or not path.parts
                        or not (original / path.parts[0]).is_dir()
                        or path.name in ("adapter.py", "compose.yaml", "Dockerfile")):
                    raise SystemExit("Unsupported service patch path")
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=target, check=True)
print("Patch paths and applicability checked; no SQL execution or deployment performed.")
'''


def guard_submitted(directory):
    """The same artifact contract applies to submission detection and durable receipts."""
    directory = pathlib.Path(directory)
    return any((directory / name).is_file() and not (directory / name).is_symlink()
               for name in GUARD_FILES)



def source_root(path, allowed):
    """Authorize lexical paths before resolving any links (including root ancestors)."""
    original = pathlib.Path(path).absolute()
    path = pathlib.Path(os.path.abspath(path))
    allowed = [pathlib.Path(os.path.abspath(p)) for p in allowed]
    if path not in allowed:
        raise ValueError("service source is outside contestant project roots")
    for candidate in (original, *original.parents):
        if candidate.is_symlink():
            # macOS exposes these OS-owned aliases even for tempfile's default root.
            aliases = {"/var": "/private/var", "/tmp": "/private/tmp", "/etc": "/private/etc"}
            if (os.uname().sysname == "Darwin" and str(candidate) in aliases and
                    str(candidate.resolve()) == aliases[str(candidate)]): continue
            raise ValueError("symlink in contestant source root")
    return path


def application_files(root, pattern):
    """Explicit source/config contract; hidden state and dependency trees never cross."""
    suffixes = _SOURCE_SUFFIXES | {".jsx", ".tsx", ".css", ".scss", ".html", ".sql", ".yaml", ".yml", ".toml", ".lock"}
    files = {}
    ignored = {"node_modules", ".medusa", ".git", "__pycache__"}
    for directory, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in ignored and not d.startswith("."))
        for name in sorted([*directories, *names]):
            path = pathlib.Path(directory) / name
            relative = path.relative_to(root)
            if path.name in ignored or path.name.startswith("."): continue
            if path.is_symlink(): raise ValueError("symlink in application source")
            if set(relative.parts) & _PRIVATE_NAMES or path.stem in {"credentials", "secrets"}:
                raise ValueError("private path in application delivery")
            if not path.is_file(): continue
            if path.suffix not in suffixes and path.name not in ("Dockerfile", "Dockerfile.deps"):
                raise ValueError("unsupported application source material")
            content = path.read_bytes()
            if pattern.search(content.decode("utf-8")):
                raise ValueError("private information in application material")
            files[relative.as_posix()] = content
    return files


def prepare_delivery(case, bench_root, workspace, *, exposure="blind", slot=0):
    """Prepare contestant inputs before spending a model call; never copy a whole case.

    For easy/strong calibration and the independent breadth attempt. Runtime service
    resolution is shared with the exam runner; only source/docs cross this boundary.
    The caller still owns Unix isolation, the owner channel and checkpoint execution.
    """
    import bench
    # A defect in the case's own contestant material is a gate result the writer can repair,
    # never an infrastructure retry (18681d, 9 November: six G16 retries on a baseline mismatch).
    from case_contract import CaseProblem
    case, bench_root, workspace = map(pathlib.Path, (case, bench_root, workspace))
    if exposure not in ("blind", "exam", "statement"):
        raise ValueError("unknown tester information conditions")
    scenario = bench.load_scenario(case / "base")
    # inventory_services resolves paths; authenticate the original declarations first.
    approved = {}
    for entry in scenario.get("inventory_services", []):
        name = entry["name"]
        if not re.fullmatch(r"[a-z][a-z0-9-]*", name): raise ValueError("invalid service name")
        project = pathlib.Path(entry["project"])
        if not project.is_absolute():
            local = case / "base" / project
            project = local if local.is_dir() else bench_root / project
        approved[name] = source_root(project, [case / "services" / name, case / "projects" / name,
                                               bench_root / "projects" / name])
    services = bench.inventory_services([scenario])
    inputs = {name: case / name for name in ("promise.md", "contestant.md")}
    if exposure == "statement": inputs["statement.md"] = case / "statement.md"
    replacements = {"projects/medusa": "app"}
    for service in services:
        name, project = service["name"], pathlib.Path(service["project"])
        if project.resolve() != approved[name].resolve():
            raise ValueError("resolved service differs from permitted source")
        if not (project / "README.md").is_file():
            raise CaseProblem("missing service documentation")
        sources = 0
        for path in sorted(project.rglob("*")):
            relative = path.relative_to(project)
            if path.is_symlink(): raise CaseProblem("symlink in contestant service material")
            if set(relative.parts) & _PRIVATE_NAMES:
                raise CaseProblem("private material in contestant service project")
            if any(p.startswith(".") or p in ("node_modules", "__pycache__") for p in relative.parts): continue
            if not path.is_file() or path.name in _INFRA_FILES: continue
            if path.suffix not in _SOURCE_SUFFIXES:
                raise CaseProblem("unsupported contestant service material")
            inputs[(pathlib.Path("services") / name / relative).as_posix()] = path
            sources += path.suffix in {".py", ".js", ".ts", ".mjs", ".cjs"}
        if not sources: raise CaseProblem("missing service source")
        replacements[f"projects/{name}"] = f"services/{name}"
        replacements[f"app/integrations/{name}"] = f"services/{name}"
    baseline = case / "base/admin.sql"
    if baseline.is_file():
        # Reuse the exam's visible baseline aliases only when their bytes agree.
        aliases = []
        for path in case.glob("harbor/*/steps/establish/workdir/**/admin.sql"):
            if path.is_symlink(): raise CaseProblem("symlink in contestant baseline material")
            if path.read_bytes() == baseline.read_bytes():
                alias = path.as_posix().split("/workdir/", 1)[1]
                aliases.append(alias)
                replacements[alias] = "baseline/admin.sql"
        if not aliases: raise CaseProblem("baseline SQL lacks contestant-visible delivery")
        inputs["baseline/admin.sql"] = baseline
    ports = [9000, 9001] + [p for s in services for p in s.get("host_ports", [])]
    port_map = {str(p): str(p + 100 * slot) for p in ports}
    leak_words = ["answer key", "reference fix", "fact sheet", "judge.py", "hooks.mjs", "key.json"]
    meta = case / "case.json"
    if meta.is_file(): leak_words += json.loads(meta.read_text()).get("leak_words", [])
    pattern = re.compile("|".join(re.escape(w) for w in leak_words), re.I)
    prepared = {}
    for name, path in inputs.items():
        source_root(path, [path])
        if not path.is_file() or path.is_symlink(): raise CaseProblem("missing contestant material")
        content = path.read_text()
        if pattern.search(content): raise CaseProblem("private information in contestant material")
        # Preserve deployed source bytes: patches written against it must apply unchanged.
        if not name.startswith("services/") and path.suffix in (".md", ".txt"):
            for old, new in replacements.items(): content = content.replace(old, new)
            content = re.sub(r":(\d+)(?!\d)", lambda m: ":" + port_map.get(m[1], m[1]), content)
        prepared[name] = path.read_bytes() if name.startswith("services/") else content.encode()
    # Referenced service files are mandatory, even if the project itself exists.
    for content in prepared.values():
        references = content.decode()
        for old, new in replacements.items(): references = references.replace(old, new)
        for reference in re.findall(r"(?:services/[a-z][a-z0-9-]*/)[\w./-]+", references):
            reference = reference.rstrip("./")
            if pathlib.PurePosixPath(reference).suffix and reference not in prepared:
                raise CaseProblem("missing promised service material")
    if workspace.exists(): raise ValueError("delivery workspace already exists")
    patch = case / "base/app.patch"
    if patch.is_file() and (patch.is_symlink() or pattern.search(patch.read_text())):
        raise CaseProblem("private information in application baseline patch")
    app = source_root(bench_root / "projects/medusa", [bench_root / "projects/medusa"])
    app_files = application_files(app, pattern)
    # Stage and validate baseline additions before creating any pilot-owned location.
    import tempfile
    with tempfile.TemporaryDirectory() as temporary:
        staged = pathlib.Path(temporary) / "app"
        staged.mkdir()
        for name, content in app_files.items():
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        if patch.is_file():
            subprocess.run(["git", "apply", str(patch.resolve())], cwd=staged, check=True, capture_output=True)
        validated = application_files(staged, pattern)
        if tree_digest(staged) != {name: hashlib.sha256(data).hexdigest() for name, data in validated.items()}:
            raise CaseProblem("baseline patch adds forbidden application material")
        shutil.copytree(staged, workspace / "app")
    for name, content in prepared.items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    checker = workspace / "bin/check-patches"
    checker.parent.mkdir(exist_ok=True)
    checker.write_text(CHECK_PATCHES)
    (workspace / "DELIVERY.md").write_text(
        "Source and service documentation bytes are unchanged for patch applicability. "
        "Endpoint mapping for this slot: " + ", ".join(f"{old} -> {new}" for old, new in port_map.items()) + ". "
        "Project mapping: " + ", ".join(f"{old} -> {new}" for old, new in replacements.items()) + ".\n\n"
        "Paths in this workspace are relative to its root. Application source is app/. "
        "Secondary-service source and API documentation are services/<name>/. "
        "app.patch paths are relative to app/; services.patch paths start with <name>/, "
        "not services/. Service deployment configuration and monitoring adapters are immutable.\n\n"
        "Local patch check: python3 bin/check-patches guard. This checks application and service "
        "patch paths/applicability without deploying them; it does not execute SQL or establish safety. "
        "The application is already running. Use its documented local HTTP APIs for trial orders "
        "and read-only monitoring. Source edits alone do not deploy a fix; submit artifacts in guard/. "
        "The runner tests that directory on a fresh restore. No reset or deployment command is "
        "installed in this workspace. Commands in contestant.md describing the full exam repository "
        "are not local workspace commands.\n\n"
        "Installation order: restore seeded database; guard/db.sql; baseline/admin.sql (if supplied); "
        "application startup with baseline app.patch then guard/app.patch; secondary services "
        "with guard/services.patch. SQL must compose with baseline replay in that order.\n")
    return {"files": sorted([*prepared, "DELIVERY.md", "bin/check-patches"]), "guard_files": list(GUARD_FILES)}


def tree_digest(root):
    """Bind all retained artifact bytes and names; symlinks are not durable evidence."""
    root = pathlib.Path(root)
    if not root.is_dir() or root.is_symlink(): raise ValueError("missing calibration artifact")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink(): raise ValueError("symlink calibration artifact")
        if path.is_file(): files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def atomic_results(path, rows):
    """Commit one completed attempt before another model call can start."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, rows)


def compatible_identity(prior, current):
    """One pinned policy-only migration; unknown historical code is never trusted."""
    if prior == current: return True
    try:
        policy = json.loads(pathlib.Path(__file__).with_name('invalid-runs-compat.json').read_text())
        upgraded = copy.deepcopy(prior)
        for section in ('runner', 'files'):
            old, new = upgraded['bench'][section], current['bench'][section]
            for name, target in policy['current_' + section].items():
                if old.get(name) == new.get(name): continue
                if old.get(name) != policy['base_' + section].get(name) or new.get(name) != target:
                    return False
                if target is None: old.pop(name, None)
                else: old[name] = target
        return upgraded == current
    except (OSError, ValueError, KeyError, TypeError):
        return False


def compatible_panel(prior, current):
    """Preserve semantic G8/G9 panels across this pinned execution-only change."""
    try:
        policy = json.loads(pathlib.Path(__file__).with_name('invalid-runs-compat.json').read_text())
        upgraded = copy.deepcopy(prior)
        if (upgraded['cache'] != policy['base_files']['factory/gate_state.py']
                or current['cache'] != policy['current_files']['factory/gate_state.py']): return False
        upgraded['cache'] = current['cache']
        for name, target in policy['current_files'].items():
            if name not in current['bench']: continue
            if upgraded['bench'].get(name) == current['bench'][name]: continue
            if (upgraded['bench'].get(name) != policy['base_files'].get(name)
                    or current['bench'][name] != target): return False
            upgraded['bench'][name] = target
        return upgraded == current
    except (OSError, ValueError, KeyError, TypeError):
        return False


def completed_attempts(path, identity, work):
    """Keep only a verified contiguous prefix. Legacy/invalid evidence is quarantined."""
    path = pathlib.Path(path)
    if not path.exists(): return []
    try:
        rows = json.loads(path.read_text())
        if not isinstance(rows, list): raise ValueError("invalid calibration receipt")
    except (OSError, ValueError): rows = None
    from run_validity import InvalidInfra
    kept, interrupted = [], False
    for row in rows or []:
        try:
            if not isinstance(row, dict) or not compatible_identity(row.get("identity"), identity) or type(row.get("try")) is not int:
                break
            artifacts = row["artifacts"]
            ws = pathlib.Path(row["workspace"])
            ws.resolve().relative_to(pathlib.Path(work).resolve())
            if any(ws.resolve() == pathlib.Path(previous["workspace"]).resolve() for previous in kept): break
            if tree_digest(ws) != artifacts: break
            guard = ws / "guard"
            submitted = guard_submitted(guard)
            if type(row.get("guard_submitted")) is not bool or submitted != row["guard_submitted"]: break
            if submitted and row.get("guard") != str(guard): break
            if row["solved"] and not submitted: break
            try: attempt_summary([row])
            except InvalidInfra: interrupted = True
            if interrupted:
                # Retain the submitted fix to repair execution without buying a
                # replacement solver. The scientific suffix is quarantined below.
                atomic_results(path.parent / f"pending-{row['try']}.json", {
                    'try': row['try'], 'identity': identity, 'workspace': str(ws),
                    'artifacts': {k: v for k, v in artifacts.items() if k != 'execution.json'},
                    'capped': {'time_limit': 'timeout', 'call_limit': 'call_limit'}.get(row.get('stop_reason'))})
                continue
            if row['try'] != len(kept) + 1: break
        except (OSError, ValueError, KeyError, TypeError): break
        kept.append({**row, 'identity': identity})
    if rows is None or len(kept) != len(rows):
        path.rename(path.with_name(f"results-unverified-{time.time_ns()}.json"))
        if kept: atomic_results(path, kept)
    elif kept != rows:
        atomic_results(path, kept)
    return kept


class AttemptSeries:
    """Own durable attempt order, verified reuse and interrupted workspaces.

    Execution supplies completed observations. Only a successful atomic commit
    advances this series; a stopped model call is never a scored failed attempt.
    """
    def __init__(self, path, identity, work, tries, model, *, probe=None):
        self.path, self.work = pathlib.Path(path), pathlib.Path(work)
        self.identity, self.tries, self.model = identity, tries, model
        self.rows = completed_attempts(self.path, identity, self.work)
        if not self.rows and probe is not None:
            prior = completed_attempts(probe, identity, self.work)
            if len(prior) == 1:
                self.rows = [{**prior[0], "source": "early_probe"}]
                atomic_results(self.path, self.rows)
        if len(self.rows) > tries:
            raise ValueError("calibration attempt count exceeds requested tries")
        self.kept = len(self.rows) == tries

    def remaining(self):
        return range(len(self.rows) + 1, self.tries + 1)

    def workspace(self, number):
        if number != len(self.rows) + 1 or number > self.tries:
            raise ValueError("calibration attempts must run in order")
        workspace = self.path.parent / f"try-{number}"
        if workspace.exists():
            workspace.rename(workspace.with_name(f"try-{number}-interrupted-{time.time_ns()}"))
        return workspace

    def commit(self, row, workspace):
        if row.get("try") != len(self.rows) + 1 or row["try"] > self.tries:
            raise ValueError("calibration attempts must commit in order")
        if pathlib.Path(workspace) != self.path.parent / f"try-{row['try']}":
            raise ValueError("calibration workspace does not match attempt")
        completed = {**row, "scientific_outcome": scientific_outcome(row),
                     "identity": self.identity, "workspace": str(workspace),
                     "artifacts": tree_digest(workspace)}
        pending = [*self.rows, completed]
        attempt_summary(pending)
        atomic_results(self.path, pending)
        self.rows = pending
        self.pending_path(row['try']).unlink(missing_ok=True)
        return self.summary()

    def pending_path(self, number):
        return self.path.parent / f'pending-{number}.json'

    def save_pending(self, number, workspace, capped):
        atomic_results(self.pending_path(number), {'try': number, 'identity': self.identity,
            'workspace': str(workspace), 'artifacts': {k: v for k, v in tree_digest(workspace).items() if k != 'execution.json'}, 'capped': capped})

    def pending(self, number):
        path = self.pending_path(number)
        if not path.exists(): return None
        row = json.loads(path.read_text())
        workspace = self.path.parent / f'try-{number}'
        if (row.get('identity') != self.identity or row.get('try') != number
                or row.get('workspace') != str(workspace) or row.get('artifacts') != {k: v for k, v in tree_digest(workspace).items() if k != 'execution.json'}):
            path.rename(path.with_name(path.stem + '-unverified-' + str(time.time_ns()) + '.json'))
            return None
        return workspace, row.get('capped')

    def summary(self):
        return {"model": self.model, **attempt_summary(self.rows)}

    def finish(self):
        if len(self.rows) != self.tries:
            raise ValueError("calibration attempts are incomplete")
        summary = self.summary()
        if self.kept: summary["kept"] = True
        return summary, [pathlib.Path(row["guard"]) for row in self.rows if row["solved"]]


@contextlib.contextmanager
def isolated_attempt_context(parent, *, slot, user):
    """Isolate probe execution settings but retain cumulative budget state on stops."""
    child = copy.copy(parent)
    child.args = copy.copy(parent.args)
    child.args.bench_workers = 1
    child.factory_slot, child.pilot_user, child.pilot_passes = slot, user, []
    try:
        yield child
    finally:
        for name in ("budget_resumed", "force_budget_resume"):
            if hasattr(child, name): setattr(parent, name, getattr(child, name))

STOP_REASONS = ("completed", "time_limit", "call_limit", "unrecorded")
OUTCOMES = ("solved", "no_fix_submitted", "fix_failed_some_runs", "fix_failed_all_runs",
            "fix_failed_runs", "run_error", "unknown")
NO_FIX = {"no guard written": "unrecorded", "no guard written (timeout)": "time_limit",
          "no guard written (call_limit)": "call_limit"}


SCIENTIFIC_OUTCOMES = ("solved", "demonstrated_failure", "capped", "no_submission", "unknown")


def scientific_outcome(row):
    """Classify observed evidence, never infer an uncapped fix from legacy counts."""
    from run_validity import require_valid
    require_valid({'runs': 1, 'error_runs': row.get('errors', 0),
                   'invalid_runs': int(bool(row.get('bench_crash')))})
    if row.get('solved') is True:
        return "solved"
    if row.get('guard_submitted') is False or (isinstance(row.get('why'), str) and row['why'] in NO_FIX):
        return "no_submission"
    if row.get('stop_reason') in ("time_limit", "call_limit"):
        return "capped"
    checked, solved = row.get('checked_runs'), row.get('solved_runs')
    if (row.get('stop_reason') == 'completed' and row.get('guard_submitted') is True
            and type(checked) is int and type(solved) is int and 0 <= solved < checked
            and row.get('errors') == 0):
        return "demonstrated_failure"
    return "unknown"


def require_summary_valid(summary):
    """Legacy public diagnostics can disprove validity; absent raw evidence cannot prove it."""
    from run_validity import require_valid
    require_valid({'runs': summary.get('tries'), 'error_runs':
        summary.get('diagnostics', {}).get('outcomes', {}).get('run_error', 0)})


def attempt_summary(rows):
    """Only allowlisted labels and integer counts may leave the sealed side.

    Stop and outcome are separate: a capped attempt can still leave a successful fix.
    Older records cannot distinguish partial from total failure, or recover most caps.
    Execution errors do not establish whether a fix or the harness caused the error.
    """
    if not isinstance(rows, list) or any(not isinstance(r, dict) or type(r.get("solved")) is not bool for r in rows):
        raise ValueError("invalid calibration results")
    stops = dict.fromkeys(STOP_REASONS, 0)
    outcomes = dict.fromkeys(OUTCOMES, 0)
    scientific = dict.fromkeys(SCIENTIFIC_OUTCOMES, 0)
    for row in rows:
        from run_validity import require_valid
        require_valid({'runs': 1, 'error_runs': row.get('errors', 0),
                       'invalid_runs': int(bool(row.get('bench_crash')))})
        observed = scientific_outcome(row)
        if "scientific_outcome" in row and row["scientific_outcome"] != observed:
            raise ValueError("conflicting scientific outcome")
        scientific[observed] += 1
        why = row.get("why")
        legacy_no_fix = isinstance(why, str) and why in NO_FIX
        stop = row.get("stop_reason")
        if not isinstance(stop, str) or stop not in stops:
            stop = NO_FIX[why] if legacy_no_fix else "unrecorded"
        stops[stop] += 1
        checked, solved = row.get("checked_runs"), row.get("solved_runs")
        errors = row.get("errors")
        if row["solved"]:
            outcome = "solved"
        elif row.get("guard_submitted") is False or legacy_no_fix:
            outcome = "no_fix_submitted"
        elif type(errors) is int and errors > 0:
            outcome = "run_error"
        elif type(checked) is int and type(solved) is int and 0 <= solved < checked:
            outcome = "fix_failed_some_runs" if solved else "fix_failed_all_runs"
        elif "guard" in row and errors == 0:
            outcome = "fix_failed_runs"
        else:
            outcome = "unknown"
        outcomes[outcome] += 1
    return {"tries": len(rows), "solved": outcomes["solved"],
            "diagnostics": {"version": 1, "stop_reasons": stops, "outcomes": outcomes},
            "scientific": {"version": 1, "outcomes": scientific}}


def interruption_label(error):
    """Interrupted calls remain stops, never scored failed attempts; no error text escapes."""
    reason = str(error)
    for prefix in ("Budget stopped: ", "Budget ledger stopped: "):
        if reason.startswith(prefix):
            reason = reason[len(prefix):]
            break
    reason = reason.split(":", 1)[0]
    if reason in ("process_error", "codex_error", "claude_error", "opencode_error"):
        return "model_process_error"
    if reason in ("missing_usage", "invalid_usage", "unpriced_usage", "usage_monitor"):
        return "usage_monitor_error"
    if reason == "stalled": return "no_progress_limit"
    if reason == "timeout": return "time_limit"
    if reason == "call_limit": return "call_limit"
    if reason in ("codex_login_expired", "provider_limit", "cost_limit", "total_call_limit", "cancelled", "zero_tokens", "refusal", "model_call_cap"):
        return reason
    return "unknown"
