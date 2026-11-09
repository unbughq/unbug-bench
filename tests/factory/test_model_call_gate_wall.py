"""Exact invocation wall rules and fail-closed socket ownership; no firewall mutation."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'factory'), str(ROOT/'bin')]
import errno
import gzip
import json
import shlex
import socket
import shutil
import tempfile
import subprocess
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid
import model_call_gate as gate
import model_router as router
import model_runtime
import run
from budget import BudgetError
from token_prices import GATED_CLAUDE


def lease():
    return router.Lease(uuid.uuid4().hex, GATED_CLAUDE, 'claude-token', time.time()+180,
        'subscription', 'anthropic', 'claude-token', **router.route_maximum(GATED_CLAUDE))


class WallTests(unittest.TestCase):
    def setUp(self):
        # Test-only cleanup of deliberately retained sockets, after checking ownership.
        self.retained = len(gate._RETAINED)
        self.addCleanup(self.release_retained)
        self.lookup = patch.object(gate.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=24001))
        self.lookup.start(); self.addCleanup(self.lookup.stop)
        self.commands = []

    def release_retained(self):
        for server in gate._RETAINED[self.retained:]: server.server_close()
        del gate._RETAINED[self.retained:]

    def command(self, argv, **kwargs):
        self.assertEqual(kwargs, dict(check=True, capture_output=True, timeout=30))
        self.commands.append(argv)
        if argv[4]=='-D': self.assert_bound(int(argv[argv.index('--dport')+1]))
        return subprocess.CompletedProcess(argv, 0)

    def enter(self, current, used, cancel=None, user='pilot'):
        return gate.enforce(current, {'CLAUDE_CODE_OAUTH_TOKEN':'synthetic-only'}, used, 3, cancel, user=user)

    def assert_bound(self, port):
        with socket.socket() as sock:
            with self.assertRaises(OSError) as error: sock.bind(('127.0.0.1', port))
        self.assertEqual(error.exception.errno, errno.EADDRINUSE)

    def test_saved_real_linux_wall_proof(self):
        record=json.loads(gzip.decompress((ROOT/'tests/factory/fixtures/router-gate-wall-linux.json.gz').read_bytes()))
        proof=record['probe'];self.assertEqual((record['status'],proof['status']),('passed','passed'))
        self.assertEqual(proof['cleanup_errors'],[]);self.assertEqual(len(proof['checks']),21)
        self.assertEqual(record['deletion_completion']['targetId'],record['worker_id'])
        self.assertEqual(record['deletion_completion']['status'],'completed')
        self.assertTrue(record['absent_from_inventory'])
        self.assertLess(record['cost_summary']['conservative_usd_through_confirmed_deletion'],.10)
        allowed={'bench-allow-before','service-allow-before','gate-reached-with-rule','bench-allow-during','service-allow-during'}
        for check in proof['checks']:self.assertEqual(check['reached'],check['name'] in allowed)
        base=proof['rules']['gateprobe-a']
        ports=[c['port'] for c in proof['checks'] if c['name']=='gate-reached-with-rule']
        self.assertEqual(len(ports),2)
        for exceptional,port in zip((False,True),ports):
            active=proof['rules']['active-exceptional-'+str(exceptional)]
            self.assertEqual(active['ip6tables'],base['ip6tables'])
            self.assertEqual(active['iptables'][:1]+active['iptables'][2:],base['iptables'])
            rule=shlex.split(active['iptables'][1]);comment=rule[rule.index('--comment')+1]
            self.assertRegex(comment,r'^factory-gate:[0-9a-f]{32}$')
            self.assertEqual(rule,['-A','factory-gateprobe-a','-d','127.0.0.1/32','-o','lo','-p','tcp',
                '-m','owner','--uid-owner',str(proof['uids']['gateprobe-a']),'-m','tcp','--dport',str(port),
                '-m','comment','--comment',comment,'-j','ACCEPT'])
        for used in proof['cap_used']:
            self.assertTrue(used['closed']);self.assertEqual(used['validated_requests'],1)
            self.assertEqual(used['unknown_requests'],0)

    def test_runtime_passes_each_isolated_cli_user_to_the_real_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'transcripts').mkdir()
            runtime=model_runtime.ModelRuntime(root,Mock(),Mock(),lambda p,**kw:shutil.rmtree(p),Mock())
            for user in ('pilot','pilot-strong','pilot-easy'):
                current=lease();used={}
                c=SimpleNamespace(model_lease=current,_model_launch_permit=current.lease_id,
                    card={'roles':{}},args=run.argument_parser().parse_args(['--source','hunt']),
                    work=root,ledger=root/'ledger.json',model_cap_used=used,
                    model_env={'CLAUDE_CODE_OAUTH_TOKEN':'synthetic-only'})
                def process(argv,cwd,env,*args,**kwargs):
                    self.assertIn(user,argv);self.assertIsNone(cwd)
                    self.assertEqual(self.commands[-1][5],'factory-'+user)
                    self.assertTrue(env['ANTHROPIC_BASE_URL'].startswith('http://127.0.0.1:'))
                    return SimpleNamespace(returncode=0)
                with patch.object(gate.subprocess,'run',side_effect=self.command), \
                     patch.object(model_runtime,'case_budget_boundary'),patch.object(model_runtime,'update_case_budget'), \
                     patch.object(model_runtime,'pinned_cli',return_value='synthetic-no-cli'), \
                     patch.object(model_runtime.ModelRuntime,'_hand_to',lambda self,c,user,staged:staged), \
                     patch.object(model_runtime,'run_budgeted',side_effect=process):
                    self.assertEqual(runtime._invoke(c,[GATED_CLAUDE],'synthetic',root,'strong-calibrator-1',user=user),0)
                self.assertTrue(used['closed']);self.assertEqual(self.commands[-1][4:6],['-D','factory-'+user])

    def test_rule_scope_cancel_independent_cleanup_and_no_user(self):
        current=lease();used={};cancel=threading.Event()
        with patch.object(gate.subprocess,'run',side_effect=self.command):
            with self.enter(current,used,cancel) as instance:
                port=instance.server.server_port
                self.assert_bound(port)
                cancel.set()  # A run.sh callback would refuse deletion here.
            rule=['-m','owner','--uid-owner','24001','-o','lo','-d','127.0.0.1/32',
                  '-p','tcp','--dport',str(port),'-m','comment','--comment',
                  'factory-gate:'+current.lease_id,'-j','ACCEPT']
            self.assertEqual(self.commands,[['sudo','iptables','-w','5','-I','factory-pilot','1',*rule],
                                            ['sudo','iptables','-w','5','-D','factory-pilot',*rule]])
            with self.enter(lease(),{},user=None): pass
            self.assertEqual(len(self.commands),2)
        self.assertTrue(used['closed'])
        with socket.socket() as sock: sock.bind(('127.0.0.1',port))
        self.assertEqual(len(gate._RETAINED),self.retained)

    def test_concurrent_invocations_delete_only_their_exact_rule(self):
        first,second=lease(),lease()
        with patch.object(gate.subprocess,'run',side_effect=self.command):
            with self.enter(first,{}) as a:
                with self.enter(second,{}) as b:
                    self.assertNotEqual(a.server.server_port,b.server.server_port)
                self.assert_bound(a.server.server_port)
                self.assertEqual(self.commands[-1][-3],'factory-gate:'+second.lease_id)
            self.assertEqual(self.commands[-1][-3],'factory-gate:'+first.lease_id)
        self.assertEqual([c[4] for c in self.commands],['-I','-I','-D','-D'])

    def test_missing_identity_closes_before_any_insert_or_launch(self):
        used={}
        with patch.object(gate.pwd,'getpwnam',side_effect=KeyError('missing')), \
             patch.object(gate.subprocess,'run') as command:
            # A missing isolated user is a classified pre-launch stop, not a bare KeyError.
            with self.assertRaisesRegex(gate.BudgetError,'^model_wall_failed$'):
                with self.enter(lease(),used): self.fail('launched without wall')
        command.assert_not_called();self.assertTrue(used['closed'])
        self.assertEqual(len(gate._RETAINED),self.retained)

    def test_body_exception_revokes_before_release(self):
        used={}
        with patch.object(gate.subprocess,'run',side_effect=self.command):
            with self.assertRaisesRegex(ValueError,'synthetic failure'):
                with self.enter(lease(),used) as instance:
                    port=instance.server.server_port
                    raise ValueError('synthetic failure')
        self.assertEqual([c[4] for c in self.commands],['-I','-D'])
        self.assertTrue(used['closed'])
        with socket.socket() as sock: sock.bind(('127.0.0.1',port))

    def test_failed_revoke_keeps_socket_and_overrides_cap_and_body_error(self):
        used={}
        def command(argv,**kwargs):
            self.command(argv,**kwargs)
            if argv[4]=='-D': raise subprocess.CalledProcessError(1,argv)
        with patch.object(gate.subprocess,'run',side_effect=command):
            with self.assertRaisesRegex(BudgetError,'^cancellation_failed$'):
                with self.enter(lease(),used) as instance:
                    port=instance.server.server_port
                    self.assertIsNotNone(instance.state.reserve(32768))
                    instance.state.exhaustion.set()
                    raise ValueError('in flight')
        self.assert_bound(port)
        self.assertTrue(used['closed']);self.assertEqual(used['unknown_requests'],1)
        self.assertEqual(used['in_flight_requests'],0)
        self.assertEqual(len(gate._RETAINED),self.retained+1)

    def test_unconfirmed_insert_keeps_socket_even_after_successful_delete(self):
        for rejected in (False,True):
            with self.subTest(rejected=rejected):
                used={};self.commands=[];ports=[];rules=set()
                def command(argv,**kwargs):
                    self.command(argv,**kwargs)
                    port=int(argv[argv.index('--dport')+1]);ports.append(port)
                    if argv[4]=='-I':
                        if rejected: raise subprocess.CalledProcessError(1,argv)
                        rules.add(port)  # The insertion took effect before the uncertain result.
                        raise subprocess.TimeoutExpired(argv,30)
                    rules.discard(port)
                    return subprocess.CompletedProcess(argv,0)
                with patch.object(gate.subprocess,'run',side_effect=command):
                    with self.assertRaisesRegex(BudgetError,'^cancellation_failed$'):
                        with self.enter(lease(),used): self.fail('launched after uncertain insertion')
                self.assertEqual([c[4] for c in self.commands],['-I','-D'])
                self.assertEqual(rules,set());self.assert_bound(ports[0])
                self.assertTrue(used['closed']);self.assertEqual(used['forwarded_requests'],0)


if __name__=='__main__': unittest.main()
