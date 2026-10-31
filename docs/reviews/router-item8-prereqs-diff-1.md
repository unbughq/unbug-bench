# Diff review: router-item8-prereqs, commit f06f7e5 against base f829df7

**Mode:** REVIEW. I read both personas (`zoom_out`, `implementation_readiness`) first, then `docs/ENGINEERING.md` and `implementation-readiness-standard.md`.
**Inputs:** the design `docs/designs/router-item8-prereqs.md`, including the founder subscription section and the saved-socket amendment; the actual diff; `factory/model_call_gate.py` (`Allowance`, `Handler.do_POST`, `Gate.close`); the test file's `ProtocolTests` setUp and new test; design reviews 1 to 3; the suite record, the suite log, and the negative-control script and log.

## Verdict: PASS. 0 blockers, 0 majors, 6 nits.

The production change is small and matches the amendment. The regression exercises the real defect: the real gate, the real runtime receipt writer, and real accounting, over a real loopback socket. I re-ran two things offline. The focused module passed: 22 tests in 4.813s, OK. The negative control failed as expected: 1 test in 5.400s, FAILED, at `test_model_call_maxima.py:711`, which is the `handler_done` assertion. Neither run left any changes in the worktree. Closing the Murphy row with the stated narrow scope is justified.

## What I checked

**Scope matches the design.** The only production change is in `factory/model_call_gate.py`: 10 lines added, 6 removed. The test change is confined to `ProtocolTests`, with an optional `stalled` fixture that defaults to `None`. With that default, the existing tests get the same upstream behaviour as before, because the Connection header and the stall are added only when `stalled` is set. Nothing is added as a second runtime, admission or accounting path, and no timeouts changed.

**Races in the production change.** Every interleaving I traced is safe:
- **Close before the connection is registered:** the handler sees `closed` and returns before connecting.
- **Close while the entry is still `None` (during `connect()`):** close calls `connection.close()`. The handler's second lock block then sees `closed` and returns before `request()`, and `finally` closes the connection again. The `auto_open=0` setting is unchanged, so it cannot reconnect.
- **Close after the socket is saved:** close shuts down the saved socket even if `getresponse()` has detached it from the connection, which is the defect. The `read1` blocked on that socket wakes up, and the handler goes through `finally`. Its `finish()` finds the identity already moved to `retained`, so nothing is refunded.
- **Close after the handler's own `finally`:** the entry has been popped, so close never sees it. Even if close copied the entry just before the pop, shutting down an already-closed Python socket raises an `OSError` (bad file descriptor) on fd -1. That error is caught, and descriptor reuse cannot hit an unrelated socket.
- **Locking:** the lock covers only map changes and the copy; no I/O or `shutdown` happens under it, as the design requires. No private response fields are inspected.

**The regression proves the defect, not a timeout.**
- **Before release:** the handler finishes and the client reaches EOF with only the prefix, within 5 seconds of the cancellation being raised. The client and gate timeouts are 30 seconds and the downstream timeout is `min(15, remaining)`, so the 5-second bound cannot pass by a normal timeout expiring.
- **Receipt, cap and ledger:** all match the design exactly:
  - receipt: `interrupted` with `final_usage_known` False;
  - cap: forwarded/validated/unknown/in_flight = 1/0/1/0, settled 0, held 8.655360, closed, not exhausted;
  - ledger: maximum 50.000000000, state `estimated`, gap 8.655360000, total equal to the gap, no events.
- **After release:** the snapshot and receipt bytes are unchanged, `reserve` is refused, and two reconcile calls leave the ledger byte-identical.
- **Router:** no live lease, and exactly one interrupted-call record carrying the same lease and call ID.
- **Variants:** HTTP/1.1 keep-alive, HTTP/1.1 with `Connection: close`, and HTTP/1.0 each get a fresh temp directory, Store and events, as the amendment requires.
- **Cleanup:** `finally` releases the upstream, closes the gate and joins the pool, so a failure cannot hang the suite.

**The negative control is valid.** It changes `Allowance.close` in memory so shutdown looks at `connection.sock` again. It first checks that the exact source line being replaced exists, so it cannot silently become a no-op. It then fails on the `Connection: close` variant at the `handler_done` assertion, before the upstream is released. Because the change is in memory, no source file was ever mutated. That satisfies "temporary mutation restored" more strongly than editing and reverting a file. The original HTTP/1.0 red is recorded with its command, exit status and assertion.

**Full suite evidence.** The log ends `158 test scripts run; 0 failed.`, and its SHA-256 matches the record (`9349ce79…bf89`). The maxima module shows 22 tests in 4.602s. I did not repeat the full suite.

**Murphy row `new-router-item8-prereqs-1`.** The row was added as `new-…`, which follows the branch numbering rule. It disclaims any live-provider incident, and `Closed by` names the test and says "plain-HTTP loopback only; TLS socket wake unproved." No item-8 row and no rows 9 or 39 are touched.
- **Real-artifacts rule:** the defect is in how the standard library handles sockets and the gate's shutdown lookup. So the real loopback socket, real gate, real runtime receipt writer and real accounting are the relevant artifacts. The synthetic payload and process boundary are labelled synthetic in the test, the record and the row.

**Founder constraints.** The design records the USD 100 qualification approval, the subscription-first preference, existing OpenRouter credit only, and the MiniMax/DeepSeek family-binding limits. It uses none of that allowance, and the record states USD 0 spend, nothing pushed and nothing merged. That is consistent.

**Merge readiness.** `factory-simplify` has moved on to 56b4c13. `git merge-tree factory-simplify f06f7e5` is clean, and the branch's later commits do not touch the gate, the maxima test or the register row.

## Nits (optional)

1. **TLS is still unproved, and the reason is specific.** `SSLSocket.shutdown` sets `_sslobj=None`. A concurrent `read1` would then most likely raise `ValueError`, which `do_POST` already catches, so it will probably work. But that has not been exercised, and the row's scope statement is correctly limited. A future TLS loopback variant, using a self-signed context on the existing fixture, would close that gap.
2. **The handler never closes the `HTTPResponse` explicitly** (`model_call_gate.py:560-568`). For connection-close responses, the underlying file descriptor stays alive until garbage collection releases the response. This was true before the change and is now harmless, because shutdown has woken the reader. An explicit `response.close()` in `finally` would release it at once. This is not part of this change's scope.
3. **The negative control only covers `Connection: close`.** The HTTP/1.0 red comes from the pre-fix run and an isolated comparison that the record describes, not from a retained raw log. That is enough, because both go through the same `will_close` path.
4. **The negative-control script depends on an exact source line.** It guards that with an assert, so the failure would be loud if the line changed, which is acceptable. Note that it lives in `docs/reports/`, not in the suite, so nothing will re-run it automatically.
5. **The design's "Change and exact test" section still says "Modify only tests/…"** and only the next sentence mentions the amendment's production file. Folding the two into one clear scope statement would read better for a fresh reader.
6. **Check the design's founder section at merge.** It repeats the scenario role map from stream-d (scenarios 1 to 7), and `factory-simplify` has since merged "item 8 plan uses sequential throwaway workers". When merging, check that the repeated mapping still matches stream-d.md, or point to it instead of copying it.

## Blockers

None.

## Murphy closure

I accept the closure of `new-router-item8-prereqs-1`, with exactly the scope written: plain-HTTP loopback; TLS socket wake, CLI process tree, selected routes, live workers and providers remain unproved. No broader cancellation or item-8 acceptance is implied.

## Implementation response

PASS accepted. No blocking findings or rejections. Optional nits remain scoped
follow-ups: TLS qualification and explicit response close need separate evidence;
the negative control is a retained manual experiment, not an automatic suite test.
The reviewed design records its original test-only scope and amendment. Recheck
the scenario-role mapping against the destination at any future authorized merge.
No merge, rebase or push performed; this branch retains its requested starting HEAD.
This record-only commit does not change tested production or test code.
