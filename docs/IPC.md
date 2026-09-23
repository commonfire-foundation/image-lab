# Controlling the Image Lab GUI

`image-lab ctl` controls an already running `image-lab-ui` instance. It does not
start the app, invoke a shell, or open the catalog database itself. The legacy
`image-lab doctor` and `image-lab analyze` commands remain unchanged.

## Quick start

Use the same virtual environment as the desktop:

```sh
.venv/bin/image-lab-ui
.venv/bin/image-lab ctl status
.venv/bin/image-lab ctl instances --json
.venv/bin/image-lab ctl window focus
.venv/bin/image-lab ctl library list --limit 20 --json
.venv/bin/image-lab ctl viewer open 12
.venv/bin/image-lab ctl viewer close
```

For a non-default catalog, give both the GUI and control client the same
`--data-dir /absolute/catalog-directory`. Global client options also work after
subcommands. Commands never implicitly select a different catalog.

The GUI enables IPC by default; `image-lab-ui --no-ipc` disables it. Restart an
older running GUI after installing this version. A keybinding can call the
absolute path to `.venv/bin/image-lab ctl window focus`; focus is requested from
the compositor, not guaranteed. No desktop keybindings are modified automatically.

## Imports, selection, and the viewer

```sh
image-lab ctl library import ~/Wallpapers --json
image-lab ctl operation wait OPERATION_ID --wait-timeout 600 --json
image-lab ctl view search mountains
image-lab ctl view filter needs_tags
image-lab ctl selection matches
image-lab ctl selection set 12 34
image-lab ctl selection highlight 12
image-lab ctl viewer open 34
image-lab ctl viewer next
image-lab ctl panel open queue
```

Import returns an operation ID immediately; wait/query that ID to observe actual
completion. A successful scan may report unreadable files in its completion
message. Stopping a scan is cooperative: `library scan-stop`.

Highlighted image, checked batch selection, and viewer image are independent.
`selection set` replaces the checked IDs; `highlight` changes the sidebar.
`library list --query ... --filter ...` queries without altering the visible view.
`view search/filter` change the visible view and clear checked selection, matching
the GUI. `selection matches` resolves at most 1000 current matches; narrow a larger
query. `selection get` reports truncation if the GUI selected more than 1000.

Viewer navigation follows the full filtered/path-sorted library, including rows
not loaded into the gallery. Navigation stops at the ends. `viewer play/pause`
controls an open GIF. `view page` loads one more gallery page; `view reveal ID`
reveals an image within the first 1000 matches, otherwise asks for a narrower
search. Panels: `queue`, `settings`, `details`, `about`; opening details requires
an editable highlighted image.

## Analysis and queue control

```sh
image-lab ctl analyze --ids 12 34 --json
image-lab ctl analyze --missing --query mountains --json
image-lab ctl analyze --ids 12 --replace --json
image-lab ctl queue list --limit 50
image-lab ctl queue pause
image-lab ctl queue resume
image-lab ctl queue remove JOB_ID
image-lab ctl queue retry JOB_ID
image-lab ctl queue stop
```

`analyze` does not alter visible selection. Already queued/tagged images are
skipped unless replacement is requested; a submission adding nothing ends as a
failed operation with an explanation. Operation results include persistent batch
and newly created job IDs. Pausing waits for the current image. Stop cancels
waiting items and lets the current image finish; it cannot guarantee Ollama
stops work already submitted. Only waiting jobs can be removed, and only the
latest failed job for an image can be retried.

Disconnecting a client does not cancel accepted work. Operation IDs belong to a
single GUI instance. Up to 128 recent operations (32 active) are kept in memory;
old finished records expire. Persistent jobs remain inspectable via `queue list`.
Do not automatically retry a mutation after a transport failure: its outcome may
be unknown. Request IDs are correlations, not durable idempotency keys.

## Metadata, renames, and settings

```sh
image-lab ctl details get 12 --json
image-lab ctl details update 12 --revision REVISION --values '{"caption":"Red","tags":["red"],"medium":"abstract","mood":[],"composition":[],"text_present":false,"watermark_present":false}'
image-lab ctl rename preview 12 --expected-path /images/a.png --name b.png --json
image-lab ctl rename apply 12 --expected-path /images/a.png --name b.png --confirm TOKEN
image-lab ctl settings get --json
image-lab ctl settings set --values '{"animateHoveredGifs":false}'
```

Use the `values` object and `revision` returned by `details get`. Edits reject
stale revisions and busy/queued images. Rename requires the exact preview token,
bound to this GUI instance, image identity, expected source, imported fingerprint,
and target. Preview is not a reservation; apply rechecks filesystem/catalog
conflicts and retains no-overwrite/rollback safeguards. These operations do not
change highlighted selection. Settings updates merge a validated partial object.

## Events, failures, and security

`image-lab ctl events --json` prints a snapshot, then sequenced JSON events.
`--count N` stops after N events; `--wait-timeout` defaults to 300 seconds and bounds
the subscription. Use a dedicated connection for events. Events expose progress,
UI/settings state, and operation transitions, not arbitrary widget properties.
There is no replay: after a gap, disconnect, or restart, get a new snapshot.

Exit codes: 0 success, 1 application/conflict/operation failure, 2 invalid request
or usage, 3 unavailable/incompatible transport, 4 timeout, 130 interruption.
`--json` emits compact JSON to stdout; parser usage errors remain on stderr.
Ordinary calls default to a 10-second response timeout; connecting takes at most
2 seconds. `operation wait` uses its own wait timeout; timing out leaves work
running. Closing while busy fails instead of killing workers.

Sockets live in a private 0700 `$XDG_RUNTIME_DIR/image-lab/` directory, keyed by
the canonical catalog path. Socket mode is 0600. Missing/unsafe runtime directories
or overly long socket paths produce an IPC startup diagnostic while the GUI stays
usable. Do not chmod a shared directory to work around this; use the private
runtime directory supplied by your desktop session. A second GUI cannot take over
an active catalog. Stale socket recovery requires acquiring the catalog lock.

This is a same-user local interface, not an authentication boundary against other
processes running as you. Paths, captions, and state may be sensitive. There is no
TCP listener, remote access, evaluation, image deletion, clipboard read, or shell
execution method. See `IPC_PROTOCOL.md` for the wire contract and limits.
