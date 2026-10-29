#!/bin/sh
# Host: factory/resume-in-place.sh SERVER_ID [run.py options]. Continues the case parked on SERVER_ID (bin/hcloud-park)
# on that same VM: uploads this factory/ tree, restarts run.py --resume with the case's source and rotation slot,
# using the keys still in the VM's memory (/dev/shm). No founder key, no new server hour. bin/factory-adopt then
# watches it (collect, then park or delete).
# Read whole before running: editing this file while a launcher runs must not change what it executes.
{
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
if [ "${1:-}" = --policy ]; then
  policy=$2; shift 2
  [ "${1:-}" = --job ] || { echo 'use --policy FILE --job NAME SERVER_ID [options]' >&2; exit 1; }
  job=$2; shift 2
  id=$1; shift
  exec python3 "$here/account_handoff.py" parked --policy "$policy" --job "$job" --worker "$id" -- "$@"
fi
id=${1:?usage: resume-in-place.sh SERVER_ID [run.py options]}; shift
export BOAT_CMD="$root/bin/hcloud-boat"
case_id=$(hcloud server describe "$id" -o json | python3 -c 'import json, sys; print((json.load(sys.stdin)["labels"] or {}).get("parked", ""))')
case $case_id in case-*) ;; *) echo "$id is not parked (no parked=case-... label)" >&2; exit 1 ;; esac
if [ "${FACTORY_PARKED_HANDOFF_READY:-}" != 1 ]; then
  stop=$("$BOAT_CMD" ssh "$id" "python3 -c 'import json; print(json.load(open(\"/home/user/sealed/$case_id.scorecard.json\")).get(\"terminal_stop\", \"\"))'")
  case $stop in provider_limit:*) echo 'provider-limited parked restore requires --policy FILE --job NAME and identity on stdin for bounded account handoff' >&2; exit 1 ;; esac
fi
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' 0
COPYFILE_DISABLE=1 tar --no-xattrs -C "$root" --exclude __pycache__ -czf "$tmp/factory.tgz" factory
"$BOAT_CMD" scp "$tmp/factory.tgz" "$id:/home/user/factory.tgz" >/dev/null
quote() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
account_state_arg=""
[ -z "${FACTORY_ACCOUNT_STATE:-}" ] || account_state_arg="--account-state $(quote "$FACTORY_ACCOUNT_STATE")"
extra=""; for a in "$@"; do extra="$extra '$(printf '%s' "$a" | sed "s/'/'\\\\''/g")'"; done
"$BOAT_CMD" ssh "$id" "set -eu
rm -rf ~/factory && tar -xzf ~/factory.tgz -C ~ && rm ~/factory.tgz
! pgrep -f '^python3 .*factory/(run|runner_supervisor)[.]py' >/dev/null || { echo 'runner already running' >&2; exit 1; }
# Source and slot from the newest scorecard that has them (a run that crashed early writes one without),
# unless given as options to this script.
case \" $extra \" in *rotation-slot*) opts= ;; *) opts=\$(python3 -c 'import json,sys
for p in sys.argv[1:]:
    try: d=json.load(open(p))
    except (OSError, ValueError): continue
    if d.get(\"dry_run\"): print(\"--dry-run\"); break
    if d.get(\"source\") and d.get(\"rotation_slot\"): print(\"--source %s --rotation-slot %s\" % (d[\"source\"], d[\"rotation_slot\"])); break
else: sys.exit(\"no scorecard names the source and slot\")' ~/sealed/$case_id.scorecard.json ~/work/$case_id/scorecard.json) ;; esac
sha=\$(cd ~/factory && python3 -c 'import run; print(run.bench_manifest())')
workers=\$(( \$(nproc) / 2 < 1 ? 1 : \$(nproc) / 2 ))
python3 ~/factory/account_handoff.py resume-worker --case $case_id --bench-sha \"\$sha\" $account_state_arg -- \$opts --bench-workers \"\$workers\" $extra
sleep 3; pgrep -f '^python3 .*factory/(run|runner_supervisor)[.]py' >/dev/null && echo \"resumed $case_id in place (\$opts, \$workers bench workers)\""
hcloud server remove-label "$id" parked >/dev/null
hcloud server add-label --overwrite "$id" "expires=$(( $(date +%s) + 8 * 3600 ))" >/dev/null
nohup "$root/bin/factory-adopt" --hours 7.5 "$id" >> "$root/results/factory/adopt.log" 2>&1 < /dev/null &
echo "watching $id with bin/factory-adopt (results/factory/adopt.log)" >&2
exit
}
