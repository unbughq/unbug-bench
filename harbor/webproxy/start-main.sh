#!/bin/sh
set -eu
i=0
until test -s /webproxy-ca/mitmproxy-ca-cert.crt; do
  i=$((i + 1)); test "$i" -lt 60 || exit 1
  sleep 1
done
cp /webproxy-ca/mitmproxy-ca-cert.crt /usr/local/share/ca-certificates/unbug-webproxy.crt
update-ca-certificates >/dev/null
# Docker's nested clients need both proxy build arguments and the same public CA.
# Resolve here: the outer Compose service name is not a nested Docker DNS name.
proxy_ip=$(getent ahostsv4 webproxy | awk 'NR == 1 { print $1; exit }')
test -n "$proxy_ip"
export HTTP_PROXY="http://$proxy_ip:8080" HTTPS_PROXY="http://$proxy_ip:8080"
export http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY"
export NO_PROXY="localhost,127.0.0.1,::1,postgres,redis,medusa,medusa-b,responder,keyswap"
export no_proxy="$NO_PROXY"
export UNBUG_PROXY_CA=$(base64 -w 0 /webproxy-ca/mitmproxy-ca-cert.crt)
mkdir -p "$HOME/.docker"
python3 - <<'PY'
import json, os
from pathlib import Path
path = Path.home() / '.docker/config.json'
config = json.loads(path.read_text()) if path.exists() else {}
config.setdefault('proxies', {})['default'] = {
    'httpProxy': os.environ['HTTP_PROXY'], 'httpsProxy': os.environ['HTTPS_PROXY'],
    'noProxy': os.environ['NO_PROXY']}
path.write_text(json.dumps(config))
# docker exec does not inherit PID 1's later exports. Compose reads this public
# certificate argument from the contestant working directory on every rebuild.
workdir = Path('/app')
for directory in (workdir, workdir / 'projects/medusa'):
    if directory.is_dir():
        env_file = directory / '.env'
        lines = env_file.read_text().splitlines() if env_file.exists() else []
        lines = [line for line in lines if not line.startswith('UNBUG_PROXY_CA=')]
        lines.append('UNBUG_PROXY_CA=' + os.environ['UNBUG_PROXY_CA'])
        env_file.write_text('\n'.join(lines) + '\n')
PY
exec start-dockerd
