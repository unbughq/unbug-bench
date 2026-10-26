# Marketplace channel (public practice service)

A small marketplace integration accepts sales of the same S kit stocked in Medusa.
Its own SQLite database stores confirmed orders and its local catalog caches 10 units.
This is the same physical stock, not another delivery of 10. Medusa reservations used
by an integration are holds for marketplace orders, not extra customer orders.

The application code (`service.py`, Dockerfile and Compose overlay) is contestant-visible.
No Python packages are installed; the Python 3.12 image is pinned by digest. The channel
uses 64 MiB, bringing the reference stack to 3,520 MiB. Only localhost port 9010 is exposed.

- `POST http://127.0.0.1:9010/orders` with `{"kit":"s","quantity":2}` returns a confirmed
  order and its physical units, or HTTP 409 if stock is unavailable.
- `GET /monitor` uses HTTP Basic login **arm_monitor / arm_monitor** and returns orders
  and cached stock. It opens SQLite with `mode=ro`; this login has no mutation endpoint.
- `GET /health` is unauthenticated. The local sales endpoint is a disposable practice API.
- SQLite lives at `/data/marketplace.sqlite` on a container tmpfs. Reset discards it.
- `MEDUSA_URL` defaults to `http://medusa:9000`; `medusa()` uses the local seeded admin
  login to call the integration API. A failed/ambiguous hold must not confirm an order.

For practice, from the bench root:

```sh
bin/reset --scenario scenarios/dev/S13-marketplace
bin/checkpoint --scenario scenarios/dev/S13-marketplace --guard none --runs 1
bin/checkpoint --scenario scenarios/dev/S13-marketplace --guard "$PWD/scenarios/dev/S13-marketplace/examples/tables-only" --runs 1
bin/checkpoint --scenario scenarios/dev/S13-marketplace --guard "$PWD/scenarios/dev/S13-marketplace/examples/cross-service" --runs 3
curl -u arm_monitor:arm_monitor http://127.0.0.1:9010/monitor
```

The guard interface adds `services.patch`, a Git patch whose paths are relative to the
service names (e.g. `a/marketplace/service.py`). It applies to isolated copies, after
scenario code is selected. Supply `db.sql` and/or `app.patch` as usual for Medusa.
`adapter.py`, `Dockerfile` and `compose.yaml` are bench-owned and cannot be changed by this patch.

Bench-only `adapter.py` resets and reads the actual SQLite ledger independently of the
service HTTP view, by copying the quiescent ledger and opening it read-only with host SQLite, independently
of the runtime interpreter. The reference container is non-root with a read-only root filesystem. Do not distribute
that file, scenario hooks, keys or example guards to contestants. The Docker image copies
only `service.py`. The reference guard acquires a Medusa reservation before recording a
local confirmation; its database guard serializes those holds with Medusa sales.

Scope: one kit, integer physical units, no fulfillment or cancellation API. An interrupted
hold can temporarily waste availability; production retries/cancellation reconciliation
are outside this small practice channel. None of its orders are mirrored as Medusa orders.
