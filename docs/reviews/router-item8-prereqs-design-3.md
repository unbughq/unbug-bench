**Verdict: PASS.** Nothing blocks it. I found two Major findings and three Nits. Both Majors are about how the design words its claims and records evidence. Neither needs a different fix.

I read the three personas in Mode REVIEW, `docs/ENGINEERING.md`, the design including its founder constraints and the amendment, the Allowance and Handler code in `factory/model_call_gate.py`, the test diff, the uncommitted Murphy row, and the two standards. I made no edits, delegations, paid calls, pushes or merges.

## The defect is real, and I reproduced it

I ran a local throwaway script against plain loopback, with no provider involved. It showed three things:
- **The socket does detach.** On a `Connection: close` response, `getresponse()` calls `self.close()`, so `connection.sock is None` while the response still holds the socket.
- **The current close path can't stop the reader.** It only looks at `connection.sock`, and the reader thread was still alive afterwards.
- **Shutting down a saved socket works.** It woke the reader at once: `read1` returned `b''`, and `parser.final()` will then return None.
- **Shutting down after the response is fully closed is safe.** Once the socket is really closed, `fileno()` is -1 and `shutdown` raises `OSError`. The existing `except OSError` already catches that, and there is no way for it to hit a reused file descriptor at the Python level.

The proposed fix is the smallest one that removes the root cause. Nothing else in `factory/` or `tests/` uses `Allowance.connections` (only `model_call_gate.py:148,227,537,563`), so changing it from a set to a map is self-contained. Not reading private response fields and not changing timeouts are the right choices.

## Findings

**1. Major: the row's closure scope leaves out TLS.** (Affects the Murphy row `new-router-item8-prereqs-1`, its `Closed by` text, and the amendment's last paragraph.)
- Production calls go through `HTTPSConnection`, so the saved socket is an `SSLSocket`. Its `shutdown` sets `_sslobj = None` and then shuts down the descriptor.
- A reader already blocked inside `_sslobj.read` will most likely get an EOF that is quietly swallowed and return `b''`. A later read raises `ValueError`, which `do_POST` already catches. So the fix probably works over TLS.
- But the fixture swaps `HTTPSConnection` for plain `HTTPConnection` (`test_model_call_maxima.py:561-564`), so nothing proves it.
- The risks section already says "not … TLS … acceptance", but the row would close with no such caveat.
- **Fix, either one:**
  - add "plain-HTTP loopback; TLS socket wake unproved" to `Closed by`, and leave the TLS part to rows 9/39 or a follow-up row; or
  - add a TLS loopback variant, if a test certificate is allowed under the real-artifacts rule.

**2. Major: the negative-control evidence has no recorded home.** (Affects the amendment's "Add a negative-control check".)
- Removing the saved-socket shutdown is a temporary mutation that never gets committed. The diff goldfish therefore can't check it unless its output is written down somewhere.
- **Fix:** state that the unfixed red result goes into the suite `.md` record or the review file. That is the existing HTTP/1.0 failure plus the mutation run on the `Connection: close` variant, with command, exit status and the failing assertion.
- The diff reviewer should not accept the row closure without that record.

**3. Nit: say that the closed check and the socket recording happen under one lock.** (Affects the amendment's "record connection.sock … after connect and the closed check".)
- I traced both orderings and both are safe. If close lands between the check and the recording, its `connection.close()` empties `sock`, and with `auto_open=0` the `request()` call raises `NotConnected`, so nothing is sent.
- Still, the existing `if closed: return` lock block at `model_call_gate.py:539-540` is the natural place to record the socket. Saying so removes a choice from the implementer.

**4. Nit: the production consequence is understated.** (Affects the amendment's first paragraph.)
- The runtime isn't blocked, because `Gate.close` joins only the serve loop. The real harm is different: after the receipt is sealed, the gate can keep relaying model output to the still-connected client, and the upstream keeps generating. That lasts up to `gate.remaining()`, plus one leaked thread and socket per cancelled call.
- The hold is already kept at the worst-case amount, so accounting stays correct. One sentence saying this would justify the "High" rating.

**5. Nit: the test is sound but has a residual race.** This is not new and does not block.
- The variants are good:
  - HTTP/1.1 keep-alive already passes today, so it guards the old path.
  - `Connection: close` and HTTP/1.0 cover both ways a response can detach the socket.
  - The 5 s bound against 30 s timeouts means a pass can't come from a normal timeout.
  - The assertions cover the client seeing only the prefix, an unchanged snapshot and receipt after release, a closed gate refusing `reserve`, reconcile being byte-identical twice, and one interrupted-call record.
- Each variant needs its own temp directory, store and events. The design implies this but doesn't say it.
- The residual race: CPython can, in a very narrow window, close a socket in one thread while `shutdown` runs in another and the descriptor number gets reused. That exists today too. Its practical effect is negligible, and it is not worth guarding.

## Checks against the standards

- **Heilmeier:** objective, current state, approach, impact, risks, cost (no spend), timeline and exams are all answered. The amendment is appended rather than merged in, and "Modify only tests/…" is patched with a forward reference. That is readable but awkward.
- **Zero-decision rule:** met. Files, data structure, lock discipline, variants, assertions and the closure condition are all specified, apart from Nit 3 and Major 2.
- **Murphy:** the row was registered before the fix, and closure is conditional on the reviewer accepting it. With Major 1 applied, the claim matches the evidence. Rows 9, 39 and all item-8 rows correctly stay open.

## Implementation response

Accepted both majors: closure is explicitly plain-HTTP loopback only, with TLS
socket wake still unproved; the suite record contains red and negative-control
commands/results. Applied nits 3–5: atomic closed-check/socket registration,
explicit lingering-relay consequence, and isolated variant state. No findings
rejected. Fresh diff review will verify the implementation and evidence.
