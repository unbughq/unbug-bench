"""Prepared attempts reuse a held grant and check the release at dispatch."""
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PreparedAttempt(unittest.TestCase):
    def test_prepared_dispatch_and_stale_paths(self):
        program = textwrap.dedent('''
            import logging, os, sys
            from pathlib import Path
            logging.disable(logging.CRITICAL)
            for key in ("DBOS_CONDUCTOR_KEY", "DBOS_CONDUCTOR_URL"):
                os.environ.pop(key, None)
            root, work, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
            sys.path[:0] = [str(root / "factory"), str(root / "tests/factory")]
            from dbos import DBOS, SetWorkflowID
            from durable.contract import ArtifactKind, Ref, Step, StepInput, StepKind, to_record
            from durable.executor import Executor
            from durable import engine
            from test_durable_engine_fakes import build_fakes, seed_batch

            f = build_fakes(work / "state", {})
            spec, registry = seed_batch(f, {})
            key = f["keys"].scope_key(spec.batch_id)
            latest, ciphertext = f["sealer"].seal(key, ArtifactKind.STATEMENT_REGISTRY, b"registry: latest")
            f["store"].put_sealed(spec.batch_id, latest, ciphertext)
            ex = Executor(f["pool"], f["worker"], f["ledger"], f["store"], f["sealer"], f["keys"],
                          poll_interval_s=0.02, grace_s=0.3)
            ex.open_batch(spec.batch_id, spec.money_bound_usd_micros)
            kind = StepKind.SEAL if mode == "seal" else StepKind.ADMIT
            snapshot = Ref("a" * 64, ArtifactKind.CASE_SNAPSHOT) if kind is StepKind.SEAL else None
            si = StepInput(spec.batch_id, "case-t-1", 1, Step(kind), 1, spec.plumbing_version,
                           spec.bench_version, spec.inputs, snapshot, 60, 0,
                           registry=registry if kind is StepKind.ADMIT else None)
            grant = ex.reserve(si, request=spec.case_money_usd_micros, case_limit=spec.case_money_usd_micros,
                               draws_case_money=True)
            lease = ex.lease_for(si.case_id, si.plumbing_version, si.bench_version)
            if mode == "dead": f["pool"].kill(si.case_id)
            plumbing = "3" * 64 if mode in ("plumbing", "seal") else si.plumbing_version
            engine._RT.executor = ex
            engine._RT.timing = engine.Timing(queue_poll_s=0.05, listener_poll_s=0.05)
            DBOS(config={"name": "prepared-test", "application_version": "prepared-test-1",
                         "system_database_url": f"sqlite:///{work}/sys.sqlite",
                         "notification_listener_polling_interval_sec": 0.05})
            DBOS.launch()
            DBOS.register_queue(engine.steps_queue(spec.batch_id), global_concurrency=1,
                                polling_interval_sec=0.05, on_conflict="always_update")
            @DBOS.workflow()
            def batch_stub():
                DBOS.set_event("plumbing", plumbing)
                DBOS.set_event("bench", si.bench_version)
                DBOS.set_event("registry", to_record(latest))
                DBOS.recv("exit", timeout_seconds=30)
            with SetWorkflowID(spec.batch_id):
                DBOS.start_workflow(batch_stub)
            assert DBOS.get_event(spec.batch_id, "registry", timeout_seconds=10) == to_record(latest)
            job = {"input": to_record(si), "grant": to_record(grant), "lease": to_record(lease),
                   "lease_plumbing": si.plumbing_version, "lease_bench": si.bench_version, "prev": None}
            workflow = si.idempotency_key + "/prepared"
            with SetWorkflowID(workflow):
                handle = DBOS.retrieve_queue(engine.steps_queue(spec.batch_id)).enqueue(
                    engine.prepared_attempt_workflow, job)
            result = handle.get_result()
            state = f["ledger"].snapshot()
            row = state["res"][si.idempotency_key]
            starts = [x for x in f["worker"].f.lines("worker.log") if x["op"] == "start"]
            reserves = [x for x in f["ledger"].f.lines("ledger.log") if x["op"] == "reserve"]
            assert len(reserves) == 1, reserves
            if mode == "run":
                assert result["started"] and result["result"]["outcome"] == "ok", result
                assert result["input"]["registry"] == to_record(latest), result
                assert result["input"]["money_ceiling_usd_micros"] == grant.amount_usd_micros
                assert len(starts) == 1 and starts[0]["opened"]["registry"] == "registry: latest", starts
                assert row["settled"] is not None, state
                context = DBOS.get_event(workflow, "attempt_context", timeout_seconds=5)
                assert context["key"] == si.idempotency_key and context["lease"] == to_record(lease), context
                assert context["grant"] == to_record(grant), context
            else:
                expected = "rerun_gates" if mode == "seal" else "stale_preparation"
                assert result == {"started": False, "action": expected}, result
                assert not starts and row["settled"] is None, state
                assert DBOS.get_event(workflow, "attempt_context", timeout_seconds=0.1) is None
            os._exit(0)
        ''')
        for mode in ("run", "plumbing", "dead", "seal"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as work:
                result = subprocess.run([sys.executable, "-B", "-c", program, str(ROOT), work, mode],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
