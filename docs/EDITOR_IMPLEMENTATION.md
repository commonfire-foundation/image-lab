# Editor implementation record

Latest: **S13 restores a green full suite and polishes the geometry workbench.**
S12 delivered full-resolution safe-copy export/import and managed original measurements.
The historical native crash remains unconfirmed, not fixed. Earlier slice descriptions
record their delivery-time scope, not the current feature set.

## Stabilization and geometry polish S13 — 2026-09-22

- Reproduced the baseline: 329 tests, 14 failures, 2 errors. The fake inference
  backends did not accept Imagescope's keyword-only `profile`, so successful queue,
  responsiveness and IPC scenarios failed before inference. Updated test/smoke
  backends with explicit wallpaper-profile checks, without loosening the production
  analyzer validator or changing Imagescope. Updated palette assertions to verify
  the provider's RGB/HSL additions, and the old status-message assertion to exercise
  the visible close dialog and Keep open action.
- Corrected desktop progress ordering to Image → Model → Tags → Save, matching the
  actual provider sequence. Tests now verify both stage numbers and labels.
- Added the planned original-ratio, square, 4:3, 3:2, 16:9, 9:16 and 21:9 crop
  presets. Added output dimensions and actionable export-disabled guidance for
  pending fields, drag selection, comparison and preview errors. Export validation
  now displays the specific controller error and retains the user's draft.
- **331 tests passed** in `results/stabilization-full-tests.log`; **24 live-editor
  tests passed** in `results/stabilization-editor-tests.log`. No model/network service
  was required. The full run still emits the shutdown warning described below.
- Fresh wheel: `results/stabilization-package/wheel/image_lab-0.1.0-py3-none-any.whl`.
  Extracted-wheel smoke passed at 900×600 and 1280×820, DPR 1 and 2; twelve total
  PNG/JPEG/WebP exports/imports, 1400×2400 full-source outputs, matching lossless
  pixels, tagged output, stripped metadata, unchanged originals and zero QML warnings.
  Evidence and inspected captures: `results/stabilization-package/`.
- Historical crash investigation: five repetitions each of the previously interrupted
  desktop test, shared-queue lifecycle and editor close test passed (15 total) with
  faulthandler enabled: `results/stabilization-crash-probe.log`. No uncollectable
  objects after explicit deferred-delete processing/runtime GC in that probe.
  The old crash log contains no native stack; none of this proves the crash fixed.
- Narrowed the 54-object shutdown warning to import-time Qt property/class teardown:
  importing Controller alone reproduces it without creating a catalog, worker or
  window. A standalone QObject class with one decorated QVariantMap Property and
  **no Image Lab imports or instances** reproduces a one-object warning on this
  Python 3.14 / PySide6 6.11.2 runtime. Evidence: `results/stabilization-shutdown-*.log`
  and `results/stabilization-property-probe.log`. This is not evidence that the
  historical native crash shares that cause; no dependency workaround/install made.
- Pyright still reports Qt binding/property/model typing errors in `app.py`; no
  clean static-typecheck claim. Hardware/HDR and manual screen-reader acceptance
  remain open. Percentage resize input from the original plan is not exposed yet;
  current resize controls use pixels. Brightness/contrast/saturation, ROI/histograms
  and persisted drafts are still separate, unimplemented work.

No personal catalog or source image was modified, no release installed/published,
and no sibling-repository files were changed.

## Foundation slice S1 — 2026-09-20

Status: **recipe/history and in-memory geometry implemented and tested**.
This is not a complete stage 1, an accepted Imagescope handoff, or a usable editor
UI. No source-image changes, exported user files, or Imagescope modifications were
made. No dependencies were installed.

### Delivered

- `image_lab_ui/edit_recipe.py`: strict immutable version-1 recipes, 40MP dimension
  limits, half-open source crops, exact centered aspect presets, rotation/flips,
  aspect-locked resize, explicit upscaling, reversible coordinate transforms,
  letterboxed logical-coordinate mapping, and bounded undo/redo/reset history with
  explicit exported-recipe checkpoints.
- `image_lab_ui/edit_render.py`: shared in-memory crop/rotate/flip/resize pipeline,
  explicit EXIF orientation, source-dimension validation, premultiplied-alpha
  resize, independent output pixels, and a preview/full-output distinction that
  prevents an encoder from accepting a reduced preview accidentally.
- `tests/test_edit_recipe.py`, `tests/test_edit_render.py`: 24 synthetic tests.
- `docs/EDITOR_CONTRACT.md`: implemented geometry schema, rounding/coordinate rules,
  limits, history semantics, and boundaries that remain the worker's responsibility.

Neither module is imported by the running desktop. No Edit button or export
controls have been added. Color conversion is deliberately not guessed while the
backend handoff remains unaccepted.

### Baseline and verification evidence

All commands ran from the Image Lab repository using its existing `.venv`.

1. Before implementation:
   `.venv/bin/python -m unittest discover -s tests -v`
   — 148 tests, 15 failures and 3 errors.
   Evidence: `results/editor-baseline-tests.log`.
2. Focused foundation tests:
   `.venv/bin/python -m unittest discover -s tests -p 'test_edit_*.py' -v`
   — **24 passed**.
   Evidence: `results/editor-core-tests.log`.
3. `compileall` on both new modules — passed.
4. Initial full-suite rerun lost its Wayland connection before completion.
   Evidence: `results/editor-foundation-full-tests.log`.
   This incomplete log is not proof of resolved failures or a clean regression run.
5. Explicit offscreen full-suite rerun:
   `QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software QT_QPA_PLATFORMTHEME= .venv/bin/python -m unittest discover -s tests -v`
   — 172 tests, 14 failures and 3 errors (155 passed).
   Evidence: `results/editor-foundation-offscreen-tests.log`.

The shell had `QT_QPA_PLATFORM=wayland;xcb`; tests using `setdefault` did not override
it. Future automated UI runs should explicitly select offscreen/software rendering
and not depend on the running compositor. The initial baseline and final run are
therefore not identical environments; do not claim a fully controlled green delta.

LSP reported no diagnostics for `edit_recipe.py`, but retained an unresolved
relative-import diagnostic for `.edit_recipe` in `edit_render.py`. Runtime imports,
compile checks, and the focused tests succeed. No clean static-typecheck gate is
claimed for this slice.

### Existing failures classified, not silently repaired

Confirmed baseline issues:

- Fake analyzer backend rejects the newer `profile` keyword, directly reported in
  `test_success_and_progress`; several queue/analysis failures are consistent with
  this contract drift but require individual validation when repaired.
- Catalog import attempts to save the decoder's RGBA working image as JPEG,
  directly reported by `test_large_png_catalog_and_analyzer_agree`.
- Legacy prediction/measurement assertions disagree with current Imagescope
  output. The editable sibling is under active development; its current behavior
  must be checked before updating compatibility code or fixtures.
- IPC tests include failed operations and a subscriber timeout; these are not
  evidence of editor behavior because the editor core is not wired into the app.
- Details-editor height and scrolled-gallery opening failures in the initial run
  pass in the final offscreen run. They were not fixed or asserted away here.
- The final offscreen run has a theme/queue test failure not present in the initial
  baseline (`test_live_theme_switch_preserves_running_queue_and_view`). It passes
  when rerun alone offscreen. Treat this as unresolved suite-order/timing or backend
  instability, not as a clean regression gate or a demonstrated new editor defect.

### Imagescope readiness recheck

The sibling plan changed during this slice. Its latest reviewed version records
initial metadata implementation and a first color-policy implementation slice;
it explicitly leaves a valid CMYK numerical reference-profile fixture as a release
gate. It does not claim Image Lab integration complete.

Metadata documentation also reveals consumer requirements needing acceptance:
its timeout does not preempt a stalled filesystem read in the caller; bounded EXIF
is top-level only, with rational/nested fields represented as null plus warnings.
A direct swap would therefore not preserve all current local camera/exposure
fields. The adapter must display unsupported/unknown information truthfully and
own an appropriate request lifecycle rather than masking this difference.

See `docs/IMAGESCOPE_COORDINATION.md`, checkpoint C2, for the document digests and
pending handoff details. No Imagescope API invocation was accepted as a production
metadata provider during S1.

### Remaining work and stage status

- Stage 0: baseline recorded and a concrete geometry contract/fixtures delivered;
  source-snapshot, worker envelope, and final color/alpha contracts remain open.
- Stage 0a: public metadata/color docs reviewed; adapter implementation and real-
  provider acceptance tests still pending. No handoff gate marked complete.
- Stage 1: pure recipe/render work delivered; bounded worker, cancellation,
  resource failures, stable source snapshot/digest, and accepted color fixtures
  are still required before its complete gate can pass.
- Stages 2–4: UI/lifecycle, safe file export, and release acceptance not started.
- Stage 5: optional measurement UI/adjustments not started.

At the end of S1, the next independent implementation unit was the bounded
source-snapshot/render worker (implemented in S2 below). Metadata adapter acceptance
can proceed against a stable backend handoff; editor UI delivery must still wait
for both stage 0a and the complete render core.

## Worker slice S2 — 2026-09-21

Status: **isolated snapshot/decode/render pipeline implemented and tested**.
No desktop integration, color-policy acceptance, encoded export, or destination
publication is implied. This slice did not modify Imagescope or install dependencies.

### Delivered

- `image_lab_ui/edit_protocol.py`: private versioned request/result limits,
  immutable source snapshot identity, strict JSON, and structured worker errors.
- `image_lab_ui/edit_worker.py`: Linux resource-limited source reading, hashing,
  still-image eligibility/full decode, EXIF orientation, rendering, and final
  source identity recheck. Worker writes only its result pipe, never source or
  destination files.
- `image_lab_ui/edit_process.py`: off-UI-thread blocking supervisor API with
  nonblocking bounded pipes, deadline/cancel checks, child kill/reap/close cleanup,
  request/generation matching, and exact raw-raster validation. Filesystem reads
  happen in the child rather than in the supervising thread.
- `tests/test_edit_worker.py` and `tests/helpers/edit_worker_fault.py`: 17 tests,
  including controlled stalled/crashed/malformed/resource-limited workers.
- Updated `docs/EDITOR_CONTRACT.md` with actual protocol, limits, support subset,
  memory/lifecycle caveats, and pending color responsibilities.

### Verified behavior

- Source SHA-256, device/inode, size, mtime/ctime, dimensions, orientation, and ICC
  identity are captured and revalidated. Changed/replaced/missing sources fail;
  originals remain byte-identical and no temporary files are left behind.
- Eight EXIF orientations, RGB/RGBA alpha preservation, crop coordinates, bounded
  previews, and full original-resolution output beyond 2048 pixels are covered.
- Unknown/invalid result envelopes, wrong request IDs/generations, oversized or
  truncated raster data, unexpected preview/full status, and false color claims
  are rejected by the supervisor.
- Cancellation and wall timeout kill and reap a stalled child. CPU and memory
  limits are exercised in child fault fixtures; excessive stdout/stderr and crash
  paths are tested. Parent-death SIGKILL configuration is inspected in a child;
  this test does not simulate an actual parent crash.
- The accepted source subset is single-frame JPEG/PNG/BMP/WebP in RGB/RGBA, with
  explicit rejection of animation, GIF/TIFF, grayscale/indexed/CMYK/high-depth
  sources, and RGB color-key transparency. No silent flattening or conversion.
- Color output is explicitly unmanaged with no conversion; ICC fingerprints are
  identity data, not profile validation. Production color-policy acceptance is
  still required before exposing the renderer in the editor UI.

### Verification evidence

- `.venv/bin/python -m unittest discover -s tests -p 'test_edit_*.py' -v`
  — **41 passed** (24 foundation + 17 worker tests).
  Evidence: `results/editor-worker-tests.log`.
- Explicit offscreen/software `tests/test_viewer.py` regression run — **10 passed**.
  Evidence: `results/editor-worker-viewer-tests.log`.
- `compileall` of the three new worker modules — passed.
- LSP optional-stream/selector issues were corrected. The language server still
  reports unresolved sibling relative imports, as in S1, despite successful
  runtime imports/tests. No clean static-typecheck result is claimed.

The full application suite was not rerun for S2; its known S1 failures remain
unresolved. These modules are not yet imported by Controller/QML. The focused
viewer regression run is not a substitute for eventual full release verification.

### Remaining stage gates

- Stage 1 now includes source identity and bounded worker/lifecycle handling, but
  accepted color-policy fixtures and broader eligible-mode policy are still open.
- Stage 0a metadata-provider migration and real Imagescope acceptance tests remain
  pending; S2 neither changes nor bypasses that gate.
- UI session scheduling/coalescing, dirty-close/IPC guards, editing controls, and
  safe encoded-copy publication remain separate implementation slices.
- The worker currently rereads/redecodes per request. Session raster reuse can be
  added later only while preserving snapshot checks and resource limits.

Next coordinated slice: metadata adapter/provider acceptance and color-contract
integration against the current Imagescope handoff. Do not label a backend gate
accepted merely because a new symbol or document exists in its live worktree.

## Metadata slice S3 — 2026-09-21

Status: **File info migrated to the public Imagescope metadata-v1 API and accepted
against the current development provider.** This completes the metadata portion,
not the color-policy portion, of stage 0a. Imagescope remains read-only; Image Lab
still owns future editing, preview rendering, undo, and encoded-copy export.

### Delivered

- `image_lab_ui/image_services.py`: public request adapter, independent metadata-v1
  validation, bounded display data, source revision checks, and structured errors.
  It neither imports Pillow nor calls the analysis result validator.
- `image_lab_ui/metadata_process.py`: disposable Linux API bridge; source I/O stays
  outside Qt's UI thread, including filesystem reads not preempted by the provider.
- `image_lab_ui/viewer_metadata.py`: asynchronous QProcess supervision, a 15-second
  outer deadline, bounded stdout/stderr, generation/source-key checks, cancellation,
  teardown, and visible failures. Normal navigation does not wait for process exit.
  The private bridge allows a 16 KiB request, 1 MiB reply, and 16 KiB stderr; parsing
  retains Imagescope's own input/memory/CPU budgets. Uninterruptible kernel I/O can
  still delay process cleanup despite cancellation; no absolute reap bound is claimed.
- File info exposes stored/oriented size, mode, ICC identity/status, sequence data,
  source digest, truthful Unknown values, and structured warnings as plain text.
  Refresh starts a new load; same-path catalog revisions also refresh automatically.
  Generated Library notes and their saved corrections are unchanged.
- Retired `file_metadata.py` and its five superseded tests only after actual-provider
  adapter tests passed. There is no hidden local-parser fallback. DPI and nested
  camera/lens/exposure metadata are explicitly unavailable in metadata-v1; top-level
  omitted values stay unknown. ICC identification is not color conversion.

### Verification and remaining scope

- **13 adapter tests passed**: `results/metadata-adapter-tests.log`.
- **16 viewer/process tests passed**: `results/metadata-viewer-tests.log`.
- Full offscreen/software suite: **203 tests, 14 failures, 3 errors**; all 41 editor
  tests and all metadata/viewer tests passed. The failing test identity set is
  identical to S1's offscreen result; existing analyzer/queue/IPC integration and
  RGBA-thumbnail issues were not changed. `results/metadata-integration-full-tests.log`.
- Wheel built with `--no-isolation`; extracted-wheel API/process smoke passed from
  outside the source package directory, using the existing dependency environment.
  `results/metadata-wheel-build.log`, `results/metadata-wheel-smoke.log`.
  This was not a fresh-environment dependency installation or a published release.
- Compile checks passed. LSP still reports unresolved imports and the existing Qt
  QVariantMap property-stub mismatch; no clean static-typecheck gate is claimed.
- Offscreen 900×600 and 1280×900 screenshots checked for readable wrapping and
  scrollable facts: `results/imagescope-metadata-900.png` and
  `results/imagescope-metadata-1280.png`.

See coordination checkpoint C3 for provider/document fingerprints, accepted contract,
backend-supplied evidence, and limitations. No Imagescope files were changed, no
new dependency was installed, and no analysis/color semantics were altered. The
next editor gate is explicit preview/measurement/render/export color agreement;
metadata acceptance does not permit exporting the 2048px analysis raster or shipping
the still-unwired editor controls. ROI/histograms remain later optional work.

## Measurement slice S4 — 2026-09-21

Status: **existing read-only measurements integrated through the analysis adapter;
not completion of the phase or the color-agreement gate.** S3's 29 focused tests
and packaged-wheel smoke passed; its full suite was baseline-failing, not green.

### Delivered

- `analyzer_client.py`: public `AnalysisRequest` / `analyze` inspect path and
  source/version/policy validation, separate from metadata-v1 and unchanged queued
  description behavior. Only the observed legacy-v1 / preprocessing-v3 /
  measurements-v6 contract is accepted. No palette extraction was recreated.
- `measurement_services.py`: presentation of provider palette/luminance/transparency
  output, original-source stat checks, explicit unknowns, and visible provenance.
  The entire provider measurement/provenance result remains available; the UI
  exposes a read-only subset rather than rebuilding other measurement algorithms.
- `measurement_process.py`, `viewer_measurements.py`: shared bounded inspection
  transport, generation/source-revision rejection, 35-second outer deadline,
  cancellation, and explicit failures. The shared supervisor disconnects callback
  cycles before deferred Qt deletion after repeated-fault tests exposed a crash.
- `MeasurementsPanel.qml`, viewer/controller wiring: on-demand Measures tab,
  approximate palette shares, color/sampling limitations, refresh, and cancellation
  on navigation/close/source changes. Library notes are never overwritten by inspect.
- `records.py`: new saved analysis records retain public provenance and schema
  alongside legacy measurement fields. No migration guesses for older records.

### Evidence and boundaries

**41 focused tests passed** (prior 29 plus 12 new tests), and extracted-wheel smoke
passed for both metadata and measurement workers. QML packaging and 900×600 /
1280×900 layouts were checked. Compile checks pass; unresolved-import/static stub
issues remain, so no clean static-typecheck claim is made.

Full suite: **215 tests, 13 failures, 3 errors**, with no new failing identities.
The prior intermittent theme/queue failure passed this time, not because it was
repaired here. The full suite remains baseline-failing, **not green**.
Evidence: `results/measurement-focused-tests.log`, `results/measurement-full-tests.log`,
`results/measurement-wheel-build.log`, `results/measurement-wheel-smoke.log`, and
`results/measurements-900.png` / `results/measurements-1280.png`.

These are first-frame, unedited-source measurements, not measurements of edited
previews. No new ROI or histogram implementation, inference, automatic dependency
installation, Imagescope modification, or export was added. Preview/measurement
color agreement remains an explicit gate before color-guided adjustments; the
readouts never claim unmanaged colors match the viewer. See checkpoint C4 for the
actual provider snapshot and remaining cross-project acceptance.

## Editor color foundation S5 — 2026-09-21

Historical handoff; S6 below supersedes the worker-transport limitation.

Returned to the original crop/rotate/resize/export plan after the read-only
metadata and measurement integration slices. Status: **shared color-preparation
core implemented and fixture-verified; end-to-end color gate still open.**

### Delivered

- `image_lab_ui/edit_color.py`: explicit `legacy-v1` / `srgb-v1` preparation and
  one color-before-geometry entry point for preview/full output. RGB/RGBA only,
  unchanged source pixels/alpha, independent output, and immutable provenance.
- ICC conversion matches the observed backend policy: relative-colorimetric,
  NOOPTIMIZE, BPC disabled, before orientation/crop/reduction. Unknown, declared,
  assumed, converted, and unmanaged outcomes stay distinct. No invalid-profile
  fallback and no automatic assumption or mode expansion.
- Destination ICC replaces the source profile after conversion; source EXIF/GPS
  is removed from derived pixels. Declared/assumed sRGB instead records its output
  interpretation explicitly; encoding/tagging remains a future responsibility.
- `tests/test_edit_color.py`: 12 synthetic tests, including an independent linear
  transfer-function ramp, conversion-order counterexample, alpha, failures, all
  orientations, and public Imagescope measurement/provenance comparisons.

### Verification

- **53 editor tests passed** (existing 41 + 12 new color tests):
  `results/editor-color-regression-tests.log`.
- Full offscreen suite: **227 tests, 14 failures, 3 errors** — no new failing
  identities relative to the known baseline. The intermittent theme/queue failure
  returned; it was never claimed fixed. The full suite remains **not green**.
  `results/editor-color-full-tests.log`.
- Extracted-wheel color-pipeline smoke passed outside the source package directory;
  full/preview separation and original preservation were verified. No dependency
  installation. `results/editor-color-wheel-build.log`,
  `results/editor-color-wheel-smoke.log`.
- Compile checks passed. LSP reports unresolved relative imports, as before; no
  clean static-typecheck gate is claimed.

### What this does not unlock yet

The existing render worker protocol and desktop remain unchanged and unmanaged;
they do not yet call this new color core. The next integration unit must carry
selected policy/assumption, provenance, and destination profile through a versioned
worker response and editor session/Qt preview, and align measurement requests.
Then verify output tagging/matte behavior in the safe-copy encoder. Keep stage 0a /
end-to-end color acceptance and editor UI gated until that evidence exists.

No editing controls, user-image writes, live measurement policy changes, new ROI
integration, or Imagescope source changes were made. The backend has meanwhile implemented
ROI; that does not change the editor-first ordering or make ROI an MVP dependency.
See `docs/EDITOR_CONTRACT.md` and coordination checkpoint C5 for the actual contract
and accepted versus still-open evidence.

## Managed render worker S6 — 2026-09-21

Historical handoff; S7 below advances the Qt preview boundary.

Status: **selected color policy now runs inside the bounded editor worker and is
validated end-to-end through the supervisor. Qt preview/export agreement remains
open.** No desktop control or live measurement policy was changed.

### Delivered

- Private worker protocol v2: render policy/assumption, immutable color provenance,
  separate bounded ICC payload, and matching compatibility summaries. V1 messages
  and old snapshot shapes fail closed; recipe version 1 is unchanged.
- Source snapshots now bind valid PNG sRGB declaration intent as well as ICC hash,
  preventing a response from inventing a declaration to bypass an assumption.
- `render_source` defaults remain legacy/unmanaged; opt-in `srgb-v1` uses the shared
  core before geometry. Preparation remains color-neutral. Full source verification,
  RGB/RGBA eligibility, no-write behavior, budgets, cancellation and preview guards
  remain in force.
- `edit_color_transport.py` checks policy/request/source consistency, actual
  interpretation, intent/BPC/optimization/order, bounded runtime identifiers, and
  profile framing. ICC bytes travel after raw pixels, capped at 1 MiB with length
  and digest checks, never inside the 16 KiB JSON header. No parent-side profile
  parser, raster decode, or source I/O was added.
- `WorkerImage.color` and `icc_profile` preserve output interpretation for the next
  consumer. Converted output has a destination ICC; legacy preserves opaque source
  bytes; declared/assumed sRGB has no manufactured profile. Future encoders must
  honor the explicit color-space claim even when profile bytes are absent.

### Verification

- **61 editor tests passed** (53 previous + 8 new worker tests), including all eight
  EXIF orientations through the real subprocess, exact preview/full pixel parity
  with the color core, public Imagescope measurements, alpha, original preservation,
  source-profile changes, >2048px full output, and >16 KiB opaque ICC transport.
- Fault cases reject stale IDs/generations, old protocol versions, policy/assumption
  drift, forged declarations/provenance, wrong intent/order/BPC/optimization, missing
  profiles, over-budget profiles, wrong hashes/framing, and short/excess payloads.
  Managed timeout/cancel cases confirm child reaping; existing quota cases pass.
- Extracted-wheel **actual worker** smoke passed using
  `tools/smoke_editor_color_worker.py`, including profile transport, full-resolution
  versus preview handling, and unchanged source bytes/mtime. No dependencies installed.
- Full offscreen suite: **235 tests, 13 failures, 3 errors**, with no new failing
  identities versus S5. The intermittent theme/queue test passed this time; it was
  not repaired. The full suite remains **baseline-failing, not green**.
- LSP still reports unresolved relative imports; no clean static-typecheck claim.

Evidence: `results/editor-color-worker-regression-tests.log`,
`results/editor-color-worker-full-tests.log`,
`results/editor-color-worker-wheel-build.log`,
`results/editor-color-worker-wheel-smoke.log`.

### Next integration boundary

Build the editor session/latest-generation scheduling and connect a tagged Qt
preview to this worker result, then verify matching measurement requests. Keep
editing UI and color-guided controls gated while preview agreement is unaccepted.
Safe-copy encoding/tagging, JPEG matte decisions, atomic no-replace publication,
and optional catalog import remain separate unfinished work. This slice does not
complete stage 0a or the overall phase. No Imagescope source was modified.

## Qt preview / measurement alignment S7 — 2026-09-21

Historical handoff; S8 below adds programmatic session lifecycle/scheduling.

Status: **bounded tagged Qt preview bridge implemented and fixture-verified**.
This is an editor integration component, not delivery of editing controls or a
change to the current viewer. Encoded-export/end-to-end acceptance remains open.

### Delivered

- `edit_preview.py`: one-frame Qt Quick image provider and QObject bridge with
  unique URLs, owning-thread publication, strictly increasing generations, stale /
  duplicate / cancelled-result rejection, and source/recipe/policy binding.
- The supervisor now retains the submitted immutable recipe in `WorkerImage`.
  Same-sized flips cannot masquerade as original pixels when matching measurements.
  The worker wire protocol remains v2; source/render validation is unchanged.
- RGB888/RGBA8888 QImages use explicit row strides and detached storage. Managed
  pixels are tagged with named sRGB, never converted twice or given the source ICC.
  Legacy stays unmanaged. Full-resolution/oversized/malformed rasters are rejected.
- Managed inspection options on the existing public adapter, with strict v6/v4
  whole-image and transform validation. Legacy defaults/live Measures stay unchanged.
  Current-frame alignment checks source content/profile and policy/runtime identity;
  edited recipes and incompatible results are rejected. No palette algorithm added.

### Verification

- **69 editor tests passed**: previous 61 plus 8 preview/alignment tests. Coverage
  includes RGB row padding, RGBA channels, alpha, all EXIF orientations, detached
  handles, stale/duplicate/recipe/policy rejection, original-only measurements,
  and real asynchronous Qt Quick Image rendering on white within two channel levels.
- **Extracted-wheel Qt Quick smoke passed**, exercising real render subprocesses,
  managed public measurements, image-provider loading, and captured frame pixels.
  Script: `tools/smoke_editor_preview.py`. No dependencies installed.
- Runtime: Qt/PySide6 **6.11.2**, Pillow **12.3.0**, offscreen/software backend.
  Tests wait for Image.Ready using a bounded Qt event loop before capture; fixed
  sleeps alone are not used as evidence of asynchronous image readiness.
- Full offscreen suite: **243 tests, 14 failures, 3 errors**. No new failing
  identities against the established baseline. The intermittent theme/queue failure
  returned; it was not repaired. Full-suite status remains **not green**.
- Compile checks passed. LSP still reports unresolved relative imports; no clean
  static-typecheck gate is claimed.

Evidence: `results/editor-preview-tests.log`,
`results/editor-preview-regression-tests.log`, `results/editor-preview-full-tests.log`,
`results/editor-preview-wheel-build.log`, `results/editor-preview-wheel-smoke.log`,
`results/editor-preview-runtime.log`, `results/editor-preview-qt.png`.

### Remaining scope

Session/job scheduling and source freshness checks must connect this component to
actual editor controls. The test runner's trusted-file off-thread calls are not a
replacement for disposable-process lifecycle/cancellation in the application.
Current viewer/Measures behavior and its unmanaged disclosure remain unchanged.
Alignment means matching original content and interpretation, not identical sampled
palette versus composited screen pixels, and not statistics for an edited recipe.

Safe-copy encoding/tagging, alpha/matte handling, no-overwrite publication, optional
catalog import, and full-suite stabilization remain unfinished. Hardware/HDR/monitor
profile behavior is not certified by the software fixture gate. This slice neither
completes the phase nor enables color-guided adjustments. No Imagescope source changed.

## Editor session / lifecycle S8 — 2026-09-21

Status: **programmatic Qt editor session implemented and verified**. It uses the
existing preview bridge and bounded workers; it is not yet wired into the live
viewer, queue, IPC, or a new editing panel. This is not completion of stage 2.

### Delivered

- `edit_session.py`: one supervisor thread / one disposable child at a time, with
  one replaceable pending job, cancellation on supersession, and Qt-thread-only
  publication. Late preparation/render results cannot replace a newer request.
- Immutable source/recipe ownership, geometry history, numeric crop/aspect,
  clockwise rotation, flips, aspect-locked resize and explicit upscale consent.
  Undo/redo/reset use the existing bounded history; invalid commands retain the
  valid draft. Original comparison changes display only, not dirty/history state.
- Explicit policy changes remain separate from geometry undo/reset and contribute
  to dirty state. Unknown color input fails rather than triggering an assumption.
- Dirty close, navigation and shutdown require explicit discard plus a matching
  session revision. Late confirmations cannot discard a newer draft or close a
  subsequently opened clean session. No fake export/mark-saved action was added.
- Close/shutdown are nonblocking; completion waits for child reaping. A Qt-free
  destruction callback cancels orphaned work. Source changes and preview allocation /
  publication failures leave the draft intact. Refresh never silently rebases.
- Opening checks a supplied external-work predicate; `blocksExternalWork` stays
  true through closing. These hooks still require real application-route wiring.

### Verification

- **83 editor tests passed**: previous 69 plus 14 session tests. Tests cover real
  prepare/render jobs off the Qt thread, command/history semantics, dirty policy
  state, original comparison, latest-only coalescing, late results, invalid inputs,
  source changes, stale discard confirmations, owner-thread enforcement, guarded
  transitions, preview failures, and reusable versus terminal close.
- Real stalled-child tests verify cancellation/reaping while Qt remains responsive,
  including QObject destruction. No Qt callbacks run from the supervisor thread.
- **Extracted-wheel session smoke passed** via `tools/smoke_editor_session.py`:
  prepare → crop/rotate/resize → preview → comparison → dirty guard → shutdown,
  with original bytes/mtime unchanged and module imports from the extracted wheel.
- Full offscreen suite: **257 tests, 13 failures, 3 errors**, no new failing
  identities versus S7. The intermittent theme/queue test passed this time; it was
  not repaired. Full-suite status remains **baseline-failing, not green**.
- Compile checks passed. LSP still reports unresolved imports and Qt/type-stub
  diagnostics; no clean static-typecheck gate is claimed.

Evidence: `results/editor-session-tests.log`,
`results/editor-session-regression-tests.log`, `results/editor-session-full-tests.log`,
`results/editor-session-wheel-build.log`, `results/editor-session-wheel-smoke.log`.

### Remaining integration boundary

Install the session in the application and route all editor entry, selection,
close/quit, queue starts, catalog mutations and applicable IPC transitions through
its guards. Bind discard dialogs to the captured revision and wait for `closed`
before completing deferred actions. Add the actual accessible editing controls,
gestures/mapping tests, and managed measurement job coordination. These are not
already delivered just because the controller exposes commands.

Safe-copy encoding/tagging, alpha/matte rules, atomic no-replace publication,
optional import, and full-suite stabilization remain unfinished. Drafts are not
persisted. No user images, catalog/settings, or Imagescope source were modified by
this slice; no dependencies were installed and no release was published.

## Live numeric geometry preview S9 — 2026-09-21

Status: **live preview-only editor installed and verified**. Open the full-image
viewer and choose **Edit image**. Export is explicitly unavailable; this does not
complete stage 2, encoded-color acceptance, or the overall editor phase.

### Delivered

- `Controller` owns the S8 session, pins entry to catalog ID/path, registers the
  preview provider, and rejects entry during scan/submission/analysis or queued
  work, including paused queued items. Existing read-only inspections are cancelled
  on entry; they are not relabeled as edited-image measurements.
- `GeometryEditor.qml` provides numeric half-open original-coordinate crop, exact
  presets, clockwise rotation, flips, aspect-locked resize/upscale consent, bounded
  undo/redo/reset and original comparison. Controls reuse the existing theme, with
  visible scrollbars, native focus/field behavior and an explicit no-export banner.
- Numeric fields accept bounded ASCII integers; grouping/decimal inputs cannot be
  misinterpreted as different pixel values. Enter/Apply commits; pending values
  disable conflicting geometry commands until applied/reverted. Preview completion
  cannot erase un-applied input. No drag overlay was introduced.
- Untagged supported inputs require explicit sRGB consent in the UI. Invalid modes
  or profiles fail without automatic fallback. Reset does not change color intent.
- Escape/Back and normal window/Qt quit attempts preserve drafts and pending form
  values. Discard carries the captured revision; stale confirmation keeps the editor
  open. Guards remain active until child reaping completes. No pending quit or
  navigation action is replayed; close the window again after leaving the editor.
- Existing controller mutations and IPC transitions are guarded. Read-only IPC and
  window show/focus remain available; `app.status` exposes editor state/dirty/image
  ID. No remote discard or editor mutation endpoint was added.

### Verification

- **91 editor-focused tests passed**: previous 83 plus 8 live integration tests.
  Includes controller/IPC guards, queued-work rejection, actual QML controls, explicit
  color consent, numeric field retention/revert/Enter, locale-invalid input, revision-
  bound discard, normal quit protection, field bounds, and stalled-child reaping.
- **Extracted-wheel live UI smoke passed at DPR 1 and 2**, loading packaged Main.qml
  and worker code: pointer entry → numeric crop/rotate/resize → 300×500 preview →
  keyboard Escape → Keep editing/Discard → reaped close. Source bytes and mtime
  remain unchanged. No QML warnings were emitted.
- Layout captures at logical **900×600 and 1280×820** were inspected. A sidebar
  minimum-width overflow found during inspection was corrected and bounded by tests.
  These checks validate numeric controls, not future drag coordinate mapping.
- Final full suite: **265 tests, 13 failures, 3 errors**; no new failing identities
  versus the established S7/S8 baseline. An earlier run in this slice had 14 failures
  when the known theme/queue intermittent test failed; it passed on the final run
  and is not considered repaired. Full-suite status remains baseline-failing.
- Changed Python modules compile. LSP still reports import/Qt/type-stub diagnostics;
  no clean static-typecheck gate or hardware/monitor-color certification is claimed.

Evidence: `results/editor-live-tests.log`, `results/editor-live-regression-tests.log`,
`results/editor-live-full-tests.log`, `results/editor-live-wheel-build.log`,
`results/editor-live-wheel-smoke.log`; captures `results/editor-live-900.png`,
`results/editor-live-1280.png`, `results/editor-live-discard.png`, and DPR-2 captures
under `results/editor-live-dpr2/`. Reproducer: `tools/smoke_editor_live.py`.

### Remaining work

Drag crop overlay/handles and complete gesture mapping/accessibility tests; managed
measurement job alignment; full-resolution encoded-copy export, intentional color
and alpha/matte handling, metadata stripping, atomic no-replace publication and
optional import; baseline stabilization and release acceptance. No source image
writes, backend edits, dependency installation, or publication were performed.

## Staged drag crop S10 — 2026-09-21

Status: **drag selection, corner resize, move and keyboard nudge installed and
verified**, still preview-only. No export or new Imagescope capability is delivered.

`CropOverlay.qml` stages normalized bounds on the actual painted image. Letterbox
starts are rejected except extended corner hit targets. Selection stays inside the
current result; pointer moves do not render or change history. Arrow/Shift-arrow
move one/ten source pixels along displayed axes. Apply maps all corners back through
resize/flips/rotation into oriented original pixels, rounds outward, clears explicit
resize on a changed crop, and commits one undo step. Effective no-ops retain resize.

`EditorSession.cropView()` binds application to the tool-entry revision and rejects
stale/not-ready/comparison frames. Escape/Cancel leaves the recipe unchanged;
viewport changes or cancelled grabs restore the gesture's starting selection.
Back/quit includes staged selections in the existing discard guard. Other geometry
and color commands are disabled while the tool owns the preview. Numeric bounds or
Reset can expand a prior crop; this tool trims the current preview rather than
loading a second uncropped image. There is no zoom/pan or aspect-locked drag mode.

### Evidence

- **99 editor tests passed**, including four new pure mapping tests and four new
  live tests. Pure coverage includes all 16 quarter-turn/flip combinations with
  resize, outward rounding/no-ops/subpixel bounds, invalid inputs, logical fitting
  at both target viewport sizes and DPR 1/1.5/2, portrait/landscape and 100:1 ratios.
- Live pointer tests cover draw, corner resize and move through four transformed
  recipes, single-step undo, boundary clamps, letterbox rejection, exact keyboard
  nudges, Escape, stale/comparison rejection, EXIF orientation 6, pending-selection
  discard/Keep editing, resizing during a grab, and 4000×40 / 40×4000 sources.
- **Extracted-wheel Main.qml workflow passed at DPR 1 and 2**, each at logical
  900×600 and 1280×820: draw → staged unchanged recipe → Apply → exact mapped recipe
  → undo → original numeric recipe. Source bytes/mtime unchanged, zero QML warnings.
  Selection captures at 900×600/DPR 1 and 1280×820/DPR 2 were visually inspected.
- Full suite: **273 tests, 13 failures, 3 errors**, no new failing identities against
  the established baseline. Full-suite status remains baseline-failing, not green.
- Changed Python files compile. LSP still reports unresolved relative imports and
  Qt/type-stub diagnostics; no clean static-typecheck or hardware-color gate claimed.

Artifacts: `results/editor-drag-regression-tests.log`,
`results/editor-drag-full-tests.log`, `results/editor-drag-wheel-build.log`,
`results/editor-drag-wheel-smoke.log`; selection captures under
`results/editor-drag-dpr1/` and `results/editor-drag-dpr2/`.
Reproducer: `tools/smoke_editor_live.py OUTPUT_DIRECTORY --drag`, with the extracted
wheel on `PYTHONPATH` and offscreen/software Qt settings.

Managed measurement coordination, further accessibility review, full-resolution safe
copy export and encoded color/alpha/metadata acceptance remain open. No original
image writes, backend modifications, dependency installations or publication occurred.

## Copy-publication foundation S11 — 2026-09-21

Status: **filesystem publication primitive implemented and verified**, not an encoder
or a live Export action. This begins stage 3's safety foundation while managed editor
measurements and encoded-color acceptance remain open. It does not complete stage 3.

### Delivered

- `export_publication.py`: explicit format/extension and filename validation, bounded
  anonymous staging (192 MiB maximum encoded output), private permissions, immutable
  public destination/source properties and one-shot transaction ownership.
- Directory-descriptor traversal rejects symlink components and pins the destination
  directory by device/inode. Recheck source identity, directory identity and the
  caller's catalog-reservation callback before publication; missing catalog paths
  remain reserved. The eventual caller must serialize catalog access.
- Linux `O_TMPFILE` avoids any replaceable staging name. After a mandatory verifier
  callback and file sync, descriptor-based `linkat` atomically creates a destination
  without replacement. No unsafe fallback is used. Unknown/network filesystems or
  unavailable operations fail closed; current runtime evidence is on Btrfs.
- Pre-commit failure/cancellation closes anonymous staging. Directory sync failure,
  changed paths or changed originals after commit return explicit partial-success
  receipts and never trigger deletion. Ambiguous link failures raise
  `PublicationUncertain`, not a false claim that no publication happened. Racing
  cancellation can lose to commit. Directory sync is not hardware durability proof;
  memory-backed destinations carry an explicit warning.

### Verification

- **26 new publication tests passed**. Actual atomic linking and competing writers;
  existing regular/symlink/dangling-symlink/hardlink destinations; source and missing
  catalog reservations; directory swaps before/at commit; changed sources; staged
  validation and mutation rejection; cancellation before/after commit; output bounds;
  injected permission, partial-write/disk-full, fsync/close and indeterminate-link
  errors; unavailable facilities; process death with no staging names left behind.
- **125 focused editor/publication tests passed** (99 editor plus 26 publication).
- **Extracted-wheel smoke passed**, with real bounded source preparation and a tiny
  controlled PNG fixture, anonymous staging, publication, collision refusal, source
  bytes/mtime preservation and directory sync. This tests publication—not a product
  encoder, full export workflow or encoded-color acceptance.
- Complete serial full suite: **299 tests, 14 failures, 3 errors**. No new failing
  identities against the established baseline, including the known intermittent
  theme/queue test, which failed on this run. Full-suite status remains failing.
- An earlier concurrent full-suite attempt ended with a native segmentation fault
  during `test_completion_updates_only_changed_tile_with_and_without_search`, before
  the publication tests. That attempt is incomplete, not a passing gate. A serial
  retry with fault diagnostics completed; the native crash was not diagnosed/fixed.
- Changed Python files compile. No clean language-server/static-typecheck claim.

Evidence: `results/export-publication-tests.log`,
`results/export-publication-regression-tests.log`,
`results/export-publication-full-tests.log`,
`results/export-publication-full-tests-crashed.log`,
`results/export-publication-wheel-build.log`,
`results/export-publication-wheel-smoke.log`.
Reproducer: `tools/smoke_export_publication.py OUTPUT_DIRECTORY`, run from an
extracted wheel with that directory on `PYTHONPATH`.

### Still gated

A resource-bounded production encoder/verifier; full-resolution recipe/provenance
binding; deliberate ICC/sRGB tagging, alpha/JPEG matte and metadata stripping;
session export/cancel/saved-state lifecycle; actual catalog reservation serialization;
format/destination UI and optional import with partial-success reporting. Managed
editor measurements, remaining accessibility review and release stabilization also
remain open. No user image writes, backend edits, dependency installs or release
publication occurred. Only disposable local test fixtures were published as copies.

## Integrated export, inspection and keyboard controls S12 — 2026-09-21

Status: **the three requested remaining feature groups are delivered**: bounded
full-resolution encoding and output acceptance; live export/publication/import
workflow and controls; managed original measurements and keyboard/numeric access.
This does not declare the entire release phase complete or certify display hardware.

### Delivered

- `editor_payload.py`, `export_encoding.py`, `export_worker.py`: bounded cancellable
  full-source render/encode/decode verification, SHA-256 transport and provenance
  binding. PNG/JPEG/WebP, explicit sRGB tags/ICC, exact lossless/alpha checks,
  explicit JPEG matte, metadata stripping; never an Imagescope/preview export source.
- `export_job.py`: existing atomic publication under a real SQLite reservation
  transaction, physical-parent and conservative case/Unicode reservation matching,
  truthful committed/uncertain receipts and optional normal catalog import/retry.
- `edit_session.py`: serialized asynchronous export/import, progress/cancel, exact
  saved recipe/policy checkpoint, late-cancellation receipt handling and close/edit
  guards. Imports do not change the editing source or copy AI/user notes.
- `catalog.py`: expected-identity import checks and white-matted JPEG thumbnails for
  RGBA inputs. The actual PNG/WebP output and original alpha are not flattened.
  This export requirement also fixes the established large-RGBA catalog test error.
- `ExportDialog.qml`, `GeometryEditor.qml`, `app.py`: destination/name/format/quality,
  lossless WebP and explicit JPEG-alpha consent, optional import, retained-copy/retry
  outcomes, Ctrl+Shift+S export and recipe history keys that leave text undo alone.
  Dialog Escape does not accidentally close the editor. Footer actions fit both layouts.
- `editor_measurements.py`, `editor_measurement_worker.py`: managed public-API
  whole-source inspection with bounded envelopes, source/policy/runtime matching,
  generation rejection and preview/export priority. Original-only disclosure remains
  explicit for edited frames; the old viewer Measures policy is unchanged.
- `tests/test_export_encoding.py`, `test_export_session.py`,
  `test_editor_measurements.py`, and four additional live QML tests. Existing S11
  race/fault/publication tests remain active. No backend edits or dependency installs.

### Verification and acceptance

- **148 focused editor/export tests passed** in
  `results/editor-export-regression-tests.log` (including 6 encoding, 8 export-session,
  5 managed-measurement and 16 live-editor tests).
- Final serial offscreen/software suite: **322 tests, 14 failures, 2 errors** in
  `results/editor-export-full-tests.log`. No new failing identities versus the
  completed S11 run. The RGBA-thumbnail error now passes; the known intermittent
  theme/queue failure recurred in the final run (the prior run had 13 failures). Analyzer/queue/IPC compatibility
  failures remain. The earlier native desktop crash was not reproduced or fixed;
  shutdown also reports unattributed uncollectable objects; that warning is not
  claimed resolved.
- Extracted wheel: `results/editor-export-wheel/image_lab-0.1.0-py3-none-any.whl`;
  `results/editor-export-wheel-build.log`. No implicit install or source-package
  import was used. Reproducer: `tools/smoke_editor_export.py OUTPUT_DIRECTORY`, cwd
  and `PYTHONPATH` set to the extracted wheel. Both 900×600 and 1280×820 passed at
  DPR 1 and 2: six PNG/JPEG/WebP copies per run, optional library import, preserved
  original selection/filter, unchanged original bytes/mtime, zero QML warnings.
- Packaged outputs are **1400×2400**, exceeding preview's 2048px limit. Decoded PNG
  and lossless WebP match full-render RGBA pixels, including transparency. JPEG is
  explicitly matted and tagged. ICC and metadata stripping are verified. Linear-RGB
  analytic fixtures, declared/assumed sRGB, invalid profiles, EXIF orientations,
  geometry, cancellation, collision, reservations, import failure/retry and late
  commit/cancel behavior are covered by the focused tests.
- Final smoke logs: `results/editor-export-wheel-smoke-dpr1.log` and
  `results/editor-export-wheel-smoke-dpr2.log`. Captures: `results/editor-export-dpr1/`
  and `results/editor-export-dpr2/`. Inspected the 900px JPEG dialog and 1280px/DPR2
  managed measurement panel. The first unsuffixed smoke log is an incomplete
  scripted-click attempt; final scripts wait for layout/frame polish before clicks.
- Runtime: Pillow 12.3.0 / LittleCMS 2.19 / PySide6 6.11.2; actual publication on
  Btrfs. Acceptance is synthetic/software and encoded-output evidence, not all ICC
  profiles, display hardware/HDR, power-loss durability or all filesystem variants.
- LSP still reports unresolved package-relative imports; runtime/compile/test gates
  pass, but there is no clean static-typecheck claim.

### Still open

Release stabilization and remaining baseline failures/native-crash investigation;
manual screen-reader and hardware/display acceptance; optional adjustments, ROI and
histograms, all still disabled. Drafts are not persisted. Publication/import I/O can
delay cancellation and resource limits may reject a valid large input without a
fallback. No user image was written, release published, backend modified or new
dependency installed; all acceptance copies used disposable in-repository fixtures.
