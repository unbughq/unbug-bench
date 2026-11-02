import base64
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import threading
import ssl
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'factory'))
import router_delivery as delivery
import model_router
from router_delivery_support import router, TOKEN


def archive(names=('claude-token',)):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as tar:
        for name in names:
            data=b'public-placeholder'; member=tarfile.TarInfo(name); member.size=len(data)
            tar.addfile(member,io.BytesIO(data))
    return base64.b64encode(stream.getvalue())


@unittest.skipUnless(shutil.which('openssl'),'openssl required for offline TLS proof')
class DeliveryTests(unittest.TestCase):
    def test_pack_and_real_authenticated_tls(self):
        with tempfile.TemporaryDirectory() as tmp, router(tmp) as (config,store,server):
            packed=delivery.pack(archive(),config)
            with tarfile.open(fileobj=io.BytesIO(base64.b64decode(packed))) as tar:
                self.assertEqual(set(tar.getnames()),{'claude-token',*delivery.NAMES})
                self.assertEqual(tar.extractfile('factory-router-token').read().decode(),TOKEN)
                self.assertTrue(all(tar.getmember(n).mode==0o600 for n in delivery.NAMES))
            value=json.loads(config.read_text())
            with patch.dict(os.environ,FACTORY_ROUTER_URL=value['url'],FACTORY_ROUTER_TOKEN=TOKEN,
                            FACTORY_ROUTER_CA_FILE=str(Path(tmp)/'cert.pem'),HTTPS_PROXY='http://127.0.0.1:1'):
                self.assertIn('paid',model_router._rpc('status',{}))
                lease=model_router._rpc('acquire',dict(id=uuid.uuid4().hex,
                    model='openrouter/minimax/minimax-m3.1-flash',accounts=['openrouter-key'],
                    role='writer',deadline=time.time()+3600,paid_protocol=1))
                self.assertEqual(lease['kind'],'lease')
                model_router._rpc('start',{'lease_id':lease['lease_id']})
                paid=dict(lease_id=lease['lease_id'],request_id=uuid.uuid4().hex)
                self.assertTrue(model_router._rpc('paid_reserve',paid)['granted'])
                self.assertTrue(model_router._rpc('paid_settle',paid | {'usage':dict(prompt_tokens=1,completion_tokens=1)})['settled'])
            with self.assertRaises(ValueError): delivery.pack(archive(('factory-router-token',)),config)

    def test_bad_config_token_trust_and_hostname_refuse(self):
        with tempfile.TemporaryDirectory() as tmp, router(tmp) as (config,store,server):
            original=json.loads(config.read_text())
            for changes in ({'token':'wrong'}, {'token':'bad\nheader'}, {'url':'http://localhost'},
                            {'url':original['url'].replace('localhost','127.0.0.1')},
                            {'ca_pem':'not a certificate'}, {'schema':True}, {'extra':1}):
                with self.subTest(changes=list(changes)):
                    config.write_text(json.dumps({**original,**changes}))
                    with self.assertRaises(Exception): delivery.pack(archive(),config)
            config.write_text(json.dumps(original)); config.chmod(0o644)
            with self.assertRaises(ValueError): delivery.read_config(config)
            config.chmod(0o600)
            linked=Path(tmp)/'linked'; linked.symlink_to(config)
            with self.assertRaises(OSError): delivery.read_config(linked)
            config.write_text('{"schema":1,"schema":1}')
            with self.assertRaises(ValueError): delivery.read_config(config)
            config.write_text(json.dumps({**original,'token':'wrong'}))
            result=subprocess.run([sys.executable,'-B',str(ROOT/'factory/router_delivery.py')],
                input=archive(),capture_output=True,env={**os.environ,'UNBUG_ROUTER_CLIENT_FILE':str(config)})
            self.assertEqual(result.returncode,1)
            self.assertEqual(result.stdout,b'')
            self.assertEqual(result.stderr,b'router delivery refused\n')
            self.assertNotIn(TOKEN.encode(),result.stderr)

    def test_wrong_ca_and_redirect_refuse_without_forwarding(self):
        with tempfile.TemporaryDirectory() as tmp, router(Path(tmp)/'one') as (config,_,__), router(Path(tmp)/'two') as (other,_,__):
            value=json.loads(config.read_text()); wrong=json.loads(other.read_text())
            with self.assertRaises(model_router.RouterUnavailable):
                model_router.router_request(value['url'],TOKEN,'status',{},ca_pem=wrong['ca_pem'])
            calls=[]
            class Redirect(BaseHTTPRequestHandler):
                def log_message(self,*a): pass
                def do_POST(self):
                    calls.append(self.path)
                    self.send_response(302);self.send_header('Location','/second');self.end_headers()
            server=ThreadingHTTPServer(('127.0.0.1',0),Redirect)
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(Path(tmp)/'one/cert.pem'),str(Path(tmp)/'one/key.pem'))
            server.socket=context.wrap_socket(server.socket,server_side=True)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with self.assertRaises(model_router.RouterUnavailable):
                    model_router.router_request('https://localhost:'+str(server.server_port),TOKEN,'status',{},ca_pem=value['ca_pem'])
                self.assertEqual(calls,['/status'])
            finally:server.shutdown();server.server_close();thread.join()

    def test_resume_requires_worker_files_without_host_client(self):
        source=(ROOT/'factory/launch.sh').read_text()
        selected=source[source.index('router_names=""'):source.index('# On the VM:')]
        exports=source[source.index('vm_creds="'):source.index('# One bench run per')]
        with tempfile.TemporaryDirectory() as tmp:
            ram=Path(tmp)/'secrets'; ram.mkdir()
            values={'factory-router-url':'https://router.invalid', 'factory-router-token':TOKEN,
                    'factory-router-ca.pem':'public-ca-placeholder'}
            for name,value in values.items(): (ram/name).write_text(value)
            script='set -eu\nbatch_release=yes; secrets="claude-token codex-auth.json opencode-go-key openrouter-key"; claude_secret=claude-token; opencode_secret=opencode-go-key\n'+selected+'\nsecrets="$router_names"\n'+exports.replace('/dev/shm/secrets',str(ram))+'\neval "$vm_creds"\ntest "$FACTORY_ROUTER_TOKEN" = "'+TOKEN+'"\n'
            env={**os.environ,'UNBUG_RESUME_LAUNCH':'1','UNBUG_ROUTER_CLIENT_FILE':str(Path(tmp)/'missing')}
            env.pop('FACTORY_ACCOUNT_POLICY',None)
            result=subprocess.run(['/bin/sh','-c',script],env=env,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            for name in values:
                (ram/name).unlink()
                result=subprocess.run(['/bin/sh','-c',script],env=env,capture_output=True)
                self.assertNotEqual(result.returncode,0,name)
                self.assertNotIn(TOKEN.encode(),result.stdout+result.stderr)
                (ram/name).write_text(values[name])
        import control_resume
        self.assertIn('UNBUG_ROUTER_CLIENT_FILE',control_resume.ENVIRONMENT)
        self.assertFalse(any(k.startswith('FACTORY_ROUTER_') for k in control_resume.ENVIRONMENT))

    def test_shared_secrets_default_and_override(self):
        code='import worker_secrets,model_router,job_config,account_handoff,run; print(worker_secrets.SECRETS); assert all(x==worker_secrets.SECRETS for x in (model_router.SECRETS,job_config.SECRETS,account_handoff.SECRETS)); assert run.STATEMENTS_KEY==worker_secrets.SECRETS/"statements-key"'
        env={k:v for k,v in os.environ.items() if k!='UNBUG_TEST_WORKER_SECRETS'}
        env['PYTHONPATH']=os.pathsep.join((str(ROOT/'factory'),str(ROOT/'bin')))
        for expected in ('/dev/shm/secrets','/offline-only/ram'):
            if expected!='/dev/shm/secrets':env['UNBUG_TEST_WORKER_SECRETS']=expected
            p=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True,env=env)
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),expected)

if __name__=='__main__': unittest.main()
