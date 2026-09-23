# Image Lab UI IPC implementation plan

Status: initial IPC v1 implemented and locally verified.

## Implementation record

- Phase 1: Qt local server, standard-library client, strict protocol validation,
  per-catalog discovery, same-user endpoint permissions, and `image-lab ctl`.
- Phase 2: shared edit/rename actions, QML control/state bridge, window, library,
  view, selection, viewer, and panel controls.
- Phase 3: explicit-ID analysis, tracked operations, queue controls, metadata
  revisions, exact-rename confirmation, and validated settings updates.
- Phase 4: snapshot/event subscriptions, sequencing, coalesced state updates,
  client/input/output limits, timeout handling, and bounded operation retention.
- Phase 5: package builds and installed-process acceptance via
  `tools/smoke_ui_ipc.py`, with disposable state and fake inference.

Verification: 132 tests passed on local Python 3.14, including 20 IPC tests.
Full suite evidence: `results/ipc-full-tests.log`. Build and installed-wheel
acceptance evidence: `results/ipc-build.log`, `results/ipc-installed-smoke.log`.
The installed smoke covers import, selection/viewer, fake analysis and events,
metadata edits, guarded renaming, settings, and safe close outside the checkout.

Implementation choices: gallery reveal is limited to the first 1000 matches to
bound main-thread allocations; viewer navigation still spans the full filtered
library. Opening the details panel requires an editable highlighted image, while
explicit-ID metadata and rename commands preserve visible selection. `operation
wait` is a client-side bounded poll. Event subscriptions use dedicated connections.

Validation scope: Linux/Python 3.14 with existing Pillow/NumPy/Qt dependencies;
no fresh dependency-resolution matrix or live Ollama inference was run. No
personal catalog, desktop keybinding, or Imagescope source was changed. The
original phased design follows; `IPC_PROTOCOL.md` is the implemented contract.

## Goal and ownership

Provide a complete, documented local control interface to a running Image Lab
GUI for shell scripts, keybindings, tests, and future agent integrations.

Keep the existing command split:
- `image-lab-ui`: desktop application and IPC server.
- `image-lab ctl ...`: new control client, alongside existing `doctor` and `analyze`.
- `imagescope`: independent analysis CLI/library. Its analysis protocol is not
  the UI control protocol and must not acquire catalog or UI responsibilities.

“Full control” means explicit application operations and observable state, not
arbitrary widget access, mouse/keyboard simulation, QML evaluation, or Python
execution. No HTTP listener, remote access, MCP server, new daemon, or direct
client-side database manipulation is in scope.

## Current integration points

- `image_lab_ui/app.py`: `Controller` already owns search, selection, imports,
  queue actions, metadata edits, renaming, preferences, and worker lifecycle.
- `image_lab_ui/Main.qml`: owns panel/dialog visibility and the busy-close guard.
- `image_lab_ui/ImageViewer.qml`: owns viewer image and GIF playback state.
- `image_lab_ui/queue.py`: owns persistent batch/job state and recovery.
- `image_lab_ui/catalog.py`: owns queries, metadata writes, and safe renaming.
- `image_lab_ui/storage.py`: resolves catalog and cache paths.
- `app.main()`: holds a per-catalog `QLockFile`; currently rejects a second
  process using the same catalog.
- `image_lab.py`: current legacy CLI; add a `ctl` branch without breaking its
  existing `doctor`/`analyze` behavior.

Some slots report failure only through a status label, depend on current
selection, or return nothing. They cannot simply be exported as RPC methods.
Create shared validated operations with structured outcomes; both GUI slots and
IPC handlers must use them. Preserve GUI behavior during this refactor.

## Architecture decisions

### Server, discovery, and client

Use `QLocalServer`/`QLocalSocket` for the server's Unix-domain transport. A small
standard-library Unix-socket client keeps `image-lab ctl` usable without Qt.

Use a private directory under `$XDG_RUNTIME_DIR/image-lab/` (mode 0700), with a
socket per canonical catalog path, named using a fixed-length SHA-256 identifier.
Validate runtime-directory ownership and permissions; fail IPC clearly if unsafe
or unavailable rather than falling back to a shared `/tmp` socket. Check Unix
socket path length before binding and produce an actionable error.

The server uses same-user socket access restrictions (and checks filesystem
permissions). Treat all same-user processes as trusted principals, but still
validate every request. There is no claim of protection against a compromised
process running as the same user.

`--data-dir` selects the catalog using the same path resolution as the GUI;
`instances` lists reachable endpoints, not merely socket files. A hello response
identifies the canonical catalog, instance ID, application version, protocol
version, and capabilities. Refuse a mismatched catalog or incompatible protocol.

Start listening only after acquiring the catalog lock and successfully creating
the controller/QML interface. A second GUI process must never remove the first
process's socket. Remove stale endpoints only while holding the matching catalog
lock, after checking ownership and that the endpoint is not reachable. Clean up
only this instance's endpoint on shutdown.

IPC is enabled for normal GUI launches; provide `--no-ipc`. An IPC startup failure
must be visibly reported, never silently advertised as a usable endpoint. Keep
the desktop usable, but make control clients return `unavailable`.

For version 1, a second GUI launch retains the existing catalog-lock error;
automatic launch forwarding is deferred. The control client never starts the GUI
or creates a catalog implicitly.

### Wire protocol

Document the implementation contract in `docs/IPC_PROTOCOL.md` during phase 1.
Use bounded newline-delimited UTF-8 JSON envelopes, independent of Imagescope's
protocol version:

```json
{"protocol_version":1,"id":"req-1","method":"app.status","params":{}}
{"protocol_version":1,"id":"req-1","result":{"ready":true}}
{"protocol_version":1,"id":"req-2","error":{"code":"busy","message":"Scan is active"}}
```

Exactly one response per accepted request ID: either `result` or `error`, never
both. Reject duplicate in-flight IDs, unknown methods/parameters, malformed JSON,
non-finite numbers, incorrect types, and out-of-range values. No dynamic dispatch
through `getattr`, arbitrary paths into QObject trees, or executable payloads.

Initial bounds to implement and test:
- 1 MiB per complete message and per partial input buffer.
- 16 clients and 32 in-flight requests per client.
- 4 MiB maximum queued output per client; disconnect slow consumers explicitly.
- Maximum page size 200 and explicit limits on image-ID lists and strings.
- Client connection timeout 2 seconds, ordinary response timeout 10 seconds;
  waiting for long operations uses a separate explicit timeout.

Long work returns `accepted` plus an operation ID immediately. Operations expose
queued/running/succeeded/failed/cancelled states. Submission acceptance is not
success, and disconnecting a client does not cancel accepted work.

Request IDs correlate messages, not durable idempotency keys. Do not automatically
retry mutations after an ambiguous disconnect. Operation IDs are instance-scoped;
existing persistent batch/job IDs are included where available. Maintain a bounded
recent-operation history and return `not_found` after eviction or restart.

Stable error categories include `invalid_request`, `unsupported_protocol`,
`unknown_method`, `not_found`, `busy`, `conflict`, `confirmation_required`,
`unavailable`, and `internal_error`. Do not expose tracebacks over IPC. Define CLI
exit codes for success, application failure, usage error, unavailable transport,
and timeout. `--json` must emit machine output only on stdout; diagnostics go to
stderr.

### Threading, state, and events

Own the server/router on Qt's main thread. All controller and QML mutations must
run there. Reuse existing workers for scanning, queue submission, decoding, and
inference; never run blocking analysis from a socket callback. Bound work per
event-loop iteration so a command flood cannot freeze the desktop.

Introduce an explicit UI bridge for viewer, panel, and window operations. Route
both user actions and IPC through it, and report actual resulting state rather
than assuming a signal was acted upon. Share close eligibility between the GUI
and IPC: busy close returns `busy`; no implicit force-kill or data loss.

Distinguish highlighted image, checked batch selection, and viewer image. Prefer
explicit setters over toggle commands. Library queries should not change the
visible search unless explicitly requested.

Event subscriptions receive an initial snapshot followed by ordered, sequenced
events from the same instance. Sequence numbers and instance IDs let clients
detect gaps/restarts and resnapshot. No durable replay in version 1. Coalesce
high-frequency progress notifications, but never silently discard terminal
operation events; disconnect overflowing subscribers so they can resynchronize.

## Command surface

Names below are the planned public CLI; finalize wire method names in phase 1.

| Area | Operations |
| --- | --- |
| Discovery | `instances`, `capabilities`, `status` |
| Window | `window show/hide/focus/close`; focus is a compositor request, not a guarantee |
| Library | `library list/get/import`, `library scan-stop`; paginated read queries |
| Visible view | `view search/filter`, gallery paging/reveal |
| Selection | `selection get/set/clear`, explicit checked IDs, select matching results |
| Viewer | `viewer open/close/next/previous`, explicit GIF play/pause, viewer status |
| Panels | `panel open/close` for a fixed allowlist: queue, settings, details, about |
| Analysis | `analyze --ids ...`, missing-only generation, explicit regeneration |
| Queue | `queue status/list/pause/resume/stop/retry/remove` |
| Metadata | `details get/update` with expected edit revision |
| Rename | `rename preview/apply` with image ID, expected source path, and confirmed target |
| Preferences | `settings get/set` using existing validators |
| Observation | `events`, `operation get/wait` |

Viewer navigation follows the current filtered/sorted library, not only loaded
QML tiles; define endpoint behavior (no wrap by default). Explicit-ID operations
must not secretly replace the user's visible selection. Bulk actions must use a
bounded resolved set or a revision-checked query snapshot, not a changing query.

Examples:

```sh
image-lab ctl status --json
image-lab ctl library import ~/Wallpapers
image-lab ctl view search mountains
image-lab ctl selection set 12 34
image-lab ctl viewer open 12
image-lab ctl analyze --ids 12 34
image-lab ctl queue pause
image-lab ctl events
```

## Safety and compatibility

- Renaming preserves existing no-overwrite, expected-path, catalog-conflict, and
  rollback protections. Require an explicit CLI confirmation flag / protocol
  confirmation field; it must bind to the exact proposed rename, not a generic
  “confirm anything” state. Revalidate at execution time.
- Metadata edits require current revision values; reject stale writes.
- Regeneration explicitly opts into replacing predictions. Preserve good results
  when analysis fails, matching current queue behavior.
- `queue stop` retains stop-after-current semantics; do not promise to interrupt
  Ollama's already submitted work. Scan cancellation remains cooperative.
- IPC does not add image deletion, arbitrary shell commands, screenshots, or
  clipboard reads. Clipboard writes, if exposed later, require a named operation.
- Paths and descriptions may be sensitive. Do not log request bodies by default.
- Keep all live state changes serialized through existing application ownership;
  never open an independent writer connection in the CLI.
- Protocol-breaking changes require a new IPC version; capabilities describe
  optional features. Existing Imagescope protocol guards remain unchanged.

## Delivery phases and completion gates

### 1. Protocol, transport, and read-only discovery

Add protocol validation, endpoint resolution, server/client lifecycle, and
`image-lab ctl` parsing. Implement capabilities, instance discovery, and status.
Suggested files: `image_lab_ui/ipc_protocol.py`, `ipc_server.py`, `ipc_client.py`,
`control_cli.py`; CLI-facing modules must not import Qt.

Gate: a separate client process can query a running disposable GUI. Tests cover
framing, partial/multiple messages, malformed input, size limits, timeouts,
permissions, stale sockets, duplicate launches, and two distinct catalogs.

### 2. Shared application actions and UI bridge

Refactor controller actions to structured results without changing QML behavior.
Implement window/view/selection/viewer/panel controls plus paginated library reads
and imports. Add the explicit QML bridge and observable viewer/panel state.

Gate: every action produces the same application result through GUI and IPC.
Test focus request reporting, busy close refusal, selection/viewer independence,
invalid IDs, navigation across unloaded pages, and responsive long imports.

### 3. Queue, edits, preferences, and guarded mutations

Implement explicit-ID queue submission, queue controls, metadata revisions,
rename preview/apply, and validated settings. Assign operation IDs at submission
and expose operation queries before adding subscriptions.

Gate: tests cover concurrent UI/client edits, stale revisions/paths, failed
submissions, duplicate/ambiguous requests, original-file preservation, rename
rollback, queue recovery, stop semantics, and disconnected clients.

### 4. Events and production hardening

Add snapshot-plus-stream subscriptions, operation waits, progress coalescing,
backpressure limits, and bounded operation retention. Document lifecycle and
failure semantics; add CLI examples for keybindings and automation.

Gate: separate-process tests cover event ordering, restart detection, slow and
abruptly disconnected subscribers, terminal state visibility, command floods,
and shutdown with active work. All existing tests continue to pass.

### 5. Packaging and end-to-end acceptance

Build and install Image Lab with the separate Imagescope package. From outside
the source checkout, launch an offscreen GUI with disposable catalog/cache and
private runtime directories, then exercise the installed `image-lab ctl` client.
Verify source paths do not mask installed imports.

Gate: scripted flow imports synthetic images, searches/selects, opens/closes the
viewer, submits fake-backend analysis, watches completion, edits metadata,
renames with confirmation, changes preferences, and closes safely. Keep automated
checks independent of a running Ollama service. Perform an optional explicit
live-model check separately; never claim fake-backend tests establish model quality.

## Test and documentation deliverables

- Unit suites for wire validation, CLI parsing, action results, and endpoint logic.
- Qt/offscreen integration tests with real Unix sockets and separate clients.
- Installed-package smoke test covering CLI and GUI entry points.
- Capability/command inventory ensuring every shipped method is documented and
  has success, invalid-input, and failure-path coverage.
- `docs/IPC_PROTOCOL.md`: authoritative envelopes, methods, errors, events, limits.
- `docs/IPC.md`: user commands, instance selection, security, and troubleshooting.
- README setup/control examples, preserving legacy CLI documentation.

## Deferred work

Remote transport/authentication, MCP adapters, persistent event replay, automatic
GUI startup/launch forwarding, forced inference cancellation, and new destructive
file operations are separate follow-up projects. Do not expand the first IPC
release to include them.
