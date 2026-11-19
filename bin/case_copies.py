#!/usr/bin/env python3
"""Free offline check that a case's duplicated files still agree.

  python3 bin/case_copies.py CASE_DIR [CASE_DIR ...]      exit 1 if any copy drifted

A case keeps some files in more than one place. Hand repairs edit one and forget the other, and
the drift then fails a paid review or G1. FAIL (exit 1):

- steps/*/workdir/**/contestant.md and promise.md are byte copies of the case root's.
- A step's workdir admin.sql, app.patch and change-record.md are byte copies of the same file in
  that step's scenario (the last UNBUG_SCENARIOS id; BASE is base/). The reduced workdir
  scenario.json agrees with the scenario's scenario.json on every field it carries.
- window.json key and answer-key.json[checkpoint] agree with that scenario's key.json on every
  shared field (bin/strategy lays answer-key.json fields over key.json, so a stale mirror changes
  G13/G15). expected_judge may list fewer guards or checks, but never a different value.
  intent_checks: the window key's are the step's cumulative set (the union over every active
  scenario, which bin/checkpoint scores); an answer-key entry's are that or the scenario's own.

WARN only: judge_checks and why (prose for reviewers, read by no code) differ, and window.json
traffic_hooks[id] differs from that scenario's hooks.mjs (a window may carry its own live recipe,
harbor/phase2/README.md; say so in BUILD-NOTES.md). judge_source and reader_source have no file
of their own to compare.

Not in any gate or identity: factory/case_contract.py (G1) is in every gate's and calibration's
identity, so this runs before launch instead. Messages name files and fields, never case content.
"""
import json
import pathlib
import sys
import tomllib

COPIED = ("admin.sql", "app.patch", "change-record.md")
PROSE = ("judge_checks", "why")


def load(path):
    try: return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError): return None


def agree(a, b):
    """Equal where both say something: dicts compare their shared keys, anything else must be equal."""
    if isinstance(a, dict) and isinstance(b, dict): return all(agree(a[k], b[k]) for k in set(a) & set(b))
    return a == b


def problems(case):
    """(failures, warnings) for one case directory."""
    case = pathlib.Path(case)
    fails, warns = [], []
    rel = lambda p: p.relative_to(case).as_posix()
    dirs = {"BASE": case / "base", "establish": case / "base"}
    for d in [case / "base", *sorted(case.glob("scenarios/*"))]:
        sid = (load(d / "scenario.json") or {}).get("id")
        if sid: dirs[sid] = d
    key = lambda sid: (load(dirs[sid] / "key.json") or {}) if sid in dirs else {}
    union = lambda ids: sorted({n for s in ids for n in key(s).get("intent_checks", [])})
    active = {}   # step name and its own scenario id -> active scenario ids at that step

    def fields(where, copy, source):
        for f in sorted(set(copy) & set(source) - {"intent_checks"}):
            same = agree(copy[f], source[f]) if f == "expected_judge" else copy[f] == source[f]
            if not same: (warns if f in PROSE else fails).append(f"{where}: {f} differs from the scenario key")

    for task in sorted(case.glob("harbor/*/task.toml")):
        try: steps = tomllib.loads(task.read_text()).get("steps") or []
        except tomllib.TOMLDecodeError: fails.append(f"{rel(task)}: not TOML"); continue
        for step in steps:
            ids = ((step.get("verifier") or {}).get("env") or {}).get("UNBUG_SCENARIOS", "").split()
            if not ids: continue
            sid, root = ids[-1], task.parent / "steps" / step.get("name", "?")
            active[step.get("name")] = active[sid] = ids
            for path in sorted(p for p in (root / "workdir").rglob("*") if p.is_file()):
                name = path.name.lower()
                if name in ("contestant.md", "promise.md"):
                    if not (case / name).is_file() or path.read_bytes() != (case / name).read_bytes():
                        fails.append(f"{rel(path)}: differs from case {name}")
                elif sid not in dirs: continue
                elif path.name in COPIED and (dirs[sid] / path.name).is_file():
                    if path.read_bytes() != (dirs[sid] / path.name).read_bytes():
                        fails.append(f"{rel(path)}: differs from {rel(dirs[sid] / path.name)}")
                elif path.name == "scenario.json" and "changes" in path.relative_to(root).parts:
                    copy, source = load(path) or {}, load(dirs[sid] / "scenario.json") or {}
                    for f in sorted(set(copy) & set(source)):
                        if copy[f] != source[f]: fails.append(f"{rel(path)}: {f} differs from the scenario")
            window = load(root / "window.json")
            if not isinstance(window, dict): continue
            where = rel(root / "window.json")
            for hook_id, source in (window.get("traffic_hooks") or {}).items():
                hooks = dirs[hook_id] / "hooks.mjs" if hook_id in dirs else None
                if hooks is None or not hooks.is_file() or source != hooks.read_text():
                    warns.append(f"{where}: traffic_hooks.{hook_id} is not its scenario's hooks.mjs")
            wkey = window.get("key") if isinstance(window.get("key"), dict) else {}
            fields(f"{where} key", wkey, key(sid))
            if "intent_checks" in wkey and sorted(wkey["intent_checks"]) != union(ids):
                fails.append(f"{where} key: intent_checks are not the step's cumulative set")

    answers = load(case / "answer-key.json") if (case / "answer-key.json").is_file() else {}
    for cp, entry in (answers or {}).items():
        ids = active.get(cp) or [cp]
        sid = "establish" if cp == "establish" else ids[-1]
        if sid not in dirs or not isinstance(entry, dict):
            fails.append(f"answer-key.json {cp}: no scenario with that id"); continue
        fields(f"answer-key.json {cp}", entry, key(sid))
        if "intent_checks" in entry and sorted(entry["intent_checks"]) not in (union(ids), union([sid])):
            fails.append(f"answer-key.json {cp}: intent_checks are neither the scenario's nor the step's cumulative set")
    return fails, warns


if __name__ == "__main__":
    if len(sys.argv) < 2: sys.exit(__doc__)
    failed = False
    for case in sys.argv[1:]:
        fails, warns = problems(case)
        for w in warns: print(f"WARN {case}: {w}")
        for f in fails: print(f"FAIL {case}: {f}")
        print(("COPIES FAIL " if fails else "COPIES OK ") + case)
        failed |= bool(fails)
    sys.exit(1 if failed else 0)
