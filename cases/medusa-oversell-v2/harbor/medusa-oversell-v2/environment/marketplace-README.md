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

## Guard interface

Supply `services.patch`, a unified Git patch relative to service names, such as `a/marketplace/service.py`. It applies to an isolated service copy. The service Dockerfile, Compose configuration and reset/monitor adapter are infrastructure and cannot be patched. You may combine it with the Medusa database and application guard files described in `/app/CONTESTANT.md`.

`bin/reset --guard /app/guard` retains this service and already-announced changes. Pending decisions are applied in the separate checkpoint bench.
