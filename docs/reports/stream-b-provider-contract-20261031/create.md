> ## Documentation Index
> Fetch the complete documentation index at: https://docs.boat.dev/llms.txt
> Use this file to discover all available pages before exploring further.

# Create sandbox

> Provision a new cloud computer. Store the returned `sandbox.id` with your product job/session record. Send an `Idempotency-Key` header to make this call safe to retry after a lost response without creating a second billable sandbox.



## OpenAPI

````yaml openapi/boat-v1.yaml POST /sandboxes
openapi: 3.1.0
info:
  title: Boat Public API v1
  version: 1.0.0
  description: >
    Public JSON API for creating, operating, prompting, observing, and exposing
    sandboxes from backend services, CI jobs, hosted workers, and Boat
    automation products.


    The v1 reference intentionally documents the developer integration surface
    only. Dashboard billing actions are not part of v1.
servers:
  - url: https://boat.dev/api/v1
security:
  - BoatBearerAuth: []
tags:
  - name: Boat
    description: >-
      Unified Boat account, setup, lifecycle, prompting, event history, desktop
      access, and SSH operations.
paths:
  /sandboxes:
    post:
      tags:
        - Boat
      summary: Create sandbox
      description: >-
        Provision a new cloud computer. Store the returned `sandbox.id` with
        your product job/session record. Send an `Idempotency-Key` header to
        make this call safe to retry after a lost response without creating a
        second billable sandbox.
      operationId: create
      parameters:
        - $ref: '#/components/parameters/IdempotencyKey'
        - $ref: '#/components/parameters/OrgId'
        - $ref: '#/components/parameters/OrgHeader'
      requestBody:
        required: false
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateSandboxRequest'
      responses:
        '202':
          description: Boat accepted for provisioning.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CreateSandboxResponse'
              examples:
                provisioning:
                  value:
                    ok: true
                    type: sandbox.created
                    status: provisioning
                    ttlSeconds: 3600
                    sandbox:
                      id: bx_23456789
                      name: Sandbox 2026-05-31 12:00
                      state: provisioning
                      url: null
                      ip: null
                      createdAt: '2026-05-31T12:00:00Z'
                      updatedAt: '2026-05-31T12:00:00Z'
                      archiveAfter: '2026-05-31T13:00:00Z'
                      desktopAvailable: false
                      desktopUrl: null
                      snapshotAvailable: false
                      snapshotCompletedAt: null
        '401':
          $ref: '#/components/responses/Unauthorized'
        '402':
          $ref: '#/components/responses/PaymentRequired'
        '403':
          $ref: '#/components/responses/EnvironmentForbidden'
        '409':
          $ref: '#/components/responses/Conflict'
        '429':
          $ref: '#/components/responses/RateLimited'
        '503':
          $ref: '#/components/responses/NoReadyMachine'
components:
  parameters:
    IdempotencyKey:
      name: Idempotency-Key
      in: header
      required: false
      schema:
        type: string
        maxLength: 255
      description: >-
        Optional exactly-once key for creating a sandbox. Send your own opaque,
        account-unique value (a UUID) to make `POST /sandboxes` safe to retry
        when the response is lost (network timeout, 5xx): the first request
        creates the sandbox and binds it to the key; every later request with
        the **same account, key, and request body** returns that same sandbox
        instead of creating a second, billable one. Behavior: keys are retained
        for **24 hours**; a concurrent or early retry while the first sandbox is
        still being minted returns `409` `idempotency_in_progress` (retry
        shortly, same key); reusing a key with a **different body** returns
        `409` `idempotency_key_reused`; timeouts and 5xx are safe to retry with
        the same key; a create that fails before the sandbox exists releases the
        key within ~2 minutes so a retry can create the sandbox. Omit the header
        to keep the default (non-idempotent) behavior.
    OrgId:
      name: org
      in: query
      required: false
      schema:
        type: string
      description: >-
        Billing wallet for this request: an organization you belong to, by id
        (`team_…`) or by name as `GET /orgs` lists it (case-insensitive), or
        `personal`. Omitted, the account's active wallet applies (`PATCH
        /orgs/active`; personal until set). Two organizations sharing the name
        answer `409 ambiguous_org` and need the id. Sandboxes and snapshots stay
        creator-private. On `/environments` routes, only this query parameter
        selects the organization's shared environments; the `X-Boat-Org` header
        and the active wallet do not apply there. Members read them, owners and
        admins change them.
    OrgHeader:
      name: X-Boat-Org
      in: header
      required: false
      schema:
        type: string
      description: Same as the `org` query parameter. Query wins when both are set.
  schemas:
    CreateSandboxRequest:
      type: object
      description: Options for provisioning a new cloud computer.
      properties:
        type:
          type: string
          enum:
            - small
            - default
            - large
            - xlarge
          default: default
          description: >-
            Machine size. `small` consumes machine time at half rate and `large`
            at twice the default rate (see the Billing guide). `xlarge` needs
            the $100/month plan or higher, or an account access grant from an
            administrator. Otherwise, create, resume and fork return 403
            `machine_class_plan_required`. A fork inherits the source sandbox's
            type unless the fork request passes its own, and resume and fork can
            move a sandbox between sizes.
        ttlSeconds:
          oneOf:
            - type: integer
              minimum: 1
              maximum: 2592000
            - type: 'null'
          default: 3600
          description: >-
            Number of seconds before automatic archival. `null` disables
            auto-stop. The backend also accepts the string `infinite` for legacy
            compatibility; new clients should send null.
        labels:
          type: object
          additionalProperties:
            type: string
          description: >-
            Key-value labels, for example your session id. Filter on them with
            `GET /sandboxes?label=key=value`. At most 20 labels. Keys match
            `[A-Za-z0-9][A-Za-z0-9._/-]{0,62}`; values are strings of at most
            256 bytes.
        env:
          type: object
          additionalProperties:
            type: string
          description: >-
            Per-sandbox environment variables injected into the sandbox's tool
            environment, on top of the account environment's variables
            (per-sandbox values win on conflicts). Keys must match
            `[A-Za-z_][A-Za-z0-9_]{0,127}`; at most 100 variables and 64KB
            total. Reserved names (`ASCII_TOKEN`, `ASCII_API_URL`, `AGENT_ID`,
            `PRODUCT_MODE`, `ENVIRONMENT_ID`, `BOAT_ID`,
            `SERVICE_PREVIEW_TOKEN`, `BOAT_CLI_TOKEN`) are rejected with
            `invalid_env`. Forked sandboxes inherit the source sandbox's env
            unless the fork request supplies its own `env`.
        environment:
          type: string
          default: base
          description: >-
            Name of the sandbox environment to attach to this sandbox.
            Environments are managed in the Boat dashboard and bundle the
            repositories, secrets, and credential toggles a sandbox gets. Omit
            to use your default environment (`base` unless you changed it).
            Unknown names are rejected with `unknown_environment`. An
            environment marked "safe for third parties" passes nothing to the
            sandbox, exactly like `noEnv`.
          examples:
            - base
            - customer-demos
        noEnv:
          type: boolean
          default: false
          description: >-
            Create a sandbox with none of the secrets attached to your account
            (no environment variables, secret files, or credentials), confined
            to itself so it cannot act on your account or other sandboxes. For
            sandboxes you give to your own users. SSH, SCP, desktop, snapshots,
            and public URLs still work; pass `env` to give the sandbox a secret
            of its own. A fork of a no-env sandbox is always no-env. Equivalent
            to attaching an environment marked "safe for third parties".
        snapshots:
          type: boolean
          default: true
          description: >-
            Pass `false` to never snapshot this sandbox. Nothing is captured in
            the background, so it pays no CPU or memory for it, and stopping it
            erases its disk the way zero data retention does. It cannot be
            resumed, forked, or saved as a saved snapshot, and if its machine
            fails there is no backup to rebuild it from.
        monitoring:
          type: boolean
          default: true
          description: >-
            Pass `false` for monitoring off. Boat keeps no command or process
            output, process list or CPU/RAM samples for this sandbox, and its
            history, processes and metrics calls answer 409 `monitoring_off`.
            Live output of a running command still works. While the account
            default is on, `true` is refused with 409
            `monitoring_off_for_account`.
        failFast:
          type: boolean
          default: false
          description: >-
            Pass `true` to get a sandbox only if a machine of this type is ready
            right now. The call answers within about 1.5 s: either the usual
            `202` with the sandbox, or `503` `no_ready_machine` with nothing
            created, billed, or counted against your start limits, so you can
            retry or fall back at once. Without it, a create waits for a machine
            to be built when none is ready. Works with `from`; fork and resume
            take it too.
        count:
          type: integer
          minimum: 1
          maximum: 1000
          default: 1
          description: >-
            With `from`: create this many sandboxes from the saved snapshot in
            one request. Boat creates them together, which is faster than
            separate creates when you need many sandboxes at once. Start limits
            and the active-sandbox limit count every sandbox of the batch; if
            the batch does not fit, nothing is created. The answer lists all of
            them in `sandboxes` (and the first one in `sandbox`). Refused with
            400 `count_requires_from` without `from`, and with 400
            `count_with_fail_fast` together with `failFast`.
        setupScript:
          type: string
          maxLength: 65536
          description: >-
            Shell script that runs on the sandbox after it is ready. Ready means
            "ready to accept the user", not "setup done": the script starts in
            the background once provisioning completes and never blocks the
            sandbox becoming usable. It runs as the sandbox user (`user`, not
            root; `sudo` needs no password) via `bash`, with the sandbox's
            environment applied, and its output goes to a log file on the
            sandbox. Observe the outcome as `setupStatus`
            (pending/running/done/failed) and `setupError` on the sandbox.
            Rejected with a 400 `invalid_setup_script` error when it is not a
            string or exceeds 64KB. When the request also has `files`, the
            script starts after every file is written.
        name:
          type: string
          maxLength: 120
          description: >-
            Display name of the sandbox, the same value `PATCH /sandboxes/{id}`
            sets. A sandbox created `from` a saved snapshot is named after the
            snapshot when this is omitted.
        visibility:
          type: string
          enum:
            - private
            - shared
          description: >-
            Who can use a sandbox billed to an organization, with the same rules
            as the sandbox's `visibility` field. `private`: only you can use it.
            `shared`: every member can, as long as it holds none of your
            personal logins (`noEnv`, or an environment that passes nothing).
            Omitted, the organization's default for new sandboxes applies
            (`PATCH /orgs/{org}` `newSandboxesPrivate`). It is set before the
            sandbox gets a machine, so a `private` sandbox is never shared, not
            even for a moment, and needs no `unshare` call. A personal sandbox
            is always private: `shared` is refused with 400 `not_org_sandbox`.
            Change it later with `POST /sandboxes/{id}/share` and `POST
            /sandboxes/{id}/unshare`.
        hostedPorts:
          type: array
          maxItems: 50
          description: >-
            Ports to host on public HTTPS URLs, each exactly as `POST
            /sandboxes/{id}/host` does. The create waits for the sandbox's
            machine (up to 60 s, usually under a second), hosts every port at
            once and answers the URLs in `hostedPorts`. The ports are routed
            before the sandbox is ready, so a service that starts later is
            reachable as soon as it listens. Refused with 400
            `invalid_hosted_ports` for a bad entry or a duplicate port, with 400
            `count_with_hosted_ports` together with `count`, and with 400
            `fail_fast_with_hosted_ports` together with `failFast`.
          items:
            $ref: '#/components/schemas/HostPortRequest'
        files:
          type: array
          maxItems: 32
          description: >-
            Files to write on the sandbox, each like `PUT /sandboxes/{id}/files`
            (a path under `/home/user` or `/tmp`, relative paths resolve against
            `/home/user`; missing folders are created). Boat writes them once
            the sandbox's disk is in place and before it reports `ready`, so a
            client that sees `ready`, and the `setupScript`, always find them.
            They are written once, at the first start: a resume does not write
            them again. At most 256KB in total; upload bigger files with `POST
            /sandboxes/{id}/files/upload-url`. `setupStatus` covers them: it
            stays `pending` until they are written, and a write that fails sets
            it `failed` with the path and the reason in `setupError` (the setup
            script then does not run). Refused with 400 `invalid_files` for a
            bad path, a duplicate path or a body over the limits.
          items:
            type: object
            required:
              - path
              - content
            properties:
              path:
                type: string
                examples:
                  - workspace/.env
                  - /home/user/.config/app.json
                  - /tmp/boot.txt
              content:
                type: string
                description: File contents, as text or base64 (see `encoding`).
              encoding:
                type: string
                enum:
                  - utf8
                  - base64
                default: utf8
        org:
          type: string
          description: >-
            Bill this sandbox to an organization you belong to (its shared
            wallet), by id or by name as `GET /orgs` lists it; `personal` or
            your own account id means personal billing. Omitted, the
            `X-Boat-Org` / `?org=` request scope applies, then the account's
            active wallet (`PATCH /orgs/active`), then personal. Listing,
            snapshots, and environments stay yours: the org is a wallet, not a
            shared workspace. Takes precedence over `teamId`.
        teamId:
          type: string
          description: Legacy alias for `org`. Ignored when `org` is also set.
        from:
          type: string
          description: >-
            Create the sandbox from a saved snapshot (saved with `POST
            /saved-snapshots`, or `boat snapshot <id> <name>` in the CLI). The
            sandbox starts from that exact frozen state. Omitting `type`
            inherits the type the snapshot was saved from; env and no-env
            inherit from the snapshot's source sandbox unless the request passes
            its own, with the same rules as forking. Also accepts a share code
            (`bsh_...`) that another account made with `POST
            /saved-snapshots/{name}/shares`. The new sandbox lives in and is
            billed to your account. It does not get the owner's per-sandbox env;
            your own environment applies normally. A wrong or revoked code
            returns `404 snapshot_not_found`.
      examples:
        - ttlSeconds: 3600
        - ttlSeconds: null
        - type: large
          ttlSeconds: 3600
        - ttlSeconds: 3600
          env:
            DATABASE_URL: postgres://user:pass@host:5432/app
            FEATURE_FLAG: '1'
        - ttlSeconds: null
          noEnv: true
        - from: my-template
          name: session-42
          visibility: private
          hostedPorts:
            - port: 8080
              public: true
              title: code-server
            - port: 3000
          files:
            - path: workspace/.session.env
              content: |
                SESSION_ID=42
    CreateSandboxResponse:
      allOf:
        - $ref: '#/components/schemas/SuccessBase'
        - type: object
          required:
            - status
            - ttlSeconds
            - sandbox
          properties:
            type:
              type: string
              const: sandbox.created
            status:
              type: string
              enum:
                - provisioning
                - ready
              description: >-
                `ready` only when an idempotent retry finds a sandbox that is
                already past provisioning.
            ttlSeconds:
              type:
                - integer
                - 'null'
            sandbox:
              $ref: '#/components/schemas/Sandbox'
            sandboxes:
              type: array
              items:
                $ref: '#/components/schemas/Sandbox'
              description: >-
                Present when the request set `count` above 1. Every sandbox of
                the batch, in creation order.
            hostedPorts:
              type: array
              description: >-
                Present when the request set `hostedPorts`, in request order.
                Each entry is what `POST /sandboxes/{id}/host` answers for that
                port: `url`, `access`, `isProtected` and `localhost`, or `error`
                and `message` when that one port could not be hosted (the
                sandbox is created anyway; host the port again with `POST
                /sandboxes/{id}/host`).
              items:
                type: object
                additionalProperties: true
                required:
                  - port
                properties:
                  port:
                    type: integer
                  url:
                    type: string
                    format: uri
                    description: >-
                      Public HTTPS URL. Carries the `_token` query parameter
                      unless the port is public; redact from logs.
                  isProtected:
                    type: boolean
                  access:
                    type: string
                    enum:
                      - private
                      - public
                  localhost:
                    type: boolean
                  error:
                    type: string
                  message:
                    type: string
            giftLimitNotice:
              type: string
              description: >-
                Present when a fair-use cap on a gifted account shortened the
                requested auto-stop time.
    HostPortRequest:
      type: object
      required:
        - port
      properties:
        port:
          type: integer
          minimum: 1
          maximum: 65535
          description: Port the service listens on inside the sandbox.
        public:
          type: boolean
          default: false
          description: >-
            Return an ungated URL instead of one that requires the `_token`
            query parameter.
        localhost:
          type: boolean
          default: false
          description: >-
            Set when the service listens on localhost (`127.0.0.1` or `::1`)
            only. The sandbox relays the URL to it. Leave unset for a service
            bound to `0.0.0.0`. Each call sets the value again.
        title:
          type: string
          description: Display title for the hosted port.
    SuccessBase:
      type: object
      required:
        - ok
        - type
      properties:
        ok:
          type: boolean
          examples:
            - true
        type:
          type: string
          description: Stable success envelope discriminator added by v1.
    Sandbox:
      type: object
      required:
        - id
        - name
        - state
        - desktopAvailable
        - snapshotAvailable
      properties:
        id:
          type: string
          pattern: ^bx_[23456789abcdefghjkmnpqrstuvwxyz]{8}$
          examples:
            - bx_23456789
        name:
          type: string
          examples:
            - Boat 2026-05-31 12:00
        state:
          type: string
          enum:
            - init
            - provisioning
            - provisioned
            - cloning
            - ready
            - idle
            - running
            - archiving
            - archived
            - error
            - cancelled
          description: >-
            `cancelled` is terminal: a create or fork that could not get a
            machine was removed. `GET /sandboxes/{sandboxId}` reports it once,
            with only `id`, `state` and `error`, then answers 404.
        error:
          type:
            - string
            - 'null'
          description: Why the sandbox is stopped, failed or cancelled, or null.
        dataExpiredAt:
          type:
            - string
            - 'null'
          format: date-time
          description: >-
            When Boat deleted the snapshot data of this stopped sandbox, 14 days
            after it stopped. Resume and fork then fail with `409
            snapshot_data_expired`. Null while the data is kept.
        stoppedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: >-
            When the sandbox last stopped, by any cause: your stop, its
            auto-stop, a plan limit or Boat. Null while the sandbox is not
            stopped.
        labels:
          type: object
          additionalProperties:
            type: string
          description: The labels set at create or fork. Empty when none were set.
        health:
          type: string
          enum:
            - ok
            - degraded
          description: >-
            `degraded` when the machine is alive but Boat cannot fully reach it
            (for example a firewall rule inside the sandbox blocks the tunnel).
            The sandbox keeps running.
        healthReason:
          type:
            - string
            - 'null'
          description: Why the sandbox is degraded, or null.
        degradedSince:
          type:
            - string
            - 'null'
          format: date-time
          description: When the sandbox became degraded, or null.
        hydrated:
          type: boolean
          description: >-
            True once every file of the sandbox's snapshot is on its disk. A
            resumed or forked sandbox is usable before that: its files keep
            copying in the background, and its docker volumes move onto the real
            disk near the end. Its docker containers start earlier; at that
            point their volume mounts move onto the real disk in place, without
            a restart. The `sandbox.hydrated` webhook fires at the same moment
            this turns true. A sandbox that restored nothing is hydrated from
            the start.
        hydratedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: When the last resume or fork finished copying files in, or null.
        hydration:
          description: >-
            Restore progress while `hydrated` is false, on GET /sandboxes/{id}
            only. Null in lists, after hydration, or when the sandbox does not
            answer within 1.5 s.
          oneOf:
            - type: 'null'
            - type: object
              required:
                - phase
                - entriesDone
                - entriesTotal
                - percent
              properties:
                phase:
                  type: string
                  description: >-
                    Restore step: `dvol` (docker volumes), `sysdelta` (system
                    files), `images` (saved docker images), `hydrating` (the
                    home directory), `reconciling` (the last check). `degraded`
                    and `stuck` mean a step failed and is retried.
                entriesDone:
                  type: integer
                  description: Files, directories and links copied in so far.
                entriesTotal:
                  type:
                    - integer
                    - 'null'
                  description: >-
                    Files, directories and links this restore copies in. Null
                    for the first seconds, until the system files are counted.
                percent:
                  type:
                    - integer
                    - 'null'
                  description: >-
                    entriesDone of entriesTotal, 0-99. Files you change during
                    the restore are yours, not copied, so it can stop short of
                    99; `hydrated` is the end signal.
        type:
          type: string
          enum:
            - small
            - default
            - large
            - xlarge
          description: >-
            Current machine size: what the sandbox was created with, or the size
            it was last resumed or forked onto.
        vcpu:
          type: integer
          description: vCPUs guaranteed by this sandbox's type.
          examples:
            - 4
        memoryGB:
          type: integer
          description: RAM in GB guaranteed by this sandbox's type.
          examples:
            - 8
        billingMultiplier:
          type: number
          description: >-
            Rate at which this sandbox consumes machine time. 0.5 for `small`, 1
            for `default`, 2 for `large`, and 50/9 (about 5.56) for `xlarge`.
          examples:
            - 1
        machineProvider:
          type:
            - string
            - 'null'
          enum:
            - hetzner
            - baremetal
            - null
          description: >-
            Machine provider of the machine the sandbox is on, or null when it
            has no machine.
        url:
          type:
            - string
            - 'null'
          format: uri
          description: Machine URL when assigned.
        ip:
          type:
            - string
            - 'null'
          description: Machine IPv6 or IPv4 address when assigned.
        sshEndpoint:
          type:
            - string
            - 'null'
          description: >-
            Public IPv4 `host:port` that forwards to the sandbox SSH server. Set
            only when the machine has no public IPv4 of its own; null otherwise.
            Connect with `ssh -p <port> user@<host>`.
          examples:
            - 203.0.113.10:22001
        createdAt:
          type:
            - string
            - 'null'
          format: date-time
        updatedAt:
          type:
            - string
            - 'null'
          format: date-time
        archiveAfter:
          type:
            - string
            - 'null'
          format: date-time
          description: >-
            When the sandbox stops by itself (the stop starts within about 5
            seconds), or null when auto-stop is disabled. A sandbox whose agent
            is working gets a fresh full TTL, and this time moves forward.
        ttlSeconds:
          type:
            - integer
            - 'null'
          description: >-
            The auto-stop length as last set on create, resume, fork or PATCH,
            or null when auto-stop is disabled.
        desktopAvailable:
          type: boolean
        desktopUrl:
          type:
            - string
            - 'null'
          format: uri
          description: Secret-bearing desktop stream URL when available. Redact from logs.
        snapshots:
          type: boolean
          description: False when the sandbox was created with snapshots off.
        monitoring:
          type: boolean
          description: False when the sandbox was created with monitoring off.
        snapshotAvailable:
          type: boolean
        snapshotCompletedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: >-
            Timestamp of the most recent successfully completed snapshot, or
            null.
        snapshotVerifiedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: >-
            Last time a snapshot confirmed the sandbox's saved state, including
            checks that found nothing new to save. Falls back to
            `snapshotCompletedAt`; null if never.
        team:
          type:
            - object
            - 'null'
          description: >-
            The organization billed for this sandbox, or null when the owner is
            billed.
          required:
            - id
            - name
          properties:
            id:
              type: string
            name:
              type: string
        createdBy:
          type:
            - string
            - 'null'
          description: >-
            Display name (or email) of the person who created the sandbox.
            Organization members see every sandbox the organization pays for, so
            this says whose it is.
        createdById:
          type:
            - string
            - 'null'
          description: Account id of the person who created the sandbox.
        access:
          type: string
          enum:
            - owner
            - use
            - view
          description: >-
            What you may do with this sandbox. `owner`: you created it. `use`: a
            teammate's organization sandbox that is `shared` (see `visibility`),
            so you can open, run commands in, prompt, resume and stop it.
            `view`: a teammate's organization sandbox that is `private`, so you
            can see it and stop it until they share it (`POST
            /sandboxes/{sandboxId}/share`).
        holdsCreatorLogins:
          type: boolean
          description: >-
            True while the sandbox still holds its creator's personal logins
            (GitHub token, model logins, secrets). Other members can only see
            such a sandbox.
        visibility:
          type:
            - string
            - 'null'
          enum:
            - shared
            - private
            - null
          description: >-
            Organization sandboxes only; null for a personal sandbox. `shared`:
            every member can use it. It holds none of its creator's personal
            logins (`noEnv`, shared and restarted, or created on an environment
            that passes nothing) and its creator did not make it private.
            `private`: only its creator can use it. It holds their logins, or
            its creator made it private (`POST /sandboxes/{sandboxId}/unshare`,
            or the organization's `newSandboxesPrivate` default).
        cost:
          type: object
          description: >-
            Only with `include=cost` on `GET /sandboxes`. Machine time this
            sandbox used this calendar month (UTC), at list price. Same meter as
            `GET /sandboxes/{sandboxId}/usage`.
          required:
            - since
            - seconds
            - dollars
          properties:
            since:
              type: string
              format: date-time
              description: The 1st of this month, 00:00 UTC.
            seconds:
              type: integer
              description: Billable machine-seconds, size multiplier applied.
            dollars:
              type: number
              description: seconds / secondsPerDollar, at list price.
        wipePendingUntilRestart:
          type: boolean
          description: >-
            True once the sandbox is shared but not restarted yet. Its creator's
            logins are wiped at its next start, and the organization can use it
            from then on.
        subdomain:
          type:
            - string
            - 'null'
          description: >-
            The sandbox's stable three-word subdomain slug (e.g.
            "frazil-pneuma-rallye"), or null before one is assigned.
        lastSnapshotAttemptAt:
          type:
            - string
            - 'null'
          format: date-time
          description: >-
            Timestamp of the most recent snapshot attempt of any status (queued,
            in_progress, completed, failed, cancelled), or null. Use with
            snapshotCompletedAt to detect snapshots that keep failing.
        lastSnapshotStatus:
          type:
            - string
            - 'null'
          enum:
            - queued
            - in_progress
            - completed
            - failed
            - cancelled
            - null
          description: >-
            Status of the most recent snapshot attempt, or null if none. A value
            other than completed while snapshotCompletedAt stays stale indicates
            failing snapshots.
        lastReboot:
          type:
            - object
            - 'null'
          description: >-
            The last time the sandbox's kernel restarted on its machine, or null
            if it never did. Every process running at that time ended. `crash`
            means the system log ended with no shutdown, for example after a
            kernel panic.
          properties:
            at:
              type: string
              format: date-time
            reason:
              type: string
              enum:
                - crash
                - clean
                - unknown
        setupStatus:
          type:
            - string
            - 'null'
          enum:
            - pending
            - running
            - done
            - failed
            - null
          description: >-
            Outcome of the create-time `setupScript`: `pending` (stored, not yet
            started), `running` (executing on the sandbox in the background),
            `done` (exit code 0) or `failed` (non-zero exit, or the sandbox lost
            track of the process). Null when the sandbox was created without a
            setup script.
        setupError:
          type:
            - string
            - 'null'
          description: >-
            Short failure detail (exit code plus a stderr tail) when
            `setupStatus` is `failed`; while `pending`, may carry the last
            start/upload error from a retry in progress. Otherwise null.
        environment:
          type:
            - string
            - 'null'
          description: >-
            Name of the sandbox environment this sandbox is running, or null if
            it is attached to none (a `noEnv` sandbox, or one whose environment
            was deleted). A sandbox freezes onto one environment version when it
            starts and keeps it for life, so this is what the sandbox actually
            holds, not what the environment says today.
          examples:
            - base
        environmentVersion:
          type:
            - integer
            - 'null'
          description: >-
            Version number of `environment` that this sandbox is pinned to.
            Compare it against the environment's latest version to see whether
            an upgrade is pending: a sandbox below the latest is still running
            the older configuration until someone calls `POST
            /environments/{environmentId}/upgrade`.
          examples:
            - 3
        stop:
          description: >-
            The last stop you requested (`POST /sandboxes/{sandboxId}/stop`), or
            null if you never stopped this sandbox.
          oneOf:
            - $ref: '#/components/schemas/StopOperation'
            - type: 'null'
    ErrorEnvelope:
      type: object
      required:
        - ok
        - type
        - status
        - code
        - message
        - error
        - requestId
      properties:
        ok:
          type: boolean
          examples:
            - false
        type:
          type: string
          examples:
            - sandbox.error
        status:
          type: integer
          examples:
            - 409
        code:
          type: string
          examples:
            - provider_not_configured
        message:
          type: string
          examples:
            - Prompting is locked until Codex is configured on the Agents page.
        requestId:
          type: string
          examples:
            - req_01HX...
        error:
          type: object
          required:
            - code
            - message
            - status
          properties:
            code:
              type: string
            message:
              type: string
            status:
              type: integer
            details:
              type: object
              additionalProperties: true
    StopOperation:
      type: object
      required:
        - id
        - status
        - requestedAt
        - lastAttemptAt
        - error
        - endedAt
      properties:
        id:
          type: string
          description: >-
            Stable id of this stop. Calling stop again while it is pending
            returns the same id.
          examples:
            - stop_3f9a1c2e7b4d5a60
        status:
          type: string
          enum:
            - pending
            - failing
            - completed
            - superseded
          description: >-
            `pending`: accepted, the sandbox is archiving. `failing`: the last
            attempt failed (see `error`); it is retried automatically until the
            sandbox archives. Running commands or prompts does not cancel it.
            `completed`: the sandbox is archived. `superseded`: a resume ended
            it before it completed.
        requestedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: >-
            When the stop was accepted. On the sandbox, null once it has ended.
            Read by id (`GET /sandboxes/{sandboxId}/stops/{stopId}`), it is
            kept.
        lastAttemptAt:
          type:
            - string
            - 'null'
          format: date-time
          description: When the last archival attempt ended.
        error:
          type:
            - string
            - 'null'
          description: >-
            Why the last attempt failed, while `status` is `failing`. Otherwise
            null.
        endedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: When the stop completed or was superseded.
        forced:
          type: boolean
          description: >-
            True when a force (`--force`) ended this stop. The sandbox kept its
            last completed snapshot, and changes after it are discarded.
  responses:
    Unauthorized:
      description: Missing or invalid bearer token.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorEnvelope'
          examples:
            unauthorized:
              value:
                ok: false
                type: sandbox.error
                status: 401
                code: unauthorized
                message: Unauthorized
                error:
                  code: unauthorized
                  message: Unauthorized
                  status: 401
                requestId: req_01HX...
    PaymentRequired:
      description: >-
        Account cannot currently create or operate sandboxes. The error body may
        include a dashboard billing URL, but billing actions are not part of the
        v1 API.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorEnvelope'
    EnvironmentForbidden:
      description: >-
        `environment_forbidden`: the organization limits this environment to
        other members. Ask an owner or admin to add you. Other `403` codes can
        also apply.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorEnvelope'
          examples:
            environmentForbidden:
              value:
                ok: false
                type: sandbox.error
                status: 403
                code: environment_forbidden
                message: You cannot use this environment.
                error:
                  code: environment_forbidden
                  message: You cannot use this environment.
                  status: 403
                requestId: req_01HX...
    Conflict:
      description: Request conflicts with current account or sandbox state.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorEnvelope'
    RateLimited:
      description: >-
        Machine start or concurrent-sandbox limit reached. Create, fork and
        resume each count as one machine start against your plan's start limits
        (see the Billing guide; `rate_limited`, naming the window and the
        `limit` that applied). With money in the wallet after the first payment,
        starts above a limit are paid, up to `startLimitsWithWallet`; the body
        carries `startLimitsWithWallet`, null when extra starts are not
        available. A sandbox that would exceed your plan's concurrent-sandbox
        cap is refused with `limit_reached`, or `member_limit_reached` when an
        organization owner has capped you below the plan.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorEnvelope'
    NoReadyMachine:
      description: >-
        No capacity. `no_ready_machine`: a `failFast` create, fork or resume
        found no ready machine of that type; nothing was started, billed, or
        counted, and a resumed sandbox stays stopped. `out_of_capacity`: creates
        and forks are paused until the provisioning queue drains.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorEnvelope'
  securitySchemes:
    BoatBearerAuth:
      type: http
      scheme: bearer
      bearerFormat: sandbox_api_key
      description: >-
        Boat bearer token in the form `boat_...`. Service API keys authenticate
        sandbox operations.

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.