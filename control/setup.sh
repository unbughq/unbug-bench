#!/bin/sh
# Run by bin/control-vm over root SSH. Never enable shell tracing here.
set -eu
umask 077
repo=/home/user/unbug-bench
state=/home/user/.unbug-control
case ${1:?bootstrap|key-and-units|activate} in
  bootstrap)
    # Refuse a source refresh underneath a running controller/holder.
    for unit in unbug-key-holder.service unbug-resume-launches.service unbug-resume-launches.timer; do
      if systemctl is-active --quiet "$unit"; then
        echo "Stop $unit deliberately before refreshing control source" >&2; exit 1
      fi
    done
    cloud-init status --wait >/dev/null
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -q >&2
    # boat-call uses zsh -ic when its caller does not preserve BOAT_CMD.
    apt-get install -yq python3 age rsync curl zsh ca-certificates unattended-upgrades >&2
    install -d -m 755 /etc/needrestart/conf.d
    cat > /etc/needrestart/conf.d/unbug.conf <<'EOF'
# 2026-10-24: unattended upgrades must not restart the key holder under a live controller.
$nrconf{override_rc}{qr(^unbug-)} = 0;
EOF
    id user >/dev/null 2>&1 || useradd -m -s /bin/bash user
    usermod -L user
    install -d -m 700 -o user -g user /home/user/.ssh "$repo" "$state" "$state/launches"
    install -m 600 -o user -g user /root/.ssh/authorized_keys /home/user/.ssh/authorized_keys
    # Use the official installer's binary/config contract without running its shell-profile
    # edits, self-update or interactive onboarding. The prod download endpoint serves the
    # latest CLI (1.0.88 on 2026-11-02), so install the exact asset bin/boat-call pins.
    # Pinned upstream x64 asset; other architectures need separate verification.
    case $(uname -m) in
      x86_64) arch=x64; boat_sha256=5d7933a238dcea0446bbbee0e2506692961d16537b9960003e4ece9ecb1ec498 ;;
      *) echo 'Unsupported Boat CLI architecture' >&2; exit 1 ;;
    esac
    install -d -m 700 -o user -g user /home/user/.config
    install -d -m 700 -o user -g user /home/user/.ascii/bin /home/user/.config/ascii/boat /home/user/.config/unbug-bench
    boat=/home/user/.ascii/bin/boat
    curl -fsSL "https://github.com/ariana-dot-dev/agent-server/releases/download/boat-cli-v1.0.85/boat-linux-$arch" -o "$boat.download"
    if [ "$(sha256sum "$boat.download" | cut -d ' ' -f 1)" != "$boat_sha256" ]; then
      rm -f "$boat.download"; echo 'Boat CLI SHA-256 mismatch; not installed' >&2; exit 1
    fi
    mv "$boat.download" "$boat"
    chmod 755 "$boat"
    chown user:user "$boat"
    config=/home/user/.config/ascii/boat/config.json
    # On Linux boat login stores its token in this file; a rerun must not erase it.
    [ -s "$config" ] || printf '%s\n' '{"api_url":"https://boat.dev","channel":"prod"}' > "$config"
    chmod 600 "$config"
    chown user:user "$config"
    ln -sfn "$boat" /usr/local/bin/boat
    version=$(BOAT_NO_UPDATE=1 runuser -u user -- /usr/local/bin/boat --version)
    printf 'Installed Boat CLI: %s\n' "$version" >&2
    # The first setting wins in sshd: load before Ubuntu/cloud-init's drop-ins.
    cat > /etc/ssh/sshd_config.d/00-unbug-control.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthenticationMethods publickey
PermitRootLogin prohibit-password
EOF
    sshd -t
    systemctl reload ssh
    cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
    systemctl enable --now unattended-upgrades >&2
    ;;
  key-and-units)
    # Generate as the non-root account, on the VM only. No stdout/stderr private key.
    runuser -u user -- sh -c '
      set -eu; umask 077
      key=$HOME/.unbug-control/control.key
      [ ! -L "$key" ] || exit 1
      if [ ! -e "$key" ]; then age-keygen -o "$key" >/dev/null 2>/dev/null; fi
      chmod 600 "$key"
      age-keygen -y "$key"
    '
    install -m 644 "$repo/control/unbug-key-holder.service" /etc/systemd/system/
    install -m 644 "$repo/control/unbug-resume-launches.service" /etc/systemd/system/
    install -m 644 "$repo/control/unbug-resume-launches.timer" /etc/systemd/system/
    systemctl daemon-reload
    ;;
  activate)
    # The controller uses its own revocable Boat API key, installed by boat-login.
    BOAT_NO_UPDATE=1 runuser -u user -- /usr/local/bin/boat list --json >/dev/null 2>&1 || {
      echo 'Boat authentication failed; run bin/control-vm boat-login before activation' >&2; exit 1
    }
    runuser -u user -- sh "$repo/control/holder-command.sh" check
    # Founder-reviewed VM policy and encrypted dual-recipient bundle are separate
    # handoff steps; setup intentionally never transfers either of them.
    [ -f "$state/policy.json" ] && [ -f /home/user/.config/unbug-bench/secrets.age ] || {
      echo 'Install reviewed VM policy and dual-recipient encrypted bundle before activation' >&2; exit 1
    }
    # These public helpers are required by the pinned launcher/holder sources.
    [ -f "$repo/factory/recovery.py" ] || {
      echo 'Missing public factory/recovery.py; refresh control source before activation' >&2; exit 1
    }
    [ -f "$repo/bin/push-secrets" ] || {
      echo 'Missing public bin/push-secrets; refresh control source before activation' >&2; exit 1
    }
    systemctl enable unbug-key-holder.service unbug-resume-launches.timer >&2
    systemctl start unbug-key-holder.service
    # resume is a oneshot client; wait for holder readiness rather than racing its socket.
    systemctl start unbug-resume-launches.service
    systemctl start unbug-resume-launches.timer
    ;;
  *) exit 2 ;;
esac
