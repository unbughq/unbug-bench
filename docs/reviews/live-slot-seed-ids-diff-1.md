**FAIL**

1. **BLOCKING — [factory/run_artifacts.py:53](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-aa3b949a9418dc299/factory/run_artifacts.py:53)**  
   Gathering still moves `.inventory-services.json` and the Compose inputs it references. After a checkpoint leaves an inventory service running, a snapshot can remove that state; the next reset then skips `stop_inventory_services()` because the state file is absent. The old service can remain running and cause a later service using the same port to fail. Keep the state and its referenced inputs available until cleanup, or stop the service at a safe point before gathering. Add a regression covering a snapshot between checkpoints with different services.

2. **NIT — [factory/run_artifacts.py:53](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-aa3b949a9418dc299/factory/run_artifacts.py:53)**  
   The stated recovery assumption for f46dac does not hold for a plumbing-only release. [factory/run.py:154](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-aa3b949a9418dc299/factory/run.py:154) imports `run_validity` from the pinned bench, so [runtime_revision](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-aa3b949a9418dc299/bin/run_validity.py:48) hashes the baked bench’s factory files, not the changed plumbing copy. The existing exhausted retry key can therefore remain in force. If this release is expected to recover f46dac, qualify a new bench image as well or bind the retry key to the active plumbing release. General retry reset on slot preparation remains optional as requested.

3. **NIT — [factory/run_artifacts.py:53](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-aa3b949a9418dc299/factory/run_artifacts.py:53)**  
   Gathering also moves `.prepared.json`. A later parallel checkpoint treats the slot as unprepared and rebuilds it, despite the preserved seed IDs. Preserve the receipt during gathering if avoiding repeated setup is desired, while still invalidating it when wipe removes the slot’s database.

The focused test would fail with the original mover and checks the reported fingerprint failure. `.slot-compose.yaml` and `.guard-compose.yaml` are recreated before use; `runs/baseline.json` is not read by later checkpoints. The seed file contains public fixture data, so excluding it from seal and wipe does not itself retain case evidence. No durable workflow steps were reordered. This was a read-only review; no tests were run.
Reviewer: Codex (gpt-6.1-terra), read-only, of commit f0f6e4e3 (gather fix only).

---

## Resolution (elephant)

- **1 (`.inventory-services.json` still moved): rejected; the second goldfish (Claude, other family) agreed.**
  This is a separate hazard that predates the change, and f46dac did not hit it. Excluding the
  state file alone would not help. Its saved Compose command names `.inventory-compose.json` and
  `.inventory-ports.yaml`, which also sit under `results/` with fresh mtimes. With those moved,
  `stop_inventory_services` would fail. The real fix changes the bench service lifecycle, so it
  needs its own design and Murphy row.
- **2 (the plumbing release does not reset the retry key): fixed.** `run.py` imports
  `run_validity` from the baked bench, so `runtime_revision` does not move. A second commit binds a
  slot checkpoint's retry identity to the digest of that slot's seed IDs, and
  `prepare_factory_slot` reseeds them. This is covered by
  `test_rebuilt_slot_gets_a_fresh_infra_allowance`, which failed before the fix.
- **3 (`.prepared.json` still moved): not taken (nit).** A moved receipt only triggers a
  re-prepare, and the slot heals itself. Keeping the receipt would make wipe leave a "ready" receipt
  for a slot whose database it has torn down.
