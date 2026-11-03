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
