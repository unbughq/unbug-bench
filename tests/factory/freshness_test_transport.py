"""Offline HTTP seam for existing synthetic search/reviewer control-flow tests."""
import gzip
import json
from pathlib import Path
from unittest.mock import patch
import freshness_retrieval

HTTP = json.loads(gzip.decompress((Path(__file__).parent / 'fixtures/invalid-runs-http.json.gz').read_bytes()))


def fetched(url):
    return {'url': url, 'final_url': url, 'status': 200}, HTTP['body'].encode()


def start(test, transport=fetched):
    mocked = patch.object(freshness_retrieval, 'fetch', side_effect=transport)
    mocked.start(); test.addCleanup(mocked.stop)
