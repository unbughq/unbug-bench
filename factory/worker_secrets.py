"""Worker RAM credentials; the override is solely for isolated offline exams."""
import os
from pathlib import Path

SECRETS = Path(os.environ.get('UNBUG_TEST_WORKER_SECRETS', '/dev/shm/secrets'))


def router_environment(directory=SECRETS):
    """Router authority stays in the worker parent; model_runtime strips it from pilots."""
    directory = Path(directory)
    names = ('factory-router-url', 'factory-router-token', 'factory-router-ca.pem')
    if not any((directory / name).exists() for name in names):
        return {}
    url, token, _ = [(directory / name).read_text().strip() for name in names]
    return {'FACTORY_ROUTER_URL': url, 'FACTORY_ROUTER_TOKEN': token,
            'FACTORY_ROUTER_CA_FILE': str(directory / names[2])}
