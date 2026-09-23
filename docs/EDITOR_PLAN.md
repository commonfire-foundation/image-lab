# Image Lab editing implementation plan

Status: recipe/history, in-memory geometry, and isolated snapshot/render workers
are implemented and tested. File info now consumes the accepted development
metadata-v1 handoff through Imagescope's public API. S12 completes the geometry
workbench, bounded safe-copy export/import, and managed original-image inspection.
Software/fixture color acceptance is recorded through S12/C12; hardware/monitor/HDR
certification and the overall release-hardening phase are not claimed.
Slice S4 also exposes existing Imagescope measurements read-only, with explicit
policy/sampling provenance. S5 verifies a shared editor color-preparation core
against public whole-image results. S6 carries policy/provenance/ICC through the
bounded worker. S7 verifies a tagged Qt preview bridge and original-measurement
alignment on synthetic fixtures. S8 adds the asynchronous programmatic session,
latest-only scheduling, geometry/history commands, original comparison, and revision-
bound dirty guards. S9 installs a live numeric geometry preview and exclusive
controller/IPC guards, including revision-bound discard and un-applied field safety.
S10 adds staged drag selection, corner resizing, movement/nudging, inverse crop
mapping and gesture checks. S11 adds the tested copy-publication primitive. S12
integrates full-resolution encoding/verification, explicit output tags and JPEG
matting, catalog reservation serialization, progress/cancellation, saved-revision
tracking, optional import/retry, Export controls and managed original measurements.
Keyboard/text-undo and accessible numeric alternatives are verified. S13 restores
full-suite acceptance (331 passing tests), completes the listed crop presets, improves
export guidance/errors, and verifies a fresh extracted wheel at both layouts/DPRs.
Stage 4 remains open for the unreproduced historical native crash and broader manual
acceptance. Percentage resize input is still missing; pixel resize is available.
Color-guided adjustments and later measurement capabilities stay disabled.

Progress/evidence: `docs/EDITOR_IMPLEMENTATION.md`; implemented geometry contract:
`docs/EDITOR_CONTRACT.md` (paths from the repository root).

Reference: `../imagescope/IMAGE_LAB_INTEGRATION_PLAN.md` (sibling checkout).
Local decision/evidence record: `docs/IMAGESCOPE_COORDINATION.md` from the repository
root, including pending handoff gates and the referenced plan digest.

## Goal

Turn the full-image viewer into a lightweight image-preparation workbench:
**crop → rotate/flip → resize → export a copy**. Keep originals untouched, make
changes reversible during the session, and keep measured file facts separate
from generated library notes.

Imagescope is being developed separately. This plan defines Image Lab's side of
that integration, not authorization to change Imagescope or its release plan.

## Scope and product decisions

### First release

- An explicit **Edit image** action in the full-image viewer.
- Freeform crop and original, 1:1, 4:3, 3:2, 16:9, 9:16, and 21:9 presets.
- Quarter-turn rotation and horizontal/vertical flips.
- Aspect-locked resize with pixel dimensions and percentage input.
- Undo, redo, reset, and a hold-to-compare original preview.
- Export a new PNG, JPEG, or WebP file; never overwrite an existing path.
- Optional **Add exported copy to library**, off by default.
- Explicit source-change, unsupported-input, cancellation, and export errors.

The first release edits supported single-frame 8-bit still images. Animated GIF,
animated WebP, multipage TIFF, high-bit-depth/HDR inputs, and unsupported color
modes remain viewable but read-only, with a reason. Do not silently flatten an
animation, discard TIFF pages, or reduce high-bit-depth content. Unknown frame/page
counts or source precision do not establish edit eligibility: obtain a bounded
positive capability check or keep editing disabled with an explanation.

Editing does not require Ollama or generated tags. Metadata/description editing
continues to mean the existing Library notes workflow, not pixel editing.

### Later, independently shippable work

1. Brightness, contrast, and saturation with neutral defaults and comparison.
2. Palette swatches, color picking, and copyable color values.
3. Region measurements and before/after histograms through Imagescope.
4. Persisted recipes, export presets, and derived-image lineage if real usage
   justifies them; no new catalog schema is required for the first release.

No layers, painting, AI fill, object removal, RAW development, batch editing,
full animation editing, or automatic wallpaper installation in this plan.

## Current integration points

| Existing file | Responsibility / planned integration |
| --- | --- |
| `image_lab_ui/ImageViewer.qml` | Fit-to-window viewer, File info / Library notes tabs, GIF playback; add explicit editing mode without disturbing ordinary viewing. |
| `image_lab_ui/Main.qml` | Dialogs, actions, viewer ownership, close guard; route dirty-editor transitions through a shared guard. |
| `image_lab_ui/app.py` | Controller, selection, work scheduling, catalog access; expose an editor service rather than placing image transforms in Controller. |
| `image_lab_ui/image_services.py` | Public metadata-v1 validation and presentation; the local Pillow reader has been retired after real-provider tests. |
| `image_lab_ui/metadata_process.py`, `image_lab_ui/viewer_metadata.py` | Cancelable off-UI-process inspection, source/load revision checks, explicit errors and warnings. |
| `image_lab_ui/catalog.py` | Import finished exports as new records only when requested. |
| `image_lab_ui/renaming.py` | Atomic no-replace publication primitive; filename validation is rename-specific and cannot be reused unchanged for format conversion. |
| `image_lab_ui/ipc_actions.py` | Existing remote viewer/navigation/mutation operations must respect editing guards. |
| `tests/test_viewer.py`, `tests/test_desktop.py` | Interaction and lifecycle coverage to extend. |

### Baseline verification requirement

Before implementing, rerun the existing tests and preserve their logs. Recent
verification found one failure in
`test_open_close_preserves_scrolled_gallery_and_batch_selection`: the simulated
double-click did not open a scrolled tile. The broader desktop suite also had
failures outside the About/removal work. Reproduce and classify these before
claiming a clean editor baseline; do not weaken assertions to get a green run.

## Ownership and Imagescope boundary

**Image Lab owns:** recipes, gestures, undo/redo, preview orchestration, full-size
rendering, output encoding, destination consent, file publication, and catalog
insertion.

**Imagescope owns:** supported public metadata/measurement APIs, deterministic
analysis, coordinate/provenance definitions, and its documented color policy.

`image_services.py` now adapts public file metadata; future measurement integration
must retain explicit capability and version checks. UI code must not depend on Imagescope internal modules
or raw version-specific result dictionaries. Unsupported optional capabilities
produce an unavailable state, not invented measurements or a silent API fallback.

- Consume the public `MetadataRequest` / `inspect_metadata()` API and
  `imagescope metadata` CLI contract; its metadata version is separate from the
  existing analysis protocol. Stage 0a performs this integration before editor UI
  delivery, not as a later enhancement. The Python API is the preferred adapter
  entry point; verify CLI/API parity in contract tests.
- The temporary reader was retired in S3 after metadata-v1 acceptance. Do not
  silently fall back on unsupported schemas or runtime errors. DPI and nested
  EXIF fields are explicitly unavailable, not re-read by a second parser.
  Retain bounded structured warnings and distinguish
  present, absent, unknown, and unsupported values. In particular, null animation
  counts, transparency capability, and ICC status must not become zero/false/none.
- Metadata parsing must remain isolated and resource-limited, without raster
  loading, thumbnail generation, inference, or frame traversal for exact counts.
- Reuse existing palette/luminance/transparency measurements rather than writing
  duplicate algorithms in Image Lab.
- Adopt Imagescope's planned ROI contract: half-open integer bounds in EXIF-oriented
  original pixels; crop before reduction. Specify shared preview mapping/rounding
  using all eight orientations and edge/one-pixel fixtures. Sampled visible bounds
  are approximate; never scale them into purported exact source-alpha bounds.
- Align preview, measurement, and export color policies before editor delivery.
  Distinguish legacy behavior, converted sRGB, declared sRGB, explicitly assumed
  sRGB, and unknown/invalid/unsupported sources. Record policy/version and CMS
  provenance, including intent, black-point compensation, alpha handling, and
  conversion order relative to reduction. Never relabel unmanaged RGB as verified
  sRGB or silently recompute older measurements with different semantics.
- Key measurement responses by source digest, session/edit revision, region,
  options, and policy/version. Reject stale responses and show working dimensions
  and sampling uncertainty; unedited-source measurements are not edited previews.
  Before/after histogram comparisons require matching policies/settings, and
  endpoint occupancy must not be presented as proof of lost detail.
- Capability discovery must remain local and bounded; no implicit downloads,
  installations, network services, or model calls.
- **Do not export from Imagescope's analysis image.** Its reduced working raster
  is not a full-resolution editing source.

Development of pure geometry can proceed against fixtures while Imagescope is
working. Coordinated delivery follows metadata acceptance → explicit color-policy
acceptance → Image Lab integration/basic editing. Region inspection and histograms
are not first-release blockers. Color-guided adjustments require the same accepted
policy across preview, measurements, and export.

## Editor architecture

Proposed modules (names may change during implementation):

- `edit_recipe.py`: immutable, versioned recipe values, validation, geometry,
  output-size calculations, undo/redo history. No Qt or disk writes.
- `editor.py`: Qt-facing editor session, guarded transitions, command routing,
  dirty/export state, and latest-preview generation handling.
- `edit_render.py`: shared deterministic transform functions used by preview and
  export; EXIF normalization occurs once, before recipe geometry.
- `edit_worker.py`: bounded subprocess entry point for source decode, preview,
  and full-size export; no catalog connection or arbitrary commands.
- `exporting.py`: destination validation, staging, atomic no-replace publication,
  structured outcome, and application-side post-export import coordination.
- `image_services.py`: public Imagescope capability/result adapter.
- `ImageEditor.qml`, `CropOverlay.qml`, `ExportDialog.qml`: contained UI components
  integrated into the existing viewer.

### Source identity and recipe

Opening an edit session snapshots catalog ID, canonical path, device/inode,
size/mtime, oriented source dimensions, and a content digest computed off the UI
thread. The session remains attached to that source, not the current sidebar
selection. Revalidate the source at export; reject replaced or changed originals.

Use integer, half-open crop bounds `[left, top, right, bottom]` in the
EXIF-normalized original pixel space. Keep the complete rectangle in full-source
coordinates; preview rounding must never rewrite it.

Canonical render order:

1. Normalize embedded orientation and apply source color handling in the order
   specified by the accepted color policy; conversion-before-reduction rules must
   hold for both preview and export, not just the final encoded file.
2. Crop in normalized original coordinates.
3. Apply quarter-turn rotation and flips in a documented fixed order.
4. Resize to the validated target dimensions.
5. Apply explicit output alpha/matte handling and encode with the matching profile.

Freeze the full color/alpha operation order at stage 0a, including where any JPEG
matte is applied, and use that same order for preview/measurement comparisons.

Dragging a crop after rotation maps through the inverse view transform into
source coordinates. Derive this mapping centrally and test every rotation/flip
combination. Do not store screen coordinates as the recipe.

- Pointer-to-image mapping includes fit scale, letterboxing, and device-pixel ratio.
- Crop changes reset resize dimensions to the new natural result; an explicit
  rotation swaps the target axes as appropriate. Avoid surprising implicit stretch.
- Ratio constraints apply to the displayed result, including portrait rotation.
- Recipes reject nonfinite values, empty/out-of-bounds crops, invalid rotations,
  and invalid or over-budget output sizes before dispatching a worker.
- Upscaling is off by default; require an explicit toggle and label that it does
  not create additional image detail.
- An entire drag or slider gesture is one undo step. Cap history at 100 recipes;
  keep no full-size raster history. New changes after undo discard the redo branch.

### Preview and process lifecycle

Render a bounded preview (initial maximum: 2048px longest side) using the same
recipe semantics as export. During crop dragging, use the overlay; request the
rendered result on commit rather than decoding for every pointer movement.

Use one editor worker at a time and coalesce pending preview requests. Each
response carries session and recipe generation IDs; late results cannot replace
newer previews or another image's session. Reuse bounded immutable source data
within a session where safe; do not retain decoded originals in QML.

Full-size decoding/encoding must run outside the UI process, with enforced wall
time, memory, input/output-size, and pixel budgets. Start with a conservative
40MP source/output ceiling, 64MiB encoded input ceiling, 1.5GiB worker address-space
budget, and 60s export deadline; benchmark representative formats and adjust the
published limits before release. A pixel ceiling does not guarantee every file
under it fits memory. Fail with a specific error rather than falling back to an
unbounded decode. Keep preview and export jobs cancelable; terminate and reap
workers and clean only their owned temporary files.

As a first-release scheduling policy, viewing remains available during analysis,
but opening an edit session waits for scan/submission/analysis work to finish.
Do not start new scan/analysis work while editing/exporting. Preserve a paused
queue without deleting or silently resuming it. Editing exits restore normal
scheduling; resuming a paused queue remains explicit.

### State and navigation

States: `viewing → preparing → editing → exporting → editing`, with recoverable
errors returning to editing. Export success records the exported recipe revision;
later changes become dirty again. Exporting a copy never silently switches the
source being edited.

A shared transition guard covers Back, Escape, viewer switching, application
close, source rename/removal, and IPC-driven equivalents:

- Dirty session: **Keep editing / Discard changes / Export a copy**.
- Export active: wait or explicitly cancel; never abandon a running encoder.
- IPC requests that would discard work return a structured conflict rather than
  silently dismissing the editor or opening an unattended confirmation.
- Unrelated selection changes do not change the editing source.
- Clean session: normal close/navigation behavior.
- Closing a session releases its preview and worker resources.

No persisted draft recovery in the first release. Explain that discarded or
unexported session edits are not saved, including after an application crash.

## Export safety and output policy

1. Choose destination folder and filename; suggest `<stem>-edited.<extension>`.
   Display final dimensions, format, and alpha/color policy before export.
2. Validate the name for export rather than preserving the source extension.
   Reject source aliases, existing files, symlinks, hardlinks to the original,
   and paths reserved by catalog records, including missing originals.
3. Use a uniquely owned temporary file in the destination directory; pin/recheck
   destination-directory identity to handle path/symlink changes during export.
4. Render from a stable original snapshot, encode explicitly selected format,
   and verify the staged output's dimensions/format before publication.
5. Flush the output and publish atomically with no replacement; an existence check
   alone is insufficient. S11 uses Linux `O_TMPFILE` and descriptor-based `linkat`
   publication rather than a replaceable staging pathname. There is no unsafe
   rename/copy fallback when the required operations are unavailable. On a collision, keep editing and offer a new name—never auto-overwrite.
6. Sync publication as appropriate for the supported filesystem. Report uncertain
   durability honestly if a failure occurs after publication; do not claim that
   no output exists when it does.
7. Optionally import the completed copy through normal catalog code after worker
   completion, without resetting search/filter or changing the selected original.
   Never copy AI tags/edits automatically onto changed pixels.
8. Import failure after a successful export is a partial success: keep the file,
   show its path, and allow retrying import. Never delete the exported copy to
   simulate a transaction spanning SQLite and the filesystem.

Default export metadata policy: strip EXIF/XMP/GPS, normalize orientation, and
explicitly preserve/encode the appropriate ICC profile. Never copy stale
orientation/dimensions into the output. Tell the user metadata is stripped;
preserving attribution fields selectively can follow later.

For geometry-only editing, preserve a compatible embedded RGB profile and label
untagged RGB as unknown. Block unsupported color conversions instead of silently
assigning sRGB. If a verified conversion-to-sRGB path is available, make that
policy explicit and cover it with fixtures. Do not wait for Imagescope to own
image encoding; Image Lab remains responsible for output correctness.

PNG preserves alpha. WebP offers lossless or quality-controlled lossy export.
JPEG requires an explicit matte color when the source has transparency. PNG has
no fake "quality" slider. Exact output byte size is shown after encoding; do not
advertise an estimate as a guarantee.

## Delivery sequence and acceptance gates

### 0. Establish baseline and contracts

- Reproduce existing test failures and record unrelated issues separately.
- Specify recipe JSON/version, source identity, transform order, service adapter,
  structured errors, resource budgets, and color/alpha behavior.
- Add asymmetric orientation/crop, transparency, ICC, and unsupported-input fixtures.

**Gate:** deterministic geometry expectations and module boundaries reviewed;
no production-file mutations or new Imagescope dependencies required.

### 0a. Accept Imagescope metadata and color-policy handoffs

Current status: metadata integration accepted against C3; C12 records software-only
RGB/RGBA sRGB preview/original-measurement/encoded-output acceptance. This is bounded
fixture and packaged-app evidence, not monitor/HDR/vendor-profile certification.
No additional modes, ROI/histogram versions or color-guided adjustments are accepted.

- Re-read the sibling integration plan and its public contract at handoff; update
  `docs/IMAGESCOPE_COORDINATION.md` with actual revision/version and test evidence.
- Accept Imagescope phase 1: supported public API/CLI, metadata schema/version,
  warning/unknown semantics, bounded parsing, and backend fixture evidence.
- Implement the metadata adapter and migrate File info. Test unknown fields,
  unsupported versions, missing provider, malformed input, and stale responses;
  verify no raster decoding and no UI-thread blocking. Retire the temporary
  provider only after real-provider contract tests pass.
- Accept phase 2: named legacy and opt-in conversion policies, supported modes,
  invalid/missing profiles/CMS behavior, and provenance. Align Image Lab preview,
  measurement, and export behavior using shared synthetic color fixtures.
- Record the source/edit revision and measurement-cache key contract. Inventory
  existing measurements for reuse; their extra UI controls remain optional.

**Gate:** metadata integration and color-policy agreement have recorded acceptance
on Image Lab's side. In-progress files or an exported API name alone are not
acceptance. If the backend is unavailable, pure recipe/worker work may continue
with fixtures, but do not mark this gate complete or ship a substitute silently.

### 1. Recipe and render core

- Implement pure recipe validation, dimensions, inverse coordinate transforms,
  undo/redo/reset, and shared crop/rotate/flip/resize operations.
- Implement bounded worker decode/render and source-snapshot checks.
- Prove preview/export geometry matches before building gestures.

**Gate:** all EXIF orientations and rotation/flip combinations tested; corrupt,
oversized, changed-source, and unsupported inputs fail safely. Original hashes
and mtimes remain unchanged.

### 2. Editor UI and lifecycle

S8 delivers the programmatic session and preparation/render job lifecycle. S9 adds
live numeric controls, catalog-ID/path-pinned entry, exclusive queue/catalog/settings/
selection/IPC guards, and revision-bound discard. Un-applied field values are guarded
as well. Closing waits for child reaping; no deferred navigation/quit action is
replayed. Finish or clear queued work (including paused queued items) before entry.

S10 adds staged draw/move/corner-resize overlays over the current edited preview,
with inverse rotation/flip/resize mapping and one Apply/undo step. Numeric bounds
or Reset expand prior crops; the drag tool trims only the visible current result.
Logical-coordinate and pointer checks cover the two target layouts, DPR 1/2,
rotated/flipped and EXIF-oriented sources, and extreme aspect ratios. Gesture
cancellation and revision rejection preserve drafts. S12 adds managed original-source
measurement scheduling, scoped disclosure, export lifecycle, named keyboard controls,
text-field undo isolation and bounded dialogs. Screen-reader and hardware-display
certification remain outside the recorded automated/software acceptance.

- Add Edit image, crop overlay/handles, presets, numeric crop/size controls,
  rotation/flips, aspect-locked resize, undo/redo/reset, and original comparison.
- Provide numeric alternatives to dragging, visible focus, accessible labels,
  usable keyboard shortcuts, and no interference with text-field editing.
- Add session state, preview-generation handling, queue guards, and dirty-close
  handling across UI and existing IPC operations.

**Gate:** correct crop mapping at 900×600 and 1280×820, multiple device-pixel
ratios, portrait/landscape images, and extreme aspect ratios. Missing files,
rapid recipe changes, Escape, switching images, and pending worker completion
cannot lose a draft or apply stale results.

### 3. Safe copy export

S11 delivers the filesystem publication foundation: Linux anonymous staging,
pinned directory descriptors, source-identity and catalog-reservation callbacks,
atomic no-replace linking, cancellation boundaries and partial/uncertain receipts.
S12 installs the bounded encoder/verifier, full-resolution recipe/color binding,
SQLite reservation transaction, export lifecycle, format/destination controls and
optional import/retry. PNG/lossless-WebP pixel identity, lossy/JPEG-alpha behavior,
metadata stripping and output color tags have recorded acceptance. Current actual
publication evidence is Btrfs; missing required filesystem operations fail closed.

- Add format/destination controls, alpha options, explicit upscale consent,
  progress/cancel, and optional import.
- Implement staged full-resolution encoding and atomic no-replace publication.
- Cover filename collisions and post-publication/import failure separately.

**Gate:** output has expected full-source-derived dimensions and content; originals
are byte-identical. Tests cover symlinks, hardlinks, changed directories/sources,
disk-full/permission failures, crash/cancel cleanup, unsupported formats, and
catalog import failure. Unsupported filesystem guarantees fail closed.

### 4. Release hardening and documentation

- Exercise editing with paused queues and IPC navigation/close/removal requests.
- Run focused tests plus the full existing suite; classify remaining baseline
  failures explicitly and permit no unexplained new regressions.
- Verify an installed wheel includes new QML and worker modules and can edit/export
  from an isolated extracted wheel without source imports, using disposable local
  source/catalog/output directories.
- Document formats, limits, metadata stripping, color policy, keyboard controls,
  session-only undo, and originals/export semantics. Capture UI screenshots.

**Gate:** first-release acceptance checklist below is satisfied.

### 5. Optional measurement tools and adjustments

- Metadata integration is already completed in stage 0a; this stage must not defer it.
- S4 now surfaces existing palette/luminance/transparency readouts through the
  analysis adapter, with source/load rejection and sampling/color-policy disclosures.
  Other regional/similarity displays remain optional; do not rebuild their algorithms.
- Add brightness/contrast/saturation only with documented working-space behavior,
  fixed transform order, unchanged neutral settings, and preview/export parity.
- Add crop-region inspection and histograms when the corresponding public
  capabilities and coordinate/color contracts are available.

**Gate:** real-provider and unavailable-provider tests pass. Missing optional
capabilities do not disable crop/resize/export or trigger inference unexpectedly.

Dependencies: **0 → 0a → 2 → 3 → 4**, with **0 → 1 → 2** in parallel while
backend work is pending. Stage 2 requires both 0a and 1; final render acceptance
also uses the agreed color fixtures. Stage 5 is separately deliverable. Its ROI
work consumes Imagescope phase 4; histogram work consumes phase 5 and does not
require ROI to ship. No Imagescope backend work is implemented by this plan.

## Test map and first-release acceptance

Proposed focused suites (metadata and initial measurement suites now implemented):

- `tests/test_measurement_services.py`, `tests/test_viewer_measurements.py`: existing
  measurement reuse, source/load rejection, unchanged originals, explicit policy
  and sampling provenance, transport failures, and the unresolved color-agreement gate.

- `tests/test_image_services.py`: public metadata/API version validation, explicit
  provider selection, unknown versus absent fields, structured warnings, color
  policy/provenance, source/edit revision keys, and unsupported capabilities.
- `tests/test_edit_recipe.py`: bounds, ratios, orientation mappings, round trips,
  undo/redo/reset, invalid values, and exact output-size rules.
- `tests/test_edit_render.py`: shared transform correctness, alpha/color fixtures,
  EXIF applied once, preview/export parity, and no reduced-preview exports.
- `tests/test_edit_worker.py`: resource limits, cancellation, stale generations,
  source changes, process crashes, and cleanup.
- `tests/test_exporting.py`: no-overwrite publication, aliases/races, failures,
  metadata policy, full-resolution outputs, and original preservation.
- `tests/test_editor.py`: gestures/numeric controls, shortcuts, resizing, state
  transitions, queue guards, and confirmation behavior.
- Extend `tests/test_viewer.py`, `tests/test_desktop.py`, IPC tests, and Imagescope
  integration tests for the affected boundaries.

A release is ready when a user can open an unanalyzed still image, crop and rotate
it, resize it, undo/reset/compare, export a distinct full-resolution-derived copy,
and optionally import that copy—without changing the original or losing unrelated
library/queue state. Cancellation, failure, and missing optional backend features
must remain understandable and recoverable. Baseline failures are recorded, not
silently represented as successful verification.
