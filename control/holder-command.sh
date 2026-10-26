#!/bin/sh
# Package 2 interface template: adjust ONLY the commands below if its CLI differs.
# launch --resume-launches asks the holder to resume its reserved orphan launches
# with its in-memory identity on child stdin. Never pipe/read control.key here.
set -eu
repo=/home/user/unbug-bench
holder=$repo/factory/key_holder.py
policy=$HOME/.unbug-control/policy.json
case ${1:?serve|resume|check} in
  serve)
    status=0
    /usr/bin/python3 "$holder" serve --policy "$policy" --identity-file "$HOME/.unbug-control/control.key" || status=$?
    # Package 2 currently retains the bounded Mac lifetime even for a file identity.
    # Treat a clean expiry as a failure so Restart=on-failure renews the holder and
    # the holder-bound resume unit reclaims its controllers. An explicit systemd stop
    # runs the unit's ExecStop (holder stop) and suppresses automatic restart.
    if [ "$status" -eq 0 ]; then echo 'Holder exited; requesting supervised restart' >&2; status=1; fi
    exit "$status"
    ;;
  resume)
    # Bounded socket readiness wait; persistent scan/locking belongs to package 1.
    ready=0
    for attempt in $(seq 1 60); do
      if /usr/bin/python3 "$holder" status >/dev/null 2>&1; then ready=1; break; fi
      sleep 1
    done
    [ "$ready" = 1 ] || { echo 'Holder not ready' >&2; exit 1; }
    # The holder CLI returns JSON even when a request is refused: check the payload.
    reply=$(/usr/bin/python3 "$holder" launch --resume-launches)
    printf '%s\n' "$reply" | /usr/bin/python3 -c '
import json, sys
reply = json.load(sys.stdin)
if type(reply.get("resumed")) is not int or reply["resumed"] < 0:
    sys.exit("Holder refused orphan resume")
print(json.dumps(reply))'
    ;;
  check)
    help=$(/usr/bin/python3 "$holder" --help)
    case $help in *--identity-file*--resume-launches*|*--resume-launches*--identity-file*) ;;
      *) echo 'TODO: package 2 holder serve --identity-file / launch --resume-launches interface missing; adjust control/holder-command.sh' >&2; exit 1 ;;
    esac
    ;;
  *) exit 2 ;;
esac
