# Stream B VM change log

2026-10-30 preflight was read-only via existing pinned SSH host/key. No VM
source, policy, identity, service, worker or pointer was changed. Reversal: none
required. Returned public evidence: batch-service-vm-preflight-20261030.json.

Queries: systemctl is-active for holder, resume timer, model router and batch
service; SHA256 of four public factory modules if present; one bounded
boat-call list --json, interpreted only when pageInfo.hasMore is false.

Result: holder and resume timer active; router/batch units inactive. Complete
Boat inventory has zero workers. batch_money.py, batch_service.py and
model_router.py absent. key_holder.py prior hash:
0d71d21df8653768eb2556d6eb9371d6178bff9031d57e8cdb8928ac4612293b.
No new hash (no change). Inventory alone is not proof that no controller owns
an uncertain launch. A later deployment must verify controller ownership,
record prior policy/unit hashes and exact rollback, and satisfy the reviewed
holder/ACK/source/restore and router per-call-maxima prerequisites first.

Workers created/deleted: none. Live model/infra spend:0/0. No exam case touched.


2026-10-31 preparation: inspected complete Boat inventory (zero workers), the
legacy controller journal (one unresolved launch with a free lock), credential
labels, money-state absence and the missing unbug command. Public details are in
stream-b-preparation-preflight-20261031.json. Stopped holder and resume timer/service
under the preparation authorization; disabled holder and timer to keep them off
across reboot; final service states inactive. Staged the
6ac450e release in /home/user/.unbug-control/releases/practice-6ac450e and verified
its SHA256 and all member pins. No source, active policy, identity or secret
bundle changed. No worker or model call. Rollback and blockers are in the updated
activation-practice plan. This is dormant staging, not completed installation.
