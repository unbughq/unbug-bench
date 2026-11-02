"""Worker RAM credentials; the override is solely for isolated offline exams."""
import os
from pathlib import Path

SECRETS = Path(os.environ.get('UNBUG_TEST_WORKER_SECRETS', '/dev/shm/secrets'))
