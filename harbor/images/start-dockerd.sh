#!/bin/sh
# Nested dockerd on cgroup v2 (same step as docker:dind's entrypoint): move this container's
# processes out of the root cgroup and enable its controllers for children, else runc fails
# with "cannot enter cgroupv2 ... with domain controllers -- it is in threaded mode".
if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
  mkdir -p /sys/fs/cgroup/init
  xargs -rn1 < /sys/fs/cgroup/cgroup.procs > /sys/fs/cgroup/init/cgroup.procs || :
  sed -e 's/ / +/g' -e 's/^/+/' < /sys/fs/cgroup/cgroup.controllers > /sys/fs/cgroup/cgroup.subtree_control
fi
dockerd >/var/log/dockerd.log 2>&1 &
exec sleep infinity
