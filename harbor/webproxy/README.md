# Contestant website audit

The overlay gives `main` only a Docker `internal: true` network. The separate
`webproxy` service has that network plus ordinary egress. Requests that honor
`HTTP_PROXY` / `HTTPS_PROXY` work; direct internet TCP from `main` or its nested
Docker containers fails. Keep Harbor's network policy `public`: this Compose
network, rather than Harbor's OUTPUT-only policy, constrains forwarded packets.
No host ports, Docker socket, private CA, or audit volume are exposed to `main`.
Audited model agents additionally use [keyswap](../keyswap/README.md) over local
HTTP with placeholder auth; keyswap records fixed upstream method/path metadata
in this same audit volume. Its upstream HTTPS is separate from webproxy. boat.dev
and its subdomains are denied for both HTTP and CONNECT and never passed through.

```sh
export UNBUG_WEBPROXY_DIR="$(pwd)/harbor/webproxy"
harbor run -p harbor/medusa-oversell -a nop \
  --extra-docker-compose "$UNBUG_WEBPROXY_DIR/docker-compose.webproxy.yaml"
```

Add this table to the generated task's top-level `artifacts` list alongside its
existing guard and claims entries:

```toml
{ source = "/log/web.jsonl", destination = "web/web.jsonl", service = "webproxy" }
```

Harbor 0.24 collects it into each step's `artifacts/web/web.jsonl`. The file is
cumulative across steps; count each event once when combining checkpoints. Its
append-only behavior is implemented by the proxy, not an immutable storage
guarantee. The final artifact and its manifest should be retained with the job.
The overlay paths are absolute bind mounts, so it supports local Docker and a
Docker host with the same staged paths. Remote providers need these files staged
on their Docker host; remote-provider upload behavior has not been tested.

`start-main.sh` waits for the public CA, installs it into the system trust store,
then runs the existing `start-dockerd`. Node and Python trust settings are supplied.
Clients with their own trust stores must also trust that public CA. Do not disable
TLS verification for contestant web traffic. The proxy generates a fresh private
CA in a project-scoped volume and exposes only its public certificate to `main`.

## What is recorded

One JSON object per observed CONNECT or HTTP request, recorded before forwarding:

```json
{"schema":1,"timestamp":"2026-10-14T21:24:16.138702+00:00","method":"GET","url":"https://github.com/medusajs/medusa/issues/17032","domain":"github.com","visibility":"request"}
```

The URL retains scheme, domain, nondefault port and path. Userinfo, **all query
parameters**, and fragments are removed. Common credential prefixes and long
opaque path segments are redacted. No headers, cookies, authorization, request or
response bodies, saved flows, or TLS payloads are written. A short arbitrary
secret embedded in a path cannot reliably be distinguished from a public page
identifier; path redaction is best effort. The log is access-controlled audit
data, not a general-purpose public artifact.

For the fixed `MODEL_HOSTS` list and strictly bounded `*.oaiusercontent.com`
suffix in `audit.py`, HTTPS uses the `tls_clienthello`
hook to allow TLS pass-through only when CONNECT authority and TLS SNI match
exactly on port 443. The log records only CONNECT,
domain and port, never the API path, authorization or body. Plain HTTP to those
hosts is rejected. Configure any additional provider/auth host in `MODEL_HOSTS`
before use; otherwise its TLS will be
intercepted as ordinary web traffic. Generic `ignore_hosts` is deliberately absent:
it also trusts attacker-controlled SNI and permits hiding public requests in an
opaque tunnel. API/public SNI mismatches and IP tricks fail the TLS handshake;
intercepted HTTP request authorities must also match their CONNECT target.
The HTTP Host inside opaque API TLS cannot be examined; its connection is
restricted to the exact allowed API destination. The list includes OpenAI/ChatGPT
authentication, observed `ab.chatgpt.com` telemetry, and Anthropic/Claude hosts.
OpenAI's official
[network guidance](https://help.openai.com/en/articles/9247338-network-recommendations-for-chatgpt-errors-on-web-and-apps)
documents its provider domain families and Codex's `wss://chatgpt.com` traffic.
Provider content-host paths are also hidden: public content accessed through
such a URL would appear only as a CONNECT. The synthetic tests below do not
claim to test live provider authentication.

Ordinary HTTPS is intercepted with the test CA to expose the public path. CONNECT
alone means a tunnel was attempted, not that a page loaded. GET means a request
was observed, not that a successful response was returned. Cached/local pages,
browser history, external tools running outside this network, and information
already in the model are not observable. This supports auditing visits to public
fixes; it does not prove contestants never learned a fix elsewhere.

## Isolation and operational limits

Missing CA/proxy prevents startup; a stopped proxy prevents internet requests.
Any audit-write or flush failure terminates the proxy before further forwarding.
There is no direct-network fallback. Proxy console flow output is disabled and
raw TCP forwarding is disabled. DNS resolution itself is not a website visit and
is not logged; Docker's embedded DNS is not a DNS-exfiltration defense.

Docker network isolation was tested for normal main and nested-container
traffic. **The current contestant is privileged and root: it can potentially
escape to host namespaces, tamper with sibling containers, or otherwise bypass
Docker isolation.** This overlay is not an adversarial security boundary for
such a contestant. Run one attempt per disposable VM and treat the host as trusted;
stronger enforcement requires controls outside the contestant's privilege domain.
Do not attach another main network, host networking, a host Docker socket, or
other egress-capable peers. Additional sidecars must be assigned networks
deliberately. Review the final merged Compose config before a scored run.

`start-main.sh` configures the isolated Docker client's proxy defaults with the
proxy's resolved address. It writes the public CA build argument into both
`/app/.env` and `/app/projects/medusa/.env`; Compose selects the project directory.
The Medusa Dockerfile accepts that optional argument and trusts the public CA
for its npm install. Normal builds use Node's built-in roots. Arbitrary new nested
images/tools still need their own CA trust; do not bypass TLS verification.

Actual full Medusa setup passed in 400.36 seconds: 1,070 packages installed,
1,074 npm HTTP requests audited, image build, migrations, seed, two resets and
both health endpoints passed. Direct external TCP was blocked. Evidence is in
`results/infrastructure/2026-10-14-medusa-proxy/`; reproduce with
`rtk proxy python3 tests/live/harbor/webproxy/test_medusa.py`.
Actual two-session Codex subscription auth also passed through the proxy
(`harbor/codex/evidence/combined-20261014.json`). Claude and the model-backed owner
answerer have not been called. The optional OpenRouter owner path currently has
metadata-only MITM logging rather than the contestant API's opaque TLS exception.

## Verification (2026-10-14, local Docker, Harbor 0.24.0)

```sh
rtk proxy python3 tests/live/harbor/webproxy/test_webproxy.py
rtk proxy python3 tests/live/harbor/webproxy/test_harbor.py
```

Both passed. The first verifies HTTP logging; trusted HTTPS logging of the full
GitHub issue path; query-secret removal; direct internet denial in main and a
nested Redis container; proxy-down failure; and TLS pass-through to a **local
synthetic** `api.openai.com` server with fake authorization and body absent from
all audit output. Regressions reject public CONNECT with model SNI, the inverse,
literal-IP tricks, and mismatched intercepted request Host. It never calls a real
model API. The second creates a temporary
one-step Harbor task with `nop` and proves sidecar artifact collection. Tests own
unique Compose projects, remove their volumes, and make no Claude/model calls.
They require the existing `unbug-bench-box:dev` and `redis:7.4.8-bookworm` images.
Stage an immutable copy of this directory for each run: mitmproxy automatically
reloads a changed addon file, so editing a live bind-mounted `audit.py` can stop
the proxy or mix logging implementations within a trial. Log initialization
failures terminate the proxy rather than allowing unlogged requests.

mitmproxy is pinned to 12.1.2 and its multi-platform image digest. Its official
[event hooks](https://docs.mitmproxy.org/stable/api/events.html) and
[options](https://docs.mitmproxy.org/stable/concepts/options/) describe the
CONNECT/request/TLS hooks, streaming and the unsafe generic `ignore_hosts`
matching behavior avoided here.
