# Practice startup diagnosis (offline)

The one parent-approved read-only transfer retained the encrypted checkpoint and
wrapped case key in mode-700 scratch outside git. No worker/provider/Boat action,
remote mutation, identity transfer, plaintext key file or ledger change occurred.
Decryption used the existing control identity in-process; only ciphertext and a
sanitized exception/location extract crossed the connection. No secret material
was printed. Decrypted case material was not written to disk.

Real traceback: RuntimeError: exit 1, `/home/user/factory/run.py:3387` in main,
then `run.py:161` in sh. Retained location: `logs/runner.log:4–9`.
Underlying Docker exception at `logs/commands.log:3–4`: container name
`/unbug-bench-postgres-1` already in use. Exact sanitized extract is the committed
fixture. The public card's error label discarded this message; encrypted logs
retained it. The missing continuation-budget ledger follows the early crash
before any model request, so accounting refusal stays intact.

Local experiment: pinned source archive in mode-700 scratch, isolated Docker
project, cached images only, no pulls. A created old-Compose-labelled Postgres
container was successfully recreated. This does not reproduce the deleted
worker's exact Docker metadata; no stronger cause claim is made.

Parent authorized one additional read-only extraction, with no remote mutation.
Retained commands.log:1–2 reports Redis Creating and Postgres Creating, confirming
Compose did not adopt the conflicting container. Worker Compose version: 5.3.1.
The proposed removal-only fix was rejected by fresh review: it could defer the
failure until after paid work. Revision 2 preserves pre-model preparation through
the existing locked owner and adds fixed-name cleanup there.

Discriminating local Docker reproduction (cached images, isolated project): an
unlabelled fixed-name Postgres container produces the same name-conflict failure
(exit 1); it survives Compose down. Removing that exact name and re-running up
succeeds (exit 0). All experiment containers/volumes were removed; no shared
bench containers were modified. This proves the unadopted-name mechanism, not
the inaccessible old worker container's exact labels.
