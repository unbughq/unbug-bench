# Account-2 credential audit, 2026-10-31

Read-only SSH audit of control VM unbug-control (172111861, 2.31.89.209).
Used the existing per-server known-host file and scoped SSH key. Decrypted
/home/user/.config/unbug-bench/secrets.age in memory on the VM using its existing
/home/user/.unbug-control/control.key. No secret bytes left the VM, reached
output or arguments, or were persisted. No files or services were changed.

Both claude-token (account-1 label) and claude-factory-token-2 (account-2 label)
exist and are nonempty. No credential is missing under either label. An
in-memory SHA-256 fingerprint comparison returned credential_fingerprints_equal:
false. Neither token nor fingerprint values were output or retained. Different
credentials do not establish different human accounts.

Attempted read-only GET https://api.anthropic.com/api/oauth/profile for each
credential, comparing only account UUIDs in VM memory if available. Both calls
returned HTTP 403; no response bodies or identifiers were printed. Distinct
accounts are therefore UNVERIFIED. Different labels or token bytes cannot prove
different accounts, and 403 here does not prove inference credentials expired.
The endpoint is used by Claude Code (upstream report:
https://github.com/anthropics/claude-code/issues/81231).

Before activation, the founder must privately confirm the account mapping or
provide profile-readable authentication for each account through the existing
secret prompt so an authenticated UUID comparison can complete. Never enter
credentials in chat. If account-2 mapping is wrong or its token is unusable,
provide a valid Claude Code OAuth/setup token generated while signed into the
SECOND Claude account, privately to the existing secret provisioning flow;
replace only claude-factory-token-2 in the control VM encrypted bundle at
/home/user/.config/unbug-bench/secrets.age. Keep claude-token for account 1.
This task does not rotate credentials, deploy, or launch workers.
