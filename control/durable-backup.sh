#!/bin/sh
# Scheduled cold snapshot: resume the source afterward; stale restores stay quarantined.
set -eu
PATH=/usr/sbin:/usr/bin:/bin
export PATH
state=/home/user/.unbug-durable
python=$state/venv/bin/python
cli=/home/user/unbug-bench/factory/durable/cli.py
config=$state/config.json
service=unbug-durable.service
# An existing fence may belong to an operator's handover. Leave it intact.
[ ! -e "$state/cold-backup.json" ] || exit 1
running=0
if systemctl is-active --quiet "$service"; then
    running=1
fi
finish() {
    status=$?
    trap - 0 HUP INT TERM
    if [ -e "$state/cold-backup.json" ]; then
        # A preexisting or crash-retained fence belongs to an operator, never us.
        exit 1
    fi
    if [ "$running" = 1 ]; then
        systemctl start "$service" || exit 1
    fi
    exit "$status"
}
trap finish 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
[ "$running" = 0 ] || systemctl stop "$service"
runuser -u user -- "$python" -B "$cli" --config "$config" backup --resume-after
