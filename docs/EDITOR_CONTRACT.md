# Editor geometry contract — version 1

Status: in-memory geometry, isolated snapshot/render workers, and a shared color-
preparation core are implemented. Protocol v2 now carries selected color policy,
validated provenance, and ICC bytes through the isolated worker. S7 verifies a
tagged Qt preview bridge and original-measurement policy alignment. S8 adds the
asynchronous session controller. S9 installs live numeric controls and exclusive
UI/controller/IPC guards. S10 adds staged drag crop mapping and live gesture checks.
S11 adds the copy-publication primitive. S12 integrates bounded encoding, live
Export/import, saved checkpoints and managed original-source measurements. Software
encoded-color acceptance is recorded; monitor/HDR certification is not claimed.
Earlier slice boundaries below are historical and are extended by the S12 section.
See `docs/EDITOR_PLAN.md` and `docs/EDITOR_IMPLEMENTATION.md` from the repository root.

## Ownership and scope

`image_lab_ui/edit_recipe.py` is independent of Qt, Imagescope, and Pillow.
`image_lab_ui/edit_render.py` uses Pillow only for transforms on decoded RGB/RGBA
pixels. Neither module opens source paths, writes images, launches inference, or
changes the catalog. Tests generate synthetic fixtures inside the repository.

The geometry function itself is not an entry point for loading arbitrary image
files. `edit_process.py` now supervises isolated snapshot/decode/render work, source
identity checks, explicit orientation, and opt-in managed color. Legacy defaults
remain unmanaged; software preview/export acceptance is recorded in S12 below. The geometry renderer rejects
a lazy image with an open file pointer, unsupported modes, mismatched dimensions,
and over-budget geometry; those checks do not replace worker isolation.

## Serialized recipe

```json
{
  "version": 1,
  "source_size": [1200, 800],
  "crop": [0, 0, 1200, 800],
  "quarter_turns": 0,
  "flip_horizontal": false,
  "flip_vertical": false,
  "output_size": null,
  "allow_upscale": false
}
```

- All fields are required. Unknown fields/versions are rejected. Booleans are
  not integers; numeric strings/floats cannot substitute for integer dimensions.
- `source_size` is the EXIF-oriented original size, not a thumbnail size.
- `crop` is integer half-open `[left, top, right, bottom]` in that source space.
  Width and height must be positive; bounds must lie inside the original.
- `quarter_turns` is 0–3 clockwise turns after the crop. Horizontal then vertical
  flips operate in the rotated axes, not the original source axes.
- `output_size: null` means the natural cropped/rotated dimensions. Explicit output
  dimensions preserve aspect ratio within one integer rounding step: either width
  or height is the driving dimension; the other is computed by half-up rounding
  and clamped to at least one pixel. Arbitrary stretching is rejected.
- Source and output areas are limited to 40,000,000 pixels. This is a geometry
  ceiling, not a claim that every such file can be safely decoded in available RAM.
- `allow_upscale` must be explicitly true to enlarge either natural dimension.
  Disabling it while an oversized target is active is rejected; callers must first
  choose an output size that fits.

Source path, digest, device/inode, session ID, and color/provenance identifiers are
not geometry fields. The future session/worker envelope must bind a recipe to
those identities. Equal image dimensions are not proof of equal source identity.

## Commands and coordinate mapping

- Crop changes clear explicit resize dimensions, preserving rotation/flips.
- Aspect presets choose the largest exact integer-ratio rectangle centered inside
  the current crop. For odd spare pixels, left/top receive the smaller margin.
  Odd quarter-turns swap the ratio axes before cropping. If the exact reduced
  ratio cannot fit even once, the command fails rather than inventing pixels.
- Rotation commands act clockwise on the displayed result. They swap explicit
  output dimensions and horizontal/vertical flip flags for odd turns. This keeps
  rotation-after-flip behavior intuitive while retaining a canonical recipe.
- Resize-by-width/height uses the natural result aspect ratio. Percentage resize
  is relative to natural size, not cumulative; valid percentages are >0–10000,
  subject to pixel and explicit-upscale limits.
- `source_to_result` and `result_to_source` use continuous pixel-edge coordinates.
  Pixel centers are at `(x + 0.5, y + 0.5)`; right/bottom boundary points are valid.
  They include crop offset, user rotation, flips, and output scaling without
  rewriting integer crop bounds or rounding pointer positions prematurely.
- `FitTransform` maps result pixels to a letterboxed viewport in Qt logical units.
  Pointer input from QML is already logical: do not multiply it by device-pixel
  ratio again. Physical-pixel input must first be divided by DPR. The future
  preview allocation policy handles DPR separately from gesture coordinates.
  Letterbox clicks are rejected unless explicit clamping is requested.

## History and export checkpoint

`EditHistory` retains at most 100 immutable recipe states, not raster copies.
Commit once per completed gesture. Duplicate commits do nothing; changes after
undo discard the redo branch. Reset returns to the session's original recipe and
is itself undoable while retained by the history limit.

Dirty state compares the current recipe with the last successfully exported
recipe, initially the original. `mark_exported(recipe)` takes the exact submitted
recipe so a late completion cannot incorrectly mark newer edits as saved.
Publication failure must never call it. The future session layer must also reject
completion from the wrong source/session and serialize or cancel conflicting work.

## Rendering contract

`render_geometry(image, recipe, orientation=..., preview_longest=...)` requires
already decoded, appropriately color-handled RGB/RGBA pixels. Orientation is
explicitly supplied (1–8); missing metadata must be resolved by the accepted
provider policy rather than silently guessed here.

Order: EXIF orientation once → crop → user quarter-turns → horizontal/vertical
flips → resize. Before calling this function, any accepted conversion-before-
orientation/reduction policy must already have been applied in the worker.

- Resizing uses Pillow LANCZOS; RGBA resizing uses Pillow's premultiplied-alpha
  behavior, with tests that hidden transparent RGB does not contaminate visible
  pixels. This is not a linear-light resampling claim.
- Returned images are independent of the input. Derived metadata is cleared except
  opaque ICC bytes, which are retained without claiming they are valid or sRGB.
  The future color-policy layer must validate compatibility before this point.
- `preview_longest` is 1–2048 when present. Rendering samples directly to that
  bounded result instead of allocating a resized full output and reducing it
  again. Geometry agrees with full rendering; resampling detail is approximate.
- A `RenderedImage` records intended full output size separately from raster size.
  Preview results remain tagged even when no reduction was needed.
  `full_resolution_image()` rejects all previews; full output always uses original
  pixels, never a previously rendered thumbnail.

No export codecs, JPEG matting, color conversions, or UI lifecycle behavior are
implied by the geometry implementation. Worker quotas and snapshot rules follow.

## Isolated snapshot/render worker — S2, extended by S6

`edit_process.prepare_source(path)` returns a `SourceSnapshot` after a complete
bounded decode. `render_source(snapshot, recipe, ...)` revalidates that source and
returns a `WorkerImage` of raw RGB/RGBA bytes. These APIs are blocking and must run
off the Qt thread. They create no source copies, temporary files, or export files.

- All source path resolution, opening, reading, hashing, and decoding happen in
  the child—not the caller—under the supervisor's wall deadline.
- Snapshot identity includes canonical path, device/inode, encoded size, mtime,
  ctime, SHA-256, stored dimensions, explicit/assumed EXIF orientation, detected
  format/mode, optional ICC fingerprint, and valid PNG sRGB declaration intent. It is a revalidation token, not a
  retained source file or raster cache. Source bytes are reread for each request.
- The child checks regular-file status, size, before/after fd identity, digest,
  expected metadata, and final path identity. Missing/replaced/changed originals
  are rejected. Final-component symlinks and nonregular inputs are not supported.
- In this slice only single-image JPEG/PNG/BMP/WebP decoded as 8-bit RGB/RGBA are
  accepted. GIF/TIFF, animated images, grayscale/indexed/CMYK/high-depth inputs,
  and RGB color-key transparency fail explicitly instead of being flattened or
  silently converted. This is narrower than the eventual product support target.
- Orientation is read after full decode (so trailing PNG EXIF can be available).
  Absent orientation is explicitly recorded as assumed 1; invalid values fail.
  Preparation fingerprints ICC bytes without certifying or converting them and
  records a valid PNG sRGB declaration (otherwise null). Render requests select
  `color_policy` and `assume_srgb`; defaults remain `legacy-v1` / false.
  `srgb-v1` runs the shared color core inside existing resource/deadline limits.
  This does not prove desktop preview/export color parity.

Private wire protocol **version 2** is separate from Imagescope's metadata/analysis
contracts: one bounded JSON request line on stdin, one bounded terminal JSON header
on stdout, followed by an exactly sized raw raster and optional ICC byte payload.
Both byte counts are validated before buffering; the profile payload is capped at
1 MiB and checked against its SHA-256. Converted ICC framing/size/RGB signature is
checked without running a profile parser in the parent. Semantics remain the
bounded, trusted producer's responsibility, not cryptographic proof of a transform.
Preparation/error results have no raster, profile, or color provenance. Request ID and generation must match;
preview/full status, dimensions, mode, source snapshot, lengths, and exit status
are validated before accepting the result. Duplicate JSON keys, nonfinite values,
unknown versions/fields, false color-conversion claims, extra/truncated bytes,
and excessive output are rejected. Raw bytes avoid another untrusted image decode
in the parent. Session-level scheduling/coalescing is still future UI work.

Limits: 64 MiB encoded input, 40MP stored/output geometry, 2048px maximum preview
side, 16 KiB request/header and stderr budgets, and 160,000,000 maximum raw raster
bytes, plus at most 1 MiB of ICC payload. Linux workers enforce 1.5 GiB address space, CPU seconds rounded up from
the request budget, disabled core dumps, 32 file descriptors, and parent-death
SIGKILL. Default preparation/render wall budgets are 30/60 seconds; neither may
exceed 60 seconds. The supervisor drains pipes nonblockingly, checks cancellation
at most every 50ms during polling, kills on timeout/cancel/failure, closes pipes,
and reaps the child. OS-level uninterruptible I/O can delay signal handling/reaping;
this is not a filesystem sandbox or a real-time kernel guarantee.

The parent also uses bounded raster buffers, but is not itself subject to the
child's address-space limit; converting the receive buffer to immutable bytes
can temporarily require another raster-sized allocation. Full rendering is
internal infrastructure, not an encoded export. `full_resolution_pixels()` refuses
preview results even when the preview happens to match the intended dimensions.
The future safe-publication exporter must not treat this as permission to write
or overwrite a destination.

## Color preparation foundation — S5

`image_lab_ui/edit_color.py` adds `prepare_color_pixels` and
`render_color_geometry` for already-decoded, isolated RGB/RGBA pixels. These are
worker-only building blocks, not UI-thread file readers or encoders. S6 connects
them to worker protocol v2. Every call must explicitly choose a policy:

- `legacy-v1`: independent unconverted pixels; profile bytes are retained but not
  parsed or treated as proof of sRGB. Output interpretation remains unmanaged.
- `srgb-v1`: embedded ICC takes priority over declarations and assumptions. Use
  relative-colorimetric intent, NOOPTIMIZE `0x0100`, no black-point compensation,
  generated sRGB destination, and separate unchanged alpha before any geometry.
  Conversion happens before EXIF orientation, crop, rotation/flips, and resize.
- A valid PNG sRGB declaration or explicit `assume_srgb=True` can identify untagged
  RGB/RGBA without a CMS transform. Unknown input otherwise fails. Invalid ICC
  cannot be overridden by a declaration or assumption, and CMS failures never fall
  back to unmanaged rendering. The assumption option itself is recorded separately
  from the actual converted/declared/assumed outcome.
- Mode support deliberately remains narrower than Imagescope's: no CMYK, LAB,
  grayscale/indexed, high-depth, animation, or RGB color-key expansion is added.
  Original encoded-depth/sequence eligibility remains the bounded decoder's job.
  Existing 40MP and 1 MiB profile limits apply to this foundation.

`ColorRenderedImage` retains the full-output/preview distinction and immutable
`ColorProvenance`: selected policy/assumption, actual interpretation, original
mode/profile digest, output color space, intent/BPC/optimization, ordering, and
Pillow/LittleCMS versions. Conversion replaces the source ICC with the destination
profile; stale EXIF/GPS/orientation metadata is not copied. Declared/assumed sRGB
carries an explicit output-color-space claim but does not invent profile bytes;
the eventual encoder must tag that output deliberately.

The shared function uses the existing geometry engine for both preview and full
output. It preserves original pixels and alpha, while retaining the existing
encoded-sRGB8/premultiplied resize convention—not a new linear-light resize policy.
Preview and full output can differ in resampling detail; previews remain forbidden
as full-resolution export sources.

Synthetic tests establish the linear-RGB transfer function within one 8-bit code
value, sRGB identity, alpha preservation, conversion-before-reduction order, failure
semantics, and public Imagescope whole-image measurement/provenance parity across
all eight EXIF orientations. This is not monitor-profile certification or a broad
vendor-profile guarantee.

## Managed worker transport — S6

`render_source(..., color_policy='srgb-v1', assume_srgb=False)` now invokes this core.
`prepare_source` remains color-neutral: successful preparation does not promise
that a subsequent managed render can interpret its source profile.

`WorkerImage.color` contains immutable validated provenance and `icc_profile`
contains separately validated opaque bytes (or null). Converted output carries the
generated destination ICC; legacy output preserves the original unparsed ICC;
declared/assumed sRGB carries no invented profile. Consumers must honor both the
output-color-space claim and profile, not infer interpretation from ICC absence.
The compatibility summaries are `color_conversion: converted|none` and
`color_interpretation: srgb|unmanaged`; a declaration/assumption is not conversion.

Validation binds policy/assumption to the request and mode/profile/declaration to
the source snapshot. It rejects unsupported intent, BPC/optimization/order, missing
runtime identities, inconsistent summaries, forged declarations, and malformed,
oversized, truncated, extra, or checksum-mismatched profile payloads. Existing
snapshot, request ID/generation, geometry, preview/full, exit, and resource checks
remain in place. V1 requests/results and old snapshot shapes are rejected; this
private protocol has no automatic migration. Recipe version 1 is unchanged.

**Remaining integration gate:** coordinate managed measurement jobs with the live
S9 editor and complete encoded-export acceptance. Current Measures remains legacy-v1
and is not shown as edited-image statistics. Encoded-copy tagging / alpha-matte behavior and safe export remain open;
passing the preview fixture gate does not complete end-to-end color acceptance or
authorize encoding a reduced preview.

## Tagged Qt preview and measurement alignment — S7

`edit_preview.EditorPreview` exposes a read-only URL and an `EditorImageProvider`.
Register the provider as `editor-preview` on the editor's QQml engine. The bridge
is not installed in the current viewer and is not itself a worker scheduler.
Call `begin`, `publish`, and `clear` on its owning Qt thread; submit blocking render
and inspection work outside that thread, using disposable processes for untrusted
source I/O. S7 tests use trusted synthetic files and an off-thread fixture runner.

A request binds source snapshot, complete immutable recipe, request ID, strictly
increasing generation, and policy/assumption. `WorkerImage.recipe` retains the
recipe actually submitted by the supervisor (no wire-version change). Publication
rejects stale, duplicate, cancelled, wrong-recipe, or wrong-policy results. Clearing
or superseding invalidates the old image URL and releases the provider's retained
frame; a unique URL per accepted generation avoids QML cache reuse.

`preview_qimage` accepts only bounded previews (maximum side 2048), detaches bytes,
uses explicit RGB888/RGBA8888 row strides, and preserves unassociated alpha. Known
sRGB output gets a named Qt sRGB tag, **not another ICC conversion**. Legacy output
remains untagged/unmanaged. Source ICC bytes are never parsed by Qt. The thread-safe
provider retains one frame and returns independent Qt handles; requested sizes
cannot trigger a larger decode or turn preview pixels into export input.

`inspect_measurements` / `validate_measurement_result` now accept explicit managed
options. Defaults and the live Measures adapter stay legacy-v1/preprocessing-v3.
The editor opt-in accepts whole-image measurements-v6 / preprocessing-v4 with the
specified transform settings, never ROI-v5 or histogram-v7 by implication.
`matching_original_measurements` checks path, source content digest, dimensions,
source profile, requested policy/assumption, actual interpretation, and matching
Pillow/LittleCMS settings/versions against the current frame. It rejects any
non-original recipe, including same-size flips, rather than labeling original
statistics as edited statistics.

This verifies **source-content and color-policy alignment**, not current filesystem
freshness, exact palette/display-pixel equality, or equal sampling resolution.
Source revalidation and asynchronous measurement-envelope scheduling remain session
responsibilities. Palette alpha weighting differs from white-composited luminance;
resampling and reduced measurements must retain their existing disclosures.

Acceptance evidence is bounded to Qt/PySide6 6.11.2, Pillow 12.3.0, offscreen software
Qt Quick: RGB/RGBA, all eight orientations, converted/declared/assumed tags, channel
order and row padding, alpha 0/128/255, and rendered white-composite channels within
two 8-bit code values. Async QML Image loading is tested through Image.Ready before
capture. This is not hardware-renderer, HDR, monitor-profile, or export certification.
No editor controls, automatic sRGB assumptions, or color-guided adjustments are
exposed by this slice.

## Asynchronous editor session — S8

`edit_session.EditorSession` owns recipe history and the S7 preview bridge. Its
commands and properties are Qt-thread-only. S8 established this programmatic layer;
S9 below installs it in the live application. No editor mutation IPC methods are exposed.

- Source preparation and rendering run on one supervisor thread, using the existing
  disposable bounded child. There is at most one active job and one latest pending
  job; superseding edits cancel the active job and replace the pending recipe.
- A 15ms Qt timer observes completed futures, consumes even stale results, and
  publishes only the current generation. Worker threads hold no QObject references
  and never emit into Qt. The timer stops when there is no work.
- Requests are pinned to the prepared source snapshot and immutable recipe/policy.
  Preparation, source reads, decode, and rendering remain off the Qt thread. Source
  changes fail without rebasing or discarding the user's draft.
- Numeric crop/aspect, clockwise rotation, flips, aspect-locked width/height resize,
  explicit upscale consent, undo/redo/reset, original comparison, refresh and cancel
  delegate to existing recipe/worker contracts. Commit once per gesture, not on every
  pointer movement. Invalid commands do not replace the valid draft or preview.
- Original comparison changes only the displayed recipe under the selected color
  policy, not history/dirty state. Geometry edits exit comparison. Policy selection
  is explicit and separate from geometry undo; geometry reset never silently changes
  the selected interpretation. Policy changes relative to opening remain dirty.
- Dirty close, source switching and shutdown require explicit discard **and the
  current `revision` token**. Missing/stale confirmation tokens are rejected. Tokens
  also stop an old dialog from closing a subsequently opened clean session. No
  action is automatically resumed merely because a guard emitted a prompt signal.
- `work_active` is an owner-supplied predicate for scan/submission/analysis activity;
  it rejects opening before any discard. `blocksExternalWork` stays true through
  closing. These are integration hooks, not proof that existing queue/IPC routes
  already enforce them.

`request_close(discard=True, revision=confirmed_revision)` returning true means
**accepted**, not necessarily quiescent. Observe `closed` (connect before requesting)
or confirm closed/not-busy before navigation, source mutations or final app exit.
Closing clears the preview and cancels work; `closed` waits for the supervisor to
finish and reap its child. A normal document close permits reuse; `shutdown` also
retires the executor permanently. Owners must keep the Qt event loop alive while
closing. QObject destruction has a Qt-free cancellation backstop, not a replacement
for the owner's dirty-close flow. Uninterruptible kernel I/O can still delay reaping.

Preview publication/allocation failures become error state without losing history;
refresh can retry. There is no exporter or fake mark-saved action. Drafts are session-
only, and no changes are written to source images, catalogs or settings by this layer.
S9 adds catalog-bound entry, application guards and numeric controls below. Managed
measurement jobs, drag gestures, and safe export remain future integration work.

## Live numeric geometry preview — S9

`Controller` owns the session for the application's lifetime and pins its entry to
an image ID and captured catalog path/name, independently of sidebar selection.
`GeometryEditor.qml` opens from the full-image viewer's **Edit image** button. The
engine registers the S7 image provider; live controls use S8 jobs, not UI-thread
decoding or a second renderer. Originals are never written by these controls.

- The editor is an exclusive modal mode. Entry requires no scan, submission, running
  analysis, or queued items (including paused queues). Existing inspections are
  cancelled and original-image display is suspended while the editor is visible.
- Controller guards reject conflicting imports, queue starts/resumes, catalog
  removal/rename/detail updates, settings changes, selection/filter/search changes,
  and source switching. The viewer independently refuses navigation while editing.
- IPC rejects non-read-only actions with `busy` while editing, except window show/
  focus. Status reports editor state, dirty state and pinned image ID. No remote
  discard or editor mutation API was introduced.
- Geometry fields use bounded ASCII integers, avoiding locale-grouping ambiguity.
  Enter or Apply commits one command. Only one crop/size form may be pending;
  other geometry commands are disabled until Apply/Revert. Background preview
  completion does not overwrite pending input. There are no drag handles yet.
- Color entry is explicitly `srgb-v1` with no assumption. Untagged supported inputs
  need the visible sRGB checkbox; invalid ICC/mode input does not fall back silently.
  Reset affects geometry, not the interpretation choice.
- Back/Escape and window/normal Qt quit attempts use the same local discard flow.
  Un-applied fields also prompt. The dialog captures the session revision; stale
  replies retain the session and require a new review. Keep editing has no deferred
  side effect. Native field editing/undo is not replaced by global geometry shortcuts.
- Guards remain active through closing, including after history is cleared but a
  cancelled child is still being reaped. Only `closed` dismisses the editor. No old
  navigation or quit intent is replayed: close the application again after leaving
  the editor. Forced termination/crashes cannot preserve session-only drafts.

This is a **preview-only** UI with persistent export-unavailable disclosure. No
save/export action, managed edited-image statistics, color-guided adjustments, or
encoded-output color acceptance is implied. Numeric layout checks at 900×600 and
1280×820, DPR 1/2, are not acceptance of future drag mapping or hardware display color.

## Staged drag cropping — S10

`CropOverlay.qml` operates in Qt logical coordinates on `Image.paintedWidth/Height`,
centered on the fitted image. It never treats letterboxing as image pixels or
multiplies by DPR. Corner hit targets extend slightly outside the image; ordinary
letterbox presses are rejected. Draws, corner resizing and movement clamp to the
current displayed result. Arrow keys move one original-source pixel along the
currently displayed axes; Shift moves ten. Numeric fields remain the alternative
for exact bounds and very thin fit-to-window images.

Staging changes only normalized UI bounds, not the recipe, worker generation or
history. Apply submits four normalized edges with the revision captured on tool
entry. `EditorSession.cropView()` rejects comparison frames, missing/not-ready
frames and stale revisions. `EditRecipe.with_display_crop()` maps all four corners
through inverse resize/flips/quarter-turns into EXIF-oriented original coordinates,
rounds outward and clamps to the current crop. Arithmetic noise within 1e-7 source
pixels snaps to integer edges without collapsing a positive subpixel selection.
A changed crop clears explicit resize; an effective no-op preserves it.

An accepted crop is one history commit regardless of pointer moves. Cancel/Escape
leaves the recipe untouched. Viewport changes or lost grabs abort the in-progress
pointer gesture back to its starting selection. Back/quit guards also cover staged
selections; Keep editing preserves them. Other geometry/color commands are disabled
while the drag tool owns the preview. Stale selections cannot apply to newer frames.

This tool trims the current preview; it does not decode an uncropped auxiliary frame
or add zoom/pan. Expand previous crops with numeric bounds or Reset. Aspect presets
remain separate commands, not aspect-locked drag constraints. No new IPC endpoint,
measurement scheduling, export behavior or hardware color acceptance is introduced.

## Copy-publication primitive — S11

`export_publication.CopyPublication` is blocking, single-owner filesystem code for
an eventual supervisor job, **not an encoder or editor export endpoint**. It accepts
a prepared source snapshot, explicit PNG/JPEG/WebP filename/format, a live reservation
callback and cancellation callback. Extension/name validation is not encoded-format
verification. The caller must provide a bounded verifier, validate full-resolution
recipe/color provenance, and serialize catalog reservations through publication.
Source digest/decoding remains the isolated renderer's responsibility; this layer
checks source file identity, size and mtime/ctime before and after publication.

- Walk absolute destination directory components with `O_DIRECTORY | O_NOFOLLOW`;
  reject symlink components and parent traversal. Pin the opened directory by
  device/inode and recheck its path before/after commit.
- Stage in a private-mode anonymous `O_TMPFILE` inode, bounded to 192 MiB encoded
  bytes. No replaceable staging pathname exists. Normal failure, cancellation and
  process death before publication leave no staging names to clean up.
- Require a nonempty payload and `verify(readable_stream)` returning None, raising
  on invalid output. Detect verifier changes to size/link count/mtime/ctime. Sync
  the file, recheck source, directory and reservations, then check cancellation.
- Link the staged descriptor via `/proc/self/fd` with `linkat` symlink-following
  semantics into the pinned directory. The destination entry is created atomically
  without replacement. Existing files, hardlinks and even dangling symlinks win.
  No unsafe fallback uses ordinary overwrite rename, copy or existence checks alone.
- Linux and accepted local filesystem types (ext-family, Btrfs, XFS, tmpfs) are
  required; anonymous staging, proc descriptor access and atomic linking must work.
  Network/unknown filesystem types fail closed. Runtime evidence is Btrfs, not
  certification of every filesystem/mount/storage configuration.

Once the link commits, cancellation cannot roll it back. A racing cancellation may
lose to publication. `PublicationReceipt.published` is true even when the subsequent
directory sync fails, the original changes, or the path moves/disappears. Inspect
`directory_synced`, `path_confirmed` and warnings; do not claim that no copy exists
or delete a published copy to simulate rollback. Sync success is not a hardware
power-loss guarantee, and tmpfs is explicitly disclosed as memory-backed.

A positive inode link count after a reported link error proves publication and
returns a warned receipt. Indeterminate errors without that proof raise
`PublicationUncertain` with `published=None` and the proposed path: inspect before
retrying. Known pre-commit rejection/collision errors remain ordinary exceptions.

No session saved-state update, catalog import, encoding/color/alpha/metadata policy,
format decoder, timeout supervisor or Export UI is introduced by this primitive.
Filesystem I/O can block; never invoke it on the Qt thread. Callback synchronization
and process-level encoding/resource/cancellation integration remain future work
at the S11 boundary; S12 supplies those callers.

## Integrated export and managed inspection — S12

### Conventional interpretation for untagged editor inputs

The live editor requests `assume_untagged=True`. After bounded source inspection,
only untagged RGB/RGBA snapshots default to `srgb-v1` with `assume_srgb=True`.
The UI discloses this as a convention, not detected metadata, without a blocking
prompt. ICC profiles (including invalid profiles) and PNG sRGB declarations are
never overridden. Originals remain untouched; exported copies carry intentional
sRGB tags. This opening interpretation is the initial clean checkpoint. Users can
opt out, which blocks managed editing/export and shows a labelled bounded unmanaged
reference. Low-level worker and programmatic session defaults remain explicit and
unchanged unless this opening option is selected.

### Encoding and output interpretation

`export_encoding.encode_copy()` accepts a prepared source, exact immutable recipe,
explicit `srgb-v1` interpretation and validated PNG/JPEG/WEBP options. It cannot
accept a preview raster. `export_worker` runs full-source render, encode, format
verification and complete decode inside the existing sandbox: 40MP source/output,
1.5 GiB child address-space ceiling, 60s encoding deadline, bounded stderr/header
and at most 192 MiB encoded output. Parent transport verifies correlation and
SHA-256; source/recipe/mode/color provenance must match. Parent copies can duplicate
encoded memory. Resource exhaustion fails closed rather than reducing resolution.

PNG uses either the generated destination ICC or an intentional sRGB declaration.
JPEG/WebP carry a generated sRGB ICC even for assumed/declared inputs. These are tags
on prepared pixels, never a second conversion. Source EXIF/GPS/XMP/orientation is
not copied. PNG and lossless WebP are decoded and pixel-compared; alpha is compared
exactly for PNG/WebP, including lossy WebP. JPEG quality is 1–95, subsampling is off,
and RGBA requires an explicit `#RRGGBB` matte with encoded-sRGB8 compositing. This
is not linear-light matting or HDR export. PNG is always lossless; WebP has an
explicit lossless switch. The staging verifier binds bytes to child-verified output.

### Publication, saved state and import

`export_job` holds SQLite `BEGIN IMMEDIATE` through live reservation checks and
publication. It compares physical parent identities and conservatively matches
case/Unicode-normalized leaf names, including on case-sensitive filesystems, so
aliases cannot bypass missing-file reservations. Destination paths are absolute,
without parent traversal, symlink components or ambiguous double-root prefixes.
No-replace publication and uncertain/post-commit behavior remain the S11 contract.

`EditorSession` serializes export/import with preview/inspection work off Qt.
Mutations, source switches, comparison, close and shutdown are refused while the
export job is active. Cancellation requests are checked before publication; they
cannot undo a successful link. Filesystem I/O, SQLite lock waits or an already
started import may delay completion. Keep guards/event polling until reaping.
Never hide a published file merely because a late cancellation was requested.

Only a confirmed, directory-synced, warning-free export advances the recipe/color
checkpoint. Undo/redo compare against that exact checkpoint. Geometry reset does
not reset interpretation; there is no fake mark-saved or persistent draft. Import
failure is separate from successful export and does not make the saved recipe dirty.
Uncertain/warned publication does not advance the checkpoint or permit blind import.

Optional import is off by default. It verifies a no-follow descriptor's bounded
contents and identity, then uses ordinary catalog import with expected-identity
checks. Retry refuses altered copies; originals stay selected and filters stay put.
Copy records do not inherit predictions or notes. Only the JPEG thumbnail receives
a white matte; exported PNG/WebP alpha stays intact. Import errors never delete a
published copy, and there is no automatic switch to editing the new file.

### Revision-bound original measurements and controls

Inspection starts on demand through `requestMeasurements()`, then refreshes after
subsequent previews. One editor supervisor job runs at a time; preview/export cancel
or replace inspection. The bounded 35s outer worker calls the public whole-image
`inspect` API (30s provider budget, 1 MiB result). Completion must match the current
session generation, snapshot, recipe and frame; source stat/digest/profile and
managed preprocessing/runtime provenance are checked. Failures clear inspection
values without destroying the recipe or valid preview. Close cancels inspection.

`sourcePolicyAligned` validates original-source interpretation independently of
current geometry. `colorAgreement` is true only for an original-recipe frame that
also passes the existing original-preview validator. Edited frames still show
explicitly ORIGINAL-source values, never edited statistics. No source-freshness
watcher, identical sampling, monitor/HDR match, ROI or histogram is implied.
Existing viewer Measures remains `legacy-v1`; color-guided controls remain disabled.

`ExportDialog.qml` shows full output dimensions, destination/name/format, quality,
WebP mode, explicit JPEG-alpha consent and optional import. Its action footer stays
reachable at 900×600 and 1280×820. Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z operate on history
outside text inputs; Ctrl+Shift+S opens Export copy. Dialog Escape is isolated from
editor Escape. Numeric alternatives and accessible names remain available. Testing
covers keyboard behavior and software rendering at DPR 1/2, not a screen-reader
or hardware-display certification.

### Native window-close follow-through

The current UI supersedes the S9 two-request quit behavior: native window close
(including compositor close shortcuts) closes a clean session and then the window.
Dirty recipes and pending fields still require the revision-bound discard decision.
Keep editing, dialog rejection or choosing Export cancels the pending quit. Active
export/work shows a visible dialog: an accepted wait/close pauses the queue without
clearing jobs, stops scans cooperatively, and waits for worker completion. New queue
jobs are not started while closing; a completing submission is paused too. Export
receipts and remaining dirty state are resolved before closing. No force-kill or
filesystem rollback is used. IPC mutation/close guards remain unchanged.
