"""Canonical evidence hashing shared by durable diagnosis; no lifecycle state."""
import hashlib
import json

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()
