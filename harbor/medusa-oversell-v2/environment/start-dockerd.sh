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
for i in $(seq 120); do
  docker info >/dev/null 2>&1 && break
  sleep 1
done
docker info >/dev/null 2>&1 || exit 1
# OCI images only: no databases, volumes, credentials, guards or judge decisions.
timeout 300 docker load -i /opt/runtime-images.tar >/var/log/runtime-images.log 2>&1 || exit 1
# Shells launched later by Harbor inherit the pinned dependency base too.
printf 'export MEDUSA_DEPS_IMAGE=%s\n' "$(cat /opt/medusa-deps-image)" > /etc/profile.d/medusa-deps.sh
touch /tmp/runtime-images-ready
exec sleep infinity
