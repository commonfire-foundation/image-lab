# Image Lab UI IPC protocol 1

This protocol controls the GUI. It is independent of Imagescope's analysis
protocol. `ipc_methods.METHODS` is the executable method/parameter inventory,
returned verbatim by `app.capabilities` and the connection hello. Adding optional
fields/methods is compatible; removing requirements or changing existing meanings
requires a protocol version change.

## Transport and framing

Unix stream socket served by Qt `QLocalServer`; one UTF-8 JSON object per newline.
The server first sends a hello with `protocol_version: 1`, `type: "hello"`,
`instance_id`, canonical `catalog`, `application_version`, and `capabilities`.
Clients must verify protocol and catalog identity before writing. Endpoint naming
is the first 32 hex characters of SHA-256 of the filesystem-encoded canonical
catalog-directory path plus `.sock`, under `$XDG_RUNTIME_DIR/image-lab/`.

```json
{"protocol_version":1,"id":"req-1","method":"app.status","params":{}}
{"protocol_version":1,"id":"req-1","result":{"ready":true}}
{"protocol_version":1,"id":"req-2","error":{"code":"busy","message":"Scan is active"}}
```

Requests require exactly those four envelope fields. IDs/methods are nonempty
strings of at most 128 characters; params must be an object. Unknown parameters,
duplicate JSON keys, non-finite numbers, booleans masquerading as integers, and
invalid types/ranges are rejected. Each processed request receives one response
with its ID and either result or error. Duplicate in-flight IDs and malformed
framing produce an error with null ID then disconnect; queued unprocessed requests
may receive no response. Connection loss leaves mutation outcomes ambiguous.
Requests are serialized per peer, with one dispatch per Qt event-loop turn.

## Limits

- 1 MiB per message/partial input buffer, including newline on emitted messages.
- 16 concurrent clients; excess connections are closed.
- 32 pending requests per client; excess or duplicate in-flight IDs disconnect.
- 10 seconds to finish a partial line; idle complete-message connections remain open.
- 4 MiB queued output per peer; slow peers are disconnected rather than silently
  losing terminal events. Large responses return an error requesting smaller pages.
- Lists of IDs: at most 1000 unique positive signed-64-bit integers.
- Page limits: 1–200, default 50; offsets: 0–2147483647.
- Generic parameter strings: at most 4096 characters, no NUL.
- 128 retained operations, at most 32 active; finished records are evicted oldest first.
- Instance discovery probes at most 64 endpoints. Clients must only probe private,
  same-user sockets and must not remove them.

## Method inventory

Parameters marked `?` are optional. Every unlisted parameter is an error. All
methods except discovery/observation execute on the owning GUI instance. UI actions
use the explicit bridge to existing QML functions, not arbitrary QObject access.

| Method | Parameters | Result / semantics |
| --- | --- | --- |
| `app.status` | none | Busy/submitting/scanning, view, selection, UI, batch, progress, settings, operation IDs |
| `app.capabilities` | none | Method schemas and operation/page limits |
| `events.subscribe` | none | Instance, sequence, snapshot; subsequent event frames |
| `window.show/hide/focus` | none | Observed UI state; focus-request indicator |
| `window.close` | none | Requested flag; busy rejection, deferred guarded close |
| `library.list` | query?, filter?, offset?, limit? | Compact image records and total; no view changes |
| `library.get` | image_id | Image details, editable values, revision |
| `library.import` | path | Accepted operation ID; folder must exist |
| `library.scan-stop` | none | Cooperative cancellation request; conflicts if no scan |
| `view.search` | query | Visible query and page state; clears checks |
| `view.filter` | filter | Visible filter/page state; changed filters clear checks |
| `view.page` | none | Load the next gallery page |
| `view.reveal` | image_id | Reveal index within first 1000 current matches |
| `selection.get` | none | Highlighted ID, checked IDs/count, truncation flag |
| `selection.set` | ids | Replace checked set; validate all IDs before changing it |
| `selection.clear` | none | Clear checked set, not highlighted/viewer image |
| `selection.highlight` | image_id | Change sidebar image |
| `selection.matches` | query?, filter? | Resolve/check at most 1000 matches, defaults to visible query/filter |
| `viewer.status` | none | Observed UI state including viewer ID and playback |
| `viewer.open` | image_id | Open without changing sidebar or checked set |
| `viewer.close` | none | Close viewer |
| `viewer.next/previous` | none | Adjacent path-sorted filtered image; no wrapping |
| `viewer.play/pause` | none | Explicit playback state; requires open GIF |
| `panel.open/close` | panel | Fixed panel allowlist; details requires editable highlight |
| `analyze` | ids, replace? | Accepted operation; replace defaults false |
| `analyze.missing` | query?, filter? | Resolve bounded untagged set; default filter needs_tags |
| `queue.status` | none | Current batch summary |
| `queue.list` | offset?, limit? | Persistent job entries and total |
| `queue.pause/resume/stop` | none | Current batch; refuses scan/submission conflicts |
| `queue.retry` | job_id | Accepted operation for latest failed job's image |
| `queue.remove` | job_id | Cancel waiting job, never running job |
| `details.get` | image_id | Image, editable values, revision |
| `details.update` | image_id, revision, values | Updated details; full editable values required |
| `rename.preview` | image_id, expected_path, name | Source, target, instance-bound confirmation token |
| `rename.apply` | image_id, expected_path, name, confirmation | Updated details; revalidates and never overwrites |
| `settings.get` | none | Current preferences |
| `settings.set` | values | Merge validated preferences; return full preferences |
| `operation.get` | operation_id | Retained operation or not_found |

Filters: `all`, `needs_tags`, `tagged`, `failed`. Panels: `queue`, `settings`,
`details`, `about`. Library list defaults to an empty query and `all`; matching
and missing-generation queries default to the visible query. Explicit-ID mutations
never silently replace selection. `details.get.values` contains only editable
fields (caption, tags, medium, mood, composition, text_present, watermark_present),
not the immutable model provenance or other predicted attributes.

CLI `instances` is client-side reachable-endpoint discovery. `operation wait` is
client-side polling of `operation.get`, not a blocking server method. Snapshot
reads and events may contain sensitive paths and descriptions.

## Operations and events

Long imports and queue submissions return `{"accepted":true,"operation_id":"..."}`.
This acknowledges scheduling, not completion. States are `queued`, `running`,
`succeeded`, `failed`, `cancelled`. Operations have an instance ID, ID, kind,
creation time, and optional message. Analysis operations include batch/job IDs
once submission completes; completion tracks those jobs, not unrelated appended
jobs. A partial failure is failed; cancellation without failures is cancelled.
An import that skips unreadable files can succeed with an explanatory message.

Operations survive client disconnects but not GUI restarts. Persistent queue
records retain their existing recovery semantics. There is no implicit retry or
idempotency-key cache. Clients must reconcile state after uncertain writes.

Subscriptions use a dedicated connection. The subscribe response atomically
captures an instance ID, sequence number, and snapshot. Later frames are:

```json
{"protocol_version":1,"type":"event","instance_id":"...","sequence":42,"event":"operation.changed","data":{"id":"...","state":"succeeded"}}
```

`operation.changed` carries the operation record. `state.changed` carries a full
state snapshot and is coalesced to at most 10 Hz. Sequence numbers increase by
one per emitted event globally within that instance. There is no replay; gaps,
restart, or disconnection require resubscription and a fresh snapshot. Terminal
operation transitions are not coalesced; overflow closes the subscriber.

## Failures and lifecycle

Error codes: `invalid_request`, `unsupported_protocol`, `unknown_method`,
`not_found`, `busy`, `conflict`, `confirmation_required`, `unavailable`,
`internal_error`. Client-side waits additionally report `timeout`. Messages are
human-readable and not stable identifiers; unknown errors still mean failure.
Tracebacks and request bodies are not emitted over the wire.

CLI exit codes: 0 successful request (including acceptance), 1 application failure,
2 usage/validation, 3 unavailable/incompatible transport, 4 timeout, 130 interrupt.
A successful `operation wait` requires terminal succeeded; failed/cancelled returns 1.

Listening begins only after the per-catalog lock and QML setup succeed. The socket
uses 0600 permissions within private same-user 0700 directories. No shared `/tmp`
fallback is used. Stale socket removal requires catalog lock ownership and a
refused connection probe. Normal shutdown stops the listener; a crashed server's
stale endpoint is recoverable by the next lock owner.

Close never forces active work to terminate. A close response acknowledges the
request, not process death; the busy condition is rechecked before closing. All
other existing queue and filesystem safeguards remain enforced by shared actions.
Same-user clients are trusted principals, but inputs are validated and methods
remain allowlisted. No generic evaluation, shell execution, remote listener,
clipboard reads, or image-deletion capability is provided.
