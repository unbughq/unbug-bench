"""Manual real-Linux wall probe on one authorized disposable worker; no model calls.

Uses the real public S13 inventory and real pilot_wall. Only upstream HTTPS is
redirected to a synthetic stub. Run as worker user with passwordless sudo.
"""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'factory'),str(ROOT/'bin')]
import errno
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
import pwd
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import uuid
os.environ['BENCH']=str(ROOT)
import model_call_gate as gate
import model_router as router
import run
from token_prices import GATED_CLAUDE

CLIENT = """import http.client,json,socket,sys
host,port,request=sys.argv[1],int(sys.argv[2]),sys.argv[3]=='post'
try:
 if request:
  c=http.client.HTTPConnection(host,port,timeout=2)
  c.request('POST','/v1/messages',json.dumps(dict(model='claude-opus-5-5',max_tokens=40000,messages=[dict(role='user',content='synthetic wall probe')])),{'Authorization':'Bearer synthetic-wall-only','Content-Type':'application/json'})
  r=c.getresponse(); data=json.loads(r.read()); c.close()
  print(json.dumps(dict(reached=True,status=r.status,model=data.get('model'))))
 else:
  s=socket.create_connection((host,port),timeout=2);s.close();print(json.dumps(dict(reached=True)))
except OSError as error: print(json.dumps(dict(reached=False,error=type(error).__name__,errno=error.errno)))
"""


def command(argv):
    return subprocess.run(argv,check=True,capture_output=True,text=True,timeout=30)


def main():
    if sys.platform!='linux': raise SystemExit('real Linux required')
    os.environ['BENCH']=str(ROOT)
    users=('gateprobe-a','gateprobe-b')
    for user in users:
        try: pwd.getpwnam(user)
        except KeyError: pass
        else: raise SystemExit('refusing preexisting test identity')
    result={'scope':'real pilot_wall; synthetic upstream; no provider/model credentials',
            'status':'running','platform':os.uname().machine,'checks':[],'uids':{},'rules':{},'requests':[],
            'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in (ROOT/'factory/model_call_gate.py',ROOT/'factory/model_runtime.py',ROOT/'factory/run.py',Path(__file__).resolve())}}
    def check(name,user,port,reached,host='127.0.0.1',post=False):
        response=json.loads(command(['sudo','-u',user,sys.executable,'-c',CLIENT,host,str(port),'post' if post else 'connect']).stdout)
        result['checks'].append(dict(name=name,user=user,host=host,port=port,**response))
        assert response['reached']==reached,(name,response)
        if post: assert response.get('status')==200 and response.get('model')=='claude-opus-5-5'
    def rules(user):
        return {binary:command(['sudo',binary,'-w','5','-S','factory-'+user]).stdout.splitlines()
                for binary in ('iptables','ip6tables')}
    class Stub(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert body['max_tokens']==32768 and body['inference_geo']=='global'
            assert self.headers.get('Authorization')=='Bearer synthetic-wall-only'
            result['requests'].append({'model':body['model'],'max_tokens':body['max_tokens'],'inference_geo':body['inference_geo']})
            data=json.dumps(dict(type='message',model='claude-opus-5-5',stop_reason='end_turn',
                content=[dict(type='text',text='stub only')],usage=dict(input_tokens=1,output_tokens=1,
                cache_read_input_tokens=0,cache_creation_input_tokens=0,speed='standard',inference_geo='global'))).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Stub)
    thread=threading.Thread(target=lambda:upstream.serve_forever(poll_interval=.05),daemon=True);thread.start()
    created=[];walls=[];listeners=[]
    try:
        with tempfile.TemporaryDirectory(prefix='gate-wall-proof-') as temporary:
            root=Path(temporary);(root/'case/base').mkdir(parents=True);(root/'work/logs').mkdir(parents=True)
            shutil.copyfile(ROOT/'scenarios/dev/S13-marketplace/scenario.json',root/'case/base/scenario.json')
            c=SimpleNamespace(case=root/'case',work=root/'work',args=SimpleNamespace(agent_timeout=30),factory_slot=0)
            for user in users:
                command(['sudo','useradd','--system','--no-create-home','--shell','/usr/sbin/nologin',user]);created.append(user)
                result['uids'][user]=pwd.getpwnam(user).pw_uid
                walls.append(user);run.pilot_wall(c,user,0)
                result['rules'][user]=rules(user)
            for host,port in (('127.0.0.1',0),('127.0.0.1',9000),('127.0.0.1',9010),('::1',0)):
                sock=socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET,socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind((host,port));sock.listen(20);listeners.append(sock)
            other,bench,service,v6=listeners
            check('other-local-before',users[0],other.getsockname()[1],False)
            check('bench-allow-before',users[0],9000,True)
            check('service-allow-before',users[0],9010,True)
            real_gate=gate.Gate
            def observe(*args,**kwargs):
                instance=real_gate(*args,**kwargs)
                try:check('gate-denied-before-rule',users[0],instance.server.server_port,False)
                except BaseException:instance.close();raise
                return instance
            def connect(host,**kwargs):
                assert host=='api.anthropic.com'
                return http.client.HTTPConnection('127.0.0.1',upstream.server_port,**kwargs)
            for exceptional in (False,True):
                current=router.Lease(uuid.uuid4().hex,GATED_CLAUDE,'claude-token',time.time()+180,
                    'subscription','anthropic','claude-token',**router.route_maximum(GATED_CLAUDE));used={}
                try:
                    with patch.object(gate,'Gate',side_effect=observe),patch.object(gate.http.client,'HTTPSConnection',side_effect=connect):
                        with gate.enforce(current,{'CLAUDE_CODE_OAUTH_TOKEN':'synthetic-wall-only'},used,20,user=users[0]) as instance:
                            port=instance.server.server_port
                            check('gate-reached-with-rule',users[0],port,True,post=True)
                            check('other-local-during',users[0],other.getsockname()[1],False)
                            check('other-uid-denied',users[1],port,False)
                            check('ipv6-local-denied',users[0],v6.getsockname()[1],False,host='::1')
                            check('bench-allow-during',users[0],9000,True)
                            check('service-allow-during',users[0],9010,True)
                            result['rules']['active-exceptional-'+str(exceptional)]=rules(users[0])
                            if exceptional:raise ValueError('synthetic invocation failure')
                except ValueError as error:
                    if not exceptional or str(error)!='synthetic invocation failure':raise
                assert used['closed'] and used['validated_requests']==1 and used['unknown_requests']==0,used
                result.setdefault('cap_used',[]).append(used)
                assert rules(users[0])==result['rules'][users[0]]
                with socket.socket() as rebound:
                    rebound.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);rebound.bind(('127.0.0.1',port));rebound.listen(5)
                    check('reused-gate-port-denied',users[0],port,False)
                check('other-local-after',users[0],other.getsockname()[1],False)
            for user in users:assert rules(user)==result['rules'][user]
            result['status']='passed'
    finally:
        for sock in listeners:sock.close()
        upstream.shutdown();upstream.server_close();thread.join(timeout=1)
        cleanup=[]
        for user in reversed(walls):
            try:
                # The TemporaryDirectory may already be removed when unwinding.
                c.work.mkdir(parents=True,exist_ok=True);(c.work/'logs').mkdir(exist_ok=True)
                run.pilot_wall(c,user,0,remove=True)
                for binary in ('iptables','ip6tables'):
                    query=subprocess.run(['sudo',binary,'-w','5','-S','factory-'+user],capture_output=True,text=True,timeout=30)
                    assert query.returncode!=0,'chain retained'
            except BaseException as error:cleanup.append(type(error).__name__)
        for user in reversed(created):
            try:command(['sudo','userdel',user])
            except BaseException as error:cleanup.append(type(error).__name__)
        result['cleanup_errors']=cleanup
        if cleanup or result['status']!='passed':result['status']='failed'
        if 'root' in locals():shutil.rmtree(root,ignore_errors=True)
        print(json.dumps(result,indent=2),flush=True)
        if cleanup:raise RuntimeError('test identity/wall cleanup failed')


if __name__=='__main__':main()
