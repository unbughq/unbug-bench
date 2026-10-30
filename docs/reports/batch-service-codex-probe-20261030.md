# Codex prerequisite probes, 2026-10-30

Credential-free local pin probe:

```
npm exec --yes --package=@openai/codex@0.162.1 -- codex --version
npm exec --yes --package=@openai/codex@0.162.1 -- codex app-server generate-json-schema --out /tmp/unbug-codex-01621-schema
```

Version reported codex-cli0.162.1; schema generation exited0. No account or
model call was made. Public schema GetAccountParams defines refreshToken:true
as proactive managed-auth refresh; external auth ignores the flag. Hashes:

- GetAccountParams.json: 30b545275f60975b55bd6fbaafd70f15505801d14168ee82d3931b6e93c78aab
- GetAccountResponse.json: c3092dd8e52c2933c5ba5f0bf92377174f65bed627ff4ef5d7c04a189dd34fd1

Read-only control VM capability probe over the authorized SSH connection used
the existing scoped VM key and streamed the encrypted secrets bundle through
tar inspection in memory. Only these booleans were returned:

```
{"bundle_verified":true,"codex_managed_refresh_capable":true,"r2_config_present":true}
```

No identity/token/credential bytes were printed, copied off the VM or written
to disk. No VM files/services changed, no refresh/network request to a model
provider, and no worker creation. This proves prerequisite availability only.
It does not prove token validity, successful refresh/rotation, R2 prefix scope,
delivery to workers or router health. The Codex increment still needs its
reviewed host-refresh/credential addendum and real qualification.
