> ## Documentation Index
> Fetch the complete documentation index at: https://docs.boat.dev/llms.txt
> Use this file to discover all available pages before exploring further.

# Stop a sandbox

> What a stop does, how to wait for it in a script, how to save app state first, and what happens when a stop is refused.

A stop saves the disk, then removes the machine. A stopped sandbox costs nothing. Run `boat resume` to get it back.

```bash theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat stop bx_f7k2q9hd
```

> [!WARNING]
>
> **boat keeps the disk of a stopped sandbox for 14 days.** Then it deletes the data. The sandbox stays in your list, but it cannot resume or fork. To keep it longer, save a saved snapshot before day 14. Read [Keep a stopped sandbox longer than 14 days](#keep-a-stopped-sandbox-longer-than-14-days).

* There is no pause. A stop removes the virtual machine and keeps a copy of the disk. A resume starts a new machine with that disk.
* A stop keeps the disk. It does not keep memory or running programs.
* Every stop saves the disk first: `boat stop`, [auto-stop](https://docs.boat.dev/long-running-tasks/auto-stop.md) and a stop for an empty wallet. Only `boat stop --force` and [snapshots off](https://docs.boat.dev/data-retention/snapshots-and-monitoring-off.md#snapshots-off) skip the save.
* To erase the sandbox for good, delete it. Read [Delete a sandbox](https://docs.boat.dev/data-retention/delete.md).

## State names

The CLI and the dashboard show one set of names. The API and webhooks show another.

| CLI and dashboard | API and webhooks | Meaning |
| - | - | - |
| `stopping` | `archiving` | boat saves the disk and removes the machine |
| `stopped` | `archived` | The disk is saved. The sandbox costs nothing |

The API reports a stopped sandbox as `archived`. The webhook event for a stop is `sandbox.archived`. The field `archiveAfter` is the auto-stop time. These are names only. A stopped sandbox is not moved or deleted.

## Keep a stopped sandbox longer than 14 days

| Day after the stop | What happens |
| - | - |
| 0 to 14 | The disk is kept for free. `boat resume` and `boat fork` work. |
| 11 | boat sends you an email. It lists the sandboxes and the date of the deletion. |
| 14 | boat deletes the data. Resume and fork fail with `409 snapshot_data_expired`. |

* A resume starts the 14 days again from the next stop.
* A [saved snapshot](https://docs.boat.dev/snapshots/templates.md) never expires. You can save one from a stopped sandbox until day 14.
* Your plan includes 10 or more saved snapshots. Each one after that costs \$0.056 a day from the wallet. Delete it to stop the charge.

To keep the disk of a sandbox that stays stopped a long time, save a saved snapshot before day 14. Then start from the saved snapshot instead of the sandbox:

```bash theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat snapshot bx_f7k2q9hd customer-42     # works on a stopped sandbox
boat new --from customer-42               # later: a new sandbox with that disk
boat snapshot rm customer-42              # when you no longer need it
```

To pay the least, save the saved snapshot only for sandboxes that are still stopped on day 13. Sandboxes that resume earlier need no saved snapshot. Record the stop time in your app when you call `boat stop`, and run the save from a daily job.

## Wait for the stop in a script

`boat stop` returns when the stop starts, with state `stopping`. It does not wait for `stopped`.

To wait, poll `boat info` until the state is `stopped`:

```bash theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat stop "$ID"
until [ "$(boat info "$ID" --json | jq -r .sandbox.state)" = "stopped" ]; do sleep 2; done
```

With the API, poll `GET /sandboxes/{sandboxId}` until `sandbox.state` is `archived`.

You do not need to wait before a plain `boat resume`. A resume during `stopping` takes back the same machine, with no restore.

boat also keeps the machine for 10 minutes after the sandbox reads `stopped`. A plain `boat resume` in those 10 minutes takes back the same machine, with no restore. These 10 minutes are not billed. After them, a resume starts a new machine from the snapshot.

Wait for `stopped` before you resume with a new `--type` or `--environment`. Such a resume always starts a new machine.

## What a stop does

boat does these steps in this order:

1. boat runs your [pre-stop command](#save-app-state-before-a-stop), if you have one.
2. boat stops your Docker containers. Each container gets 30 seconds to exit.
3. boat takes the last snapshot of the disk.
4. boat turns off the machine and removes it.

boat does not shut down the operating system. Only Docker containers get a stop signal. Your other programs get no signal.

A program that runs during the stop does not run its cleanup code. Its files go into the snapshot as they are at that moment.

To clean up, use one of these:

* Clean up when the sandbox starts again. An enabled systemd service with an `ExecStartPre=` step runs at every resume. Read [Always-on services](https://docs.boat.dev/long-running-tasks/always-on-services.md#run-an-always-on-service).
* Run your own cleanup first, then run `boat stop`.

## Save app state before a stop

Some apps keep recent changes in memory. They write them to disk later.

Chrome is an example. Chrome writes new cookies to disk every 30 seconds, or when it closes. If you stop the sandbox a few seconds after a login, the snapshot has the old cookies. A kill signal does not help, because Chrome then exits without saving.

To fix this, put a command in the file `~/.boat/pre-stop`. boat runs it at every stop, before the last snapshot.

The example below closes Chrome. It needs Chrome to have a debug port. Start Chrome with `--remote-debugging-port=9222`.

```bash theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
mkdir -p ~/.boat
cat > ~/.boat/pre-stop <<'EOF'
#!/bin/bash
# Ask Chrome to close over its debug port, so it writes its cookies.
node -e '
fetch("http://127.0.0.1:9222/json/version").then(r => r.json()).then(v => {
  const ws = new WebSocket(v.webSocketDebuggerUrl);
  ws.onopen = () => ws.send(JSON.stringify({ id: 1, method: "Browser.close" }));
  ws.onclose = () => process.exit(0);
}).catch(() => process.exit(0));'
# Then wait for it to exit.
for i in $(seq 30); do pgrep -f remote-debugging-port=9222 >/dev/null || exit 0; sleep 1; done
EOF
chmod +x ~/.boat/pre-stop
```

A Chrome that you started without the flag does not answer, so the command does not close it. A Chrome that you opened from the desktop is an example. Start it again with the flag.

How the pre-stop command runs:

* It runs as `user`, in your home folder.
* It has 60 seconds. After that, boat stops it.
* It runs on `boat stop` and on auto-stop.
* It does not run on `boat stop --force`. It does not run when you save a saved snapshot.
* If it fails or takes too long, the stop continues.
* The file is on the disk. Resumes, forks and saved snapshots keep it.

## When a stop is refused

A stop saves the disk first. If the save fails, boat refuses the stop. The sandbox keeps running, so the unsaved work stays on its disk. boat tries again by itself and sends you an email.

**You do not pay while the stop waits.** The billing meter pauses at the first refused stop. Your balance and your invoice both show the pause. You do not need to ask for a refund.

* The meter stays paused while the stop waits, even if you or your scripts use the sandbox.
* The meter starts again when the sandbox stops.
* The meter also starts again when you resume the sandbox, because a resume cancels the stop.
* If the refused stop was an auto-stop, the meter starts again when you use the sandbox again.

The stop waits until a save works. Then the sandbox stops by itself.

If this happens again and again, snapshots fail on that sandbox. The stop error shows the last snapshot error. We get an alert. Also [contact us](https://docs.boat.dev/support.md), so that we look at your sandbox.

> [!WARNING]
>
> The boat agent in the sandbox uploads snapshots to `boat.dev` and to snapshot storage. If you block outbound traffic in the sandbox, let the agent service `ascii-agent.service` out, or every save fails and every stop is refused. An nftables `socket cgroupv2` rule stops to match when the agent restarts, for example on a boat update. Load that rule again each time `ascii-agent.service` starts.

To stop the sandbox now, run `boat stop --force`. In the API, send `{"force": true}` in the body. The reply has `"forced": true` when boat reads the force. The sandbox stops with its last good snapshot. **You lose everything written after that snapshot.**

After 3 days of failed saves, boat does a forced stop by itself. You then lose everything written after the last good snapshot. boat sends you an email one day before it does this.

## Why a sandbox stops by itself

Auto-stop is the most common cause. For every cause and how to check it, read [Why did my sandbox stop?](https://docs.boat.dev/troubleshooting.md#why-did-my-sandbox-stop).

## Stop without saving

To never save a sandbox, turn [snapshots off](https://docs.boat.dev/data-retention/snapshots-and-monitoring-off.md#snapshots-off) for your account or for one sandbox. boat then never saves it, and a stop erases it.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.