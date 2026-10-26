#!/usr/bin/env python3
"""Dependency preload keeps the pinned lock, contains no app, and rejects lock drift."""
import hashlib, pathlib, shutil, subprocess, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[4]
app = ROOT / "projects/medusa"
image = "unbug-bench-medusa-deps:" + hashlib.sha256((app / "package-lock.json").read_bytes()).hexdigest()
subprocess.run(["docker", "run", "--rm", image, "sh", "-c",
    "test -d node_modules && test ! -d src && test ! -d .medusa && node verify-lock.mjs && sha256sum -c /opt/medusa-deps.sha256"], check=True)
with tempfile.TemporaryDirectory(prefix="unbug-deps-lock-") as temporary:
    context = pathlib.Path(temporary)
    shutil.copytree(app, context, dirs_exist_ok=True, ignore=shutil.ignore_patterns("node_modules", ".medusa", "seed-ids.json"))
    # Same resolved versions; changing even lock formatting must not reuse stale dependencies.
    with (context / "package-lock.json").open("a") as lock: lock.write("\n")
    result = subprocess.run(["docker", "build", "--progress=plain", "--build-arg", "MEDUSA_DEPS_IMAGE=" + image, str(context)], capture_output=True, text=True)
    assert result.returncode != 0, "changed lock unexpectedly reused dependencies"
    assert "package-lock.json: FAILED" in result.stdout + result.stderr, result.stderr[-3000:]
print("dependency image: exact lock and Medusa verified; no source/build; altered lock rejected")
