"""Synthetic local TLS service; no production credentials or provider transport."""
import json
from pathlib import Path
import subprocess
import threading
from contextlib import contextmanager
import model_router

TOKEN = 'public-offline-router-sentinel'

@contextmanager
def router(base):
    base = Path(base); base.mkdir(parents=True, exist_ok=True)
    key, cert = base / 'key.pem', base / 'cert.pem'
    cfg = base / 'openssl.cnf'
    cfg.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n')
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                    '-keyout',str(key),'-out',str(cert),'-config',str(cfg)],check=True,capture_output=True)
    store = model_router.Store(base / 'router.sqlite', credit_reader=lambda: '11.63')
    server = model_router.Server(('127.0.0.1',0),store,TOKEN)
    server.enable_tls(str(cert),str(key))
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    config = base / 'client.json'
    config.write_text(json.dumps(dict(schema=1,url='https://localhost:'+str(server.server_port),token=TOKEN,ca_pem=cert.read_text())))
    config.chmod(0o600)
    try: yield config, store, server
    finally:
        server.shutdown(); server.server_close(); thread.join()
