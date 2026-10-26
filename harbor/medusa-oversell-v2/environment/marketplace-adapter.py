#!/usr/bin/env python3
"""Contestant reset convenience: read the service's public monitor, never the judge adapter."""
import base64, json, sys, urllib.request
assert sys.argv[1] in ("reset", "check")
request = urllib.request.Request("http://127.0.0.1:9010/monitor", headers={
    "Authorization": "Basic " + base64.b64encode(b"arm_monitor:arm_monitor").decode()})
with urllib.request.urlopen(request, timeout=10) as response:
    orders = json.load(response)["orders"]
# bench.reset recreates the tmpfs container before calling reset.
if sys.argv[1] == "reset": assert orders == {}
print(json.dumps({"orders": orders}))
