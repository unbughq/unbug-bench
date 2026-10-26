# Task

You are an engineer asked to protect a business promise in a running application.

- `promise.md`: the promise, as approved by the business.
- `contestant.md`: how the app runs, the guard interface and its limits.
- `app/`: the application source.
- `services/<name>/`: contestant-visible secondary-service source and API documentation,
  when the promise includes another service.
- `DELIVERY.md`: workspace paths, effective endpoint mapping, supported local testing and installation order.
  Source and service README bytes are preserved for patches; apply its port/path mapping when using their examples.
- The app is running: store and admin APIs at `http://127.0.0.1:9000` and
  `http://127.0.0.1:9001`.

Make the promise hold on every path that can break it, without refusing legitimate business.
Deliver your protection only through the guard interface allowed by `contestant.md`:
write `guard/db.sql`, `guard/app.patch` (patch paths relative to `app/`), and/or
`guard/services.patch` (patch paths start with the service name, e.g. `a/channel/service.py`).
A service-only fix is a submission when that interface is allowed. Do not change anything else. You have the
session's time budget; stop when you are confident or out of ideas.
