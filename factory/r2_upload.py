"""Per-case key and R2 copy of sealed archives (2026-10-20). The archive is sealed to the founder and to the case's
own key; that key, sealed to the founder, is collected as <case>.casekey.age. A restore then sends only the small case
key to the new VM, which downloads the ciphertext from R2 (bin/r2-presign links; the R2 keys never leave the host)."""
import json, os, pathlib, subprocess, tempfile


def case_recipient(work, sealed, case_id, founder_recipient):
    """Public key of the case's own age identity. The identity lives in the work tree, so every resume reuses it."""
    ident = pathlib.Path(work) / ".casekey"
    if not ident.is_file():
        made = subprocess.run(["age-keygen"], capture_output=True, text=True, check=True).stdout
        ident.touch(0o600); ident.write_text(made)
    ident.chmod(0o600)  # older archive modes must never relax the case identity
    public = subprocess.run(["age-keygen", "-y", str(ident)], capture_output=True, text=True, check=True).stdout.strip()
    # age refuses an existing -o path. Seal again into a sibling temporary file;
    # a failed re-seal must preserve the previously collected recovery key.
    destination = pathlib.Path(sealed) / f"{case_id}.casekey.age"
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=sealed, prefix=".casekey-", delete=False) as stream:
            staged = pathlib.Path(stream.name)
            subprocess.run(["age", "-r", founder_recipient, str(ident)], stdout=stream,
                           stderr=subprocess.PIPE, check=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, destination)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    return public


def upload(archive, checkpoint, links=None):
    """PUT the ciphertext to this VM's pre-signed link; the object key, or None (host collection still has it)."""
    try: cfg = json.loads((links or pathlib.Path.home() / ".factory-r2").read_text())
    except (OSError, ValueError): return None
    kind = "checkpoint" if checkpoint else "final"
    try: done = subprocess.run(["curl", "-fsS", "--retry", "3", "-X", "PUT", "--upload-file", str(archive), cfg[kind]],
                               capture_output=True, timeout=1800).returncode == 0
    except (KeyError, subprocess.TimeoutExpired): done = False
    return f"{cfg['prefix']}/{kind}.tar.gz.age" if done else None
