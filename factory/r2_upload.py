"""Per-case key and R2 copy of sealed archives (2026-10-20). The archive is sealed to the founder and to the case's
own key; that key, sealed to the founder, is collected as <case>.casekey.age. A restore then sends only the small case
key to the new VM, which downloads the ciphertext from R2 (bin/r2-presign links; the R2 keys never leave the host)."""
import hashlib, json, os, pathlib, subprocess, tempfile, time


def case_recipient(work, sealed, case_id, founder_recipient, restore_recipient=None):
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
            recipients = ['-r', founder_recipient]
            if restore_recipient:
                recipients += ['-r', restore_recipient]
            subprocess.run(["age", *recipients, str(ident)], stdout=stream,
                           stderr=subprocess.PIPE, check=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, destination)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    return public


def _links(checkpoint, links):
    """(PUT link, GET link, object key) for this kind, or None. Both links are required (checkpoint-readback)."""
    try: cfg = json.loads((links or pathlib.Path.home() / ".factory-r2").read_text())
    except (OSError, ValueError): return None
    kind = "checkpoint" if checkpoint else "final"
    if not isinstance(cfg, dict): return None
    put, get, prefix = cfg.get(kind), cfg.get(kind + "_get"), cfg.get("prefix")
    if not all(isinstance(v, str) and v for v in (put, get, prefix)): return None
    return put, get, f"{prefix}/{kind}.tar.gz.age"


def target(checkpoint, links=None):
    """The object key upload() would write, or None when it would not upload."""
    found = _links(checkpoint, links)
    return found[2] if found else None


def _readback(url, size, timeout=1800):
    """Stream the object back; its SHA-256 if exactly `size` bytes arrive in time, else None. No retry: a retried
    transfer would append to bytes already hashed. The URL never enters an error or log."""
    h, seen, end = hashlib.sha256(), 0, time.monotonic() + timeout
    with subprocess.Popen(["curl", "-fsS", "--max-time", str(timeout), url],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as p:
        try:
            while block := p.stdout.read(1024 * 1024):
                seen += len(block)
                if seen > size or time.monotonic() > end: return None
                h.update(block)
            if p.wait(timeout=max(1, end - time.monotonic())) != 0: return None
        except subprocess.TimeoutExpired:
            return None
        finally:
            if p.poll() is None: p.kill()
    return h.hexdigest() if seen == size else None


def upload(archive, checkpoint, links=None):
    """PUT the ciphertext to this VM's pre-signed link, then read it back. The object key only when the stored bytes
    equal the archive; otherwise None (host collection still has the archive)."""
    found = _links(checkpoint, links)
    if found is None: return None
    put, get, key = found
    archive = pathlib.Path(archive)
    try: done = subprocess.run(["curl", "-fsS", "--retry", "3", "-X", "PUT", "--upload-file", str(archive), put],
                               capture_output=True, timeout=1800).returncode == 0
    except subprocess.TimeoutExpired: done = False
    if not done: return None
    with archive.open("rb") as stream:
        size, expected = os.fstat(stream.fileno()).st_size, hashlib.file_digest(stream, "sha256").hexdigest()
    return key if _readback(get, size) == expected else None
