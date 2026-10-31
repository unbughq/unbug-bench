> ## Documentation Index
> Fetch the complete documentation index at: https://docs.boat.dev/llms.txt
> Use this file to discover all available pages before exploring further.

# Auto-stop and keep alive

> Keep a sandbox alive: turn off auto-stop, read the auto-stop deadline, and extend a sandbox. A running agent prompt moves the deadline.

## Keep a sandbox alive

Every sandbox has an auto-stop timer.

* The default is 1 hour. The maximum is 30 days, or no auto-stop at all.
* The timer counts from creation or from the last resume, not from your last activity.
* A sandbox with a 1 hour TTL stops one hour after it starts, even in the middle of your own commands.
* **A running agent prompt is the exception.** When the deadline comes while a prompt runs or waits, boat moves the deadline to one TTL later. It does this again until no prompt is active.

| You want | Command |
| - | - |
| No auto-stop | `boat extend <id> --no-auto-stop` |
| Stop 12 hours from now | `boat extend <id> --hours 12` |
| See the deadline | `boat info <id>` |

> [!NOTE]
>
> On the free trial, you cannot turn off auto-stop, and the TTL cannot be more than 2 hours. boat refuses the call with `trial_auto_stop_required`. Read [Free trial](https://docs.boat.dev/free-trial.md).

## Turn off auto-stop

Use this when the sandbox must run until you stop it yourself. Examples are demos, browser sessions, long setup jobs and unattended workflows. A stop interrupts this work, and you must then start the processes again.

Turn off auto-stop when you create the sandbox. For a sandbox that exists, set its TTL to `null`.

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat new --no-auto-stop
boat extend bx_f7k2q9hd --no-auto-stop
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS -X POST "$BOAT_API_BASE/sandboxes" \
  -H "Authorization: Bearer $BOAT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ttlSeconds":null}'

curl -sS -X PATCH "$BOAT_API_BASE/sandboxes/bx_f7k2q9hd" \
  -H "Authorization: Bearer $BOAT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ttlSeconds":null}'
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
const created = await sandbox.create({ ttlSeconds: null });

await sandbox.update({
  sandboxId: "bx_f7k2q9hd",
  ttlSeconds: null,
});
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
created = sandbox.create(create_sandbox_request=CreateSandboxRequest(ttl_seconds=None))

sandbox.update("bx_f7k2q9hd", UpdateSandboxRequest(ttl_seconds=None))
```

You can also select **No auto-stop** in the dashboard.

### TTL on resume and fork

`resume` and `fork` also accept `ttlSeconds`. Thus a sandbox that comes back does not need a second call to set its lifetime.

| Call | When you do not give `ttlSeconds` |
| - | - |
| Resume | The sandbox keeps its current setting. |
| Fork | The new sandbox gets 1 hour. It does not copy the setting of the source sandbox. |

Thus a fork of a sandbox with auto-stop off does not silently make a second sandbox that never stops. See [Snapshots](https://docs.boat.dev/snapshots.md).

## Read the auto-stop deadline

Each resume sets the deadline again. The new deadline is the resume time plus the TTL of the sandbox.

If you schedule long jobs, do these steps:

1. Read the deadline after each resume.
2. Before a job that runs past the deadline, extend the sandbox.

`archiveAfter` is the deadline. It is `null` when auto-stop is off. `ttlSeconds` is the TTL as you last set it.

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat info bx_f7k2q9hd          # shows the deadline and the time left
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS "$BOAT_API_BASE/sandboxes/bx_f7k2q9hd" \
  -H "Authorization: Bearer $BOAT_API_KEY" | jq -r .sandbox.archiveAfter
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
const info = await sandbox.get({ sandboxId: "bx_f7k2q9hd" });
console.log(info.sandbox.archiveAfter);
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
info = sandbox.get("bx_f7k2q9hd")
print(info.sandbox.archive_after)
```

At the deadline, the sandbox stops the same as with `boat stop`. The stop starts within about 5 seconds of the deadline. boat cuts off the jobs that run. See [what a stop does to running work](https://docs.boat.dev/snapshots/stop.md#what-a-stop-does).

There is one exception. While a prompt to the agent of the sandbox runs, boat moves the deadline forward by one TTL. Your own jobs do not move the deadline. Examples are `boat exec` commands and services. Read `archiveAfter` again each time. Do not keep the first value.

The API reports a stopped sandbox as `archived`.

## Extend with a deadline

`boat extend` sets a new TTL. The new deadline is **now plus the TTL**, not the start time plus the TTL. The sandbox also keeps this TTL for later resumes.

* `boat extend <id> --hours 12`: the sandbox stops 12 hours from now.
* `--hours` and `--ttl` set the remaining time. They do not add to it.
* `PATCH /sandboxes/{id}` with `ttlSeconds` does the same.

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat extend bx_f7k2q9hd --hours 12
boat info bx_f7k2q9hd          # archiveAfter is now 12 hours from now
boat extend bx_f7k2q9hd --ttl 2592000
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS -X PATCH "$BOAT_API_BASE/sandboxes/bx_f7k2q9hd" \
  -H "Authorization: Bearer $BOAT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ttlSeconds":43200}'
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
await sandbox.update({
  sandboxId: "bx_f7k2q9hd",
  ttlSeconds: 12 * 60 * 60,
});
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
sandbox.update("bx_f7k2q9hd", UpdateSandboxRequest(ttl_seconds=12 * 60 * 60))
```

* `2592000` seconds is 30 days.
* 30 days is the maximum numeric TTL that the boat API accepts.
* boat caps larger values to 30 days.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.