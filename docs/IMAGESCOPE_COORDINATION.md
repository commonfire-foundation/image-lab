# Imagescope / Image Lab coordination record

Latest checkpoint: **C12 accepts scoped software/encoded-output color agreement
and delivers managed original measurements plus live safe-copy export/import.**
The full release-hardening phase, hardware/display certification and optional
adjustment/ROI/histogram integrations are not complete. Earlier checkpoints are historical.

## Coordination pass C1 — 2026-09-20

Status: **Image Lab plan aligned; backend handoffs pending acceptance.**

Purpose: correct the initial editor plan's missing reference to Imagescope's
active integration plan. The initial draft used README/protocol/source research
but had not read that plan. This pass records the actual cross-project reference
and changes Image Lab's implementation ordering accordingly.

Scope: documentation in Image Lab only. No Imagescope files, runtime settings,
package versions, release state, or project-roadmap lifecycle state were changed.
This is not evidence of reciprocal acknowledgment by an Imagescope implementer.

### Reference snapshot

Read-only reference: `../imagescope/IMAGE_LAB_INTEGRATION_PLAN.md`.

- Observed at: `2026-09-20T22:34:44-07:00`.
- Imagescope checkout HEAD (short): `3696cab`.
- Referenced plan SHA-256:
  `7f6f35047f4ec87c7d1390a18b754b84aa3a580192da89e01ecd84e6a461c7e6`.
- The integration plan was untracked at observation, so HEAD alone does not
  identify the plan contents. The digest identifies the document actually read.
- Observed work in progress: modified `imagescope/__init__.py`, `cli.py`,
  `decode_worker.py`, and `images.py`; untracked `imagescope/metadata.py`,
  `metadata_worker.py`, and `tests/test_metadata.py`.
- `metadata.py` contained `METADATA_VERSION = 1`, `MetadataRequest`, and
  `inspect_metadata`. These are observations of live work, not a frozen contract
  or proof that the implementation/tests are complete.

No Imagescope tests or release checks were run during this coordination pass.
Re-read the public contract and capture new evidence at handoff rather than
assuming this live snapshot is still current.

### Decisions recorded in `docs/EDITOR_PLAN.md`

1. **Early metadata integration:** add stage 0a, consuming the public
   `MetadataRequest` / `inspect_metadata()` API and `imagescope metadata` contract.
   Metadata migration is no longer deferred to the later-tools stage.
2. **Truthful metadata states:** preserve unknown, absent, unsupported, warnings,
   and nullable counts. Do not infer a single-frame/editable source from missing
   animation information. No silent fallback after provider migration.
3. **Explicit color gate:** accept the backend's versioned legacy/conversion
   policies and align preview, measurement, and export semantics before editor UI
   delivery. Include profile/mode support, intent, black-point compensation,
   alpha handling, conversion-before-reduction order, and CMS provenance.
4. **Coordinate agreement:** use half-open EXIF-oriented original-pixel rectangles,
   crop before reduction, and shared mapping/rounding fixtures. Reduced visible
   bounds are sampled—not exact original-alpha crop bounds.
5. **Revision/provenance agreement:** associate measurements with source digest,
   session/edit revision, ROI, options, and policy/version; discard stale results.
   Show sampling limitations and require comparable histogram settings.
6. **Delivery alignment:** backend metadata → explicit color policy → Image Lab
   integration/basic editing. Pure recipe/render development can proceed against
   fixtures meanwhile. ROI and histograms remain separately deliverable; histogram
   integration does not require ROI first.
7. **Ownership unchanged:** Imagescope reads/measures. Image Lab owns editing,
   full-resolution rendering, undo, output metadata policy, no-overwrite export,
   and catalog insertion. The 2048px analysis raster is never an export source.

### Handoff and acceptance matrix

| Imagescope phase | Image Lab consumer | Evidence needed before acceptance | C1 status |
| --- | --- | --- | --- |
| 1 — Metadata | Stage 0a, `image_services.py`, File info | Public schema/version and API/CLI parity; supported-format and orientation fixtures; unknown/warning semantics; malformed/oversized metadata, timeout, and no-raster-load tests; local adapter tests with the actual provider | Pending; implementation files observed only |
| 2 — Color policy | Stage 0a plus render/export acceptance | Legacy and conversion policy identifiers; supported modes and invalid/missing profile/CMS behavior; conversion/alpha order, intent/BPC, provenance; shared profiled RGB/CMYK/alpha fixtures and numerical tolerances | Pending; plan reviewed only |
| 3 — Lab integration/basic editing | Stages 0a–4 | Accepted metadata/color handoffs; orientation-correct crop and source-resolution export; unchanged originals; preview/export color agreement; stale-result and lifecycle tests | Planned, not implemented |
| 4 — ROI | Optional stage 5 region inspection | Original-coordinate validation, mapping/rounding, working dimensions and sampling provenance; eight orientations, edge/one-pixel crops, alpha, large sources, independent crop comparisons | Pending; not an MVP blocker |
| 5 — Histograms | Optional stage 5 comparisons | Bin/transfer/alpha/sampling/normalization contract; precise endpoint statistics; ramps, solids, alpha, and count/weight-conservation fixtures | Pending; independent of ROI |

### Pending decisions to close at implementation handoff

- Exact accepted metadata schema/API and supported-version policy; do not freeze
  today's work-in-progress shape solely from symbol names.
- How bounded source capability checks establish edit eligibility when metadata
  cannot determine exact frame counts or precision.
- Exact color-policy identifiers/settings and shared fixture tolerances, including
  the geometry-only path for untagged sources and placement of JPEG matte handling.
- Which existing measurements receive first-release UI, versus later swatches/
  comparison tools. None should be reimplemented just because UI is not yet built.
- Concrete cross-project fixture exchange and test evidence: keep synthetic
  fixtures local to each repository unless a shared package is explicitly agreed.

### Next coordination checkpoint

When Imagescope offers phase 1 or phase 2 for integration:

1. Re-read its integration plan and public API/protocol documentation.
2. Record the actual revision/artifact, relevant contract versions, plan digest,
   known limitations, and supplied test evidence here.
3. Run Image Lab adapter/preview tests against that provider in an explicitly
   authorized project environment; do not implicitly install or update dependencies.
4. Record accepted, rejected, or blocked status per matrix row, with evidence.
5. Update `docs/EDITOR_PLAN.md` only where the handoff changes agreed behavior.

### Verification of this record

The referenced integration plan was read in full and its digest recorded. The
local editor plan now names the public API, stage 0a, both early acceptance gates,
unknown-state rules, coordinate/revision contracts, and independent ROI/histogram
work. Local Markdown paths and document consistency were checked. Documentation
only: no application tests were rerun and no integration gate is claimed passed.

## Coordination pass C2 — editor foundation started, 2026-09-20

Status: **backend documentation advanced; Image Lab handoff acceptance still pending**.
The matrix above records C1's historical observations; this checkpoint updates the
readiness assessment without marking any acceptance gate passed.

During foundation slice S1 the sibling worktree continued changing. Latest
reference hashes observed at `2026-09-20T23:04:11-07:00`:

- `IMAGE_LAB_INTEGRATION_PLAN.md`:
  `7e41231da425fd80b408bf9da6c0e4f42a05a513d0efd5dc0b5e5567ab39df74`.
- `METADATA.md`:
  `8f531cc805916d8e092a206ba407dc8ada9c6c395f4d5a19b66055958e93ea1a`.
- `COLOR_POLICY.md`:
  `2b4204be1306115a57be4de08c40ea11552df61e18586a5efef8393a6bbd2490`.

The integration plan now records phase 1 implementation and an initial phase 2
slice. Phase 2 explicitly retains a valid CMYK reference-profile numerical fixture
as a release gate. These records were read; their backend test claims were not
independently executed or accepted here.

Concrete consumer constraints now identified:

- Metadata-v1 is separate from analysis schema-v1 and must not go through the
  existing analysis `validate_result`. Unknown metadata versions must fail clearly.
- Metadata snapshots hash the encoded input; the API's worker deadline does not
  preempt a stalled caller filesystem read. The Lab adapter must not put that read
  on the UI thread or assume a QThread alone makes it safely cancelable.
- EXIF exposes bounded top-level tags; rational and nested values can be null with
  warnings. The current Lab reader exposes exposure/lens sub-IFD fields that this
  contract does not promise. Do not silently lose those fields while claiming
  feature parity, invent them, or secretly run a second metadata reader. Decide
  and document their unavailable state at metadata acceptance.
- `legacy-v1` and opt-in `srgb-v1` are now documented. The latter converts before
  reduction **and before orientation**, using relative-colorimetric intent,
  black-point compensation disabled, and explicit profile/declaration/assumption
  rules. The Lab geometry core takes already color-handled pixels plus explicit
  orientation; it does not implement or claim this conversion gate.
- Color comparisons must match preprocessing/color policy as well as measurement
  version. ICC bytes retained by a geometry operation are not proof of validity
  or successful conversion.

Image Lab delivered pure recipe/history and in-memory geometry with 24 passing
synthetic tests; see `docs/EDITOR_IMPLEMENTATION.md` and `docs/EDITOR_CONTRACT.md`.
No editor UI, worker/export pipeline, or metadata provider migration was performed.
The existing full suite is not green; evidence and classification are recorded in
that implementation record. Neither repository's release/version state changed,
and no Imagescope files were modified by this pass.

## Coordination pass C3 — metadata integration, 2026-09-21

Status: **metadata-v1 accepted for File info against the observed development
provider; the combined stage 0a gate remains incomplete.** No Imagescope source,
dependency installation, package version, or release state was changed.

### Actual provider and handoff snapshot

Existing Image Lab `.venv` imports the editable sibling at
`../imagescope/imagescope/__init__.py`, distribution version `0.1.0`. Its checkout
HEAD is still `3696cab`, with uncommitted/untracked metadata and color work; HEAD or
package version alone cannot identify this accepted implementation.

Reference digests captured at `2026-09-21T00:44:23-07:00`:

- `IMAGE_LAB_INTEGRATION_PLAN.md`:
  `748573b76606baf1e950587b15241fc7ae3d2e684c54ee1c8dac702420254c0c`.
- `METADATA.md`:
  `8f531cc805916d8e092a206ba407dc8ada9c6c395f4d5a19b66055958e93ea1a`.
- `COLOR_POLICY.md`:
  `f0f9c6d5bd26b2299aa9d6e7225965eb56dc1110689407e1620231350f6275cc`.
- `imagescope/metadata.py`:
  `814ee73d9d4aeee0118a46fb5bb8cf4f543cd80bd619117d4bfa4e874c787dd0`.
- `imagescope/metadata_worker.py`:
  `72cb0a320417ee3bdd200e4860f97f7223aef63a0a875ab1daf647ff8a2e438d`.

The handoff reports 119 passing backend tests and successful wheel/source builds.
Those backend checks were not independently rerun here. Image Lab instead executed
its own public-API/CLI and UI/process tests with synthetic fixtures inside this
repository. This is development-provider acceptance, not proof that a published
Imagescope 0.1.0 artifact contains the metadata API.

### Accepted metadata behavior

- `image_services.py` calls only public
  `inspect_metadata(MetadataRequest(Path(path), timeout=10))`. It validates integer
  `metadata_version == 1` separately from analysis, allows additive fields, rejects
  unsupported contracts, and never calls analysis `validate_result()`.
- The old Pillow reader and its replaced tests were retired only after passing
  real-provider integration tests. No fallback reader, raster loading, thumbnail
  creation, inference, or color conversion was added to metadata inspection.
- File info displays stored/oriented dimensions, source mode, declared alpha,
  profile state/identity, sequence declarations, encoded digest, and structured
  code/field/message warnings. Nullable values stay unknown; false and zero stay
  distinct. Original paths/bytes/mtime are not rewritten; GPS tags are not displayed.
- **Explicit capability difference:** DPI and nested EXIF lens/capture/exposure
  fields are unavailable through metadata-v1. The panel explains this rather than
  claiming the old reader's field parity. Top-level omitted rational values show
  Unknown. Original camera/mode/dimension facts match the public provider.
- A disposable process owns source stat/read/hash/API work, with a 15-second outer
  wall timer, cancellation on new loads/close, and generation plus catalog source
  keys. The API retains its own 10-second budget and bounded parser. The adapter
  checks source identity before/after inspection; same-path catalog revision changes
  restart it, and catalog drift is visible. Saved Library notes remain independent.
- Linux parent-lifetime guards are installed; normal cancellation/deadline cases
  are tested. Kernel uninterruptible I/O can still delay process death/reaping;
  neither an API timeout nor SIGKILL is a guarantee of immediate kernel cleanup.

### Local evidence and remaining gates

- **13 adapter tests passed:** six formats; grayscale/indexed/CMYK/high-depth modes;
  all orientations; CLI/API parity; ICC identity, invalid/oversized profiles;
  unknown/rational states; corrupt/missing/changed sources; missing API/unsupported
  version; and header success despite an invalid pixel stream.
  `results/metadata-adapter-tests.log`.
- **16 viewer/process tests passed:** UI heartbeat under a stalled read, navigation,
  same-path revision changes, refresh/close, timeout, malformed/duplicate/stale/wrong
  source results, output limits, process failures, and normal viewer regressions.
  `results/metadata-viewer-tests.log`.
- Packaged-wheel API/process smoke passed with the existing dependency environment;
  no package installation was performed. `results/metadata-wheel-build.log` and
  `results/metadata-wheel-smoke.log`. Visual checks:
  `results/imagescope-metadata-900.png`, `results/imagescope-metadata-1280.png`.
- Full offscreen suite: **203 tests, 14 failures, 3 errors**. Failing test identities
  exactly match the S1 offscreen baseline; all metadata/viewer and 41 editor-core
  tests passed. `results/metadata-integration-full-tests.log`. No clean release gate
  is claimed, and the existing analysis/queue/IPC compatibility issues remain open.

The new backend plan closes its synthetic CMYK numerical gate and refines unshipped
`srgb-v1` to require NOOPTIMIZE, relative-colorimetric intent, and disabled BPC.
Image Lab has **not accepted preview/render/export color agreement**. No pixel
editing UI, color-guided adjustment, safe copy export, ROI, or histogram integration
was added. Existing measurements should be reused later, never reimplemented or
silently recolored by this metadata migration.

## Coordination pass C4 — existing measurement reuse, 2026-09-21

Status: **read-only measurement adapter/UI slice delivered; not full-phase
completion or preview/measurement color agreement.** The C3 metadata slice's
**29 focused tests and wheel smoke passed**. Its full suite was baseline-failing,
not green; that distinction is retained below.

The existing analysis adapter now calls public
`analyze(AnalysisRequest(source=path, task='inspect', timeout=30,
palette_size=6, color_policy='legacy-v1', assume_srgb=False))` in an isolated process.
It validates analysis schema-v1 separately from metadata-v1 and accepts the observed
measurement-v6 / preprocessing-v3 contract. No palette extraction or other pixel
algorithm was rebuilt in Image Lab; no Imagescope files or dependencies were changed.

The on-demand Measures tab displays the provider's palette, luminance, and
transparency output. Policy/status, algorithm versions, source digest, working
size, downsampling, palette/alpha sampling, first-frame scope, and bounds limitations
are visible. Source stat identity is checked around the operation; changed catalog
fingerprints, mismatched source paths/versions, stale loads, close/navigation, and
malformed responses cannot publish successful readouts. No measurements are written
as generated Library notes. New description records retain their analysis provenance;
older saved records are not silently assigned guessed color semantics.

The source/load envelope and bounded cancelable supervisor are shared with metadata.
Measurement work has a 35-second outer timer; the provider request has 30 seconds.
As before, kernel uninterruptible I/O can delay actual process reaping. Repeated
fault tests exposed a Qt teardown crash from callback cycles; the shared supervisor
now disconnects callbacks before deferred process deletion, and regression tests pass.

Reference digests at `2026-09-21T01:26:07-07:00`:

- `PROTOCOL.md`: `b851ee093e27777c61bd4fd9b6475f95866b7405e0b3eff0b8636b16c2165ad6`.
- `COLOR_POLICY.md`: `f0f9c6d5bd26b2299aa9d6e7225965eb56dc1110689407e1620231350f6275cc`.
- `imagescope/api.py`: `14877bffea63be6fd404d03d5cb419f74080c27b4bfa02088aad269c41015aed`.
- `imagescope/measurements.py`: `e5f34db02d5fb9113a708bcddf3275839572218068f21950c2fc312122fa933c`.

Local evidence:

- **41 focused tests passed**: the prior 29 plus 7 measurement-adapter tests,
  4 measurement-process tests, and 1 viewer integration test.
  `results/measurement-focused-tests.log`.
- New extracted-wheel smoke passed for **both** metadata and measurement workers,
  and includes the new QML panel. Existing dependency environment; no installation.
  `results/measurement-wheel-build.log`, `results/measurement-wheel-smoke.log`.
- Full suite: **215 tests, 13 failures, 3 errors** — still baseline-failing, not
  green. No new failing test identities. The previously intermittent theme/queue
  test passed this run; it was not repaired or claimed resolved by this slice.
  `results/measurement-full-tests.log`.
- Visual checks at 900×600 and 1280×900:
  `results/measurements-900.png`, `results/measurements-1280.png`.

**Gate retained:** legacy unmanaged readouts are not verified against preview
colors. No color-guided adjustment is enabled; no sRGB conversion policy was
adopted. Preview/measurement/render/export agreement still needs shared color
fixtures and explicit acceptance. Editing, safe copy export, new ROI APIs, and
new histogram integration remain outside this slice.

## Coordination pass C5 — resume editor color foundation, 2026-09-21

Status: **synthetic RGB/RGBA color-core agreement established, not end-to-end editor
color acceptance.** Image Lab now has an explicit worker-only color-preparation
function ahead of its shared geometry engine. Live viewer/measurement behavior and
the existing unmanaged worker protocol have not changed.

The supported editor subset uses the same whole-image `srgb-v1` transform settings
as Imagescope: relative-colorimetric, NOOPTIMIZE, BPC disabled, ICC precedence,
explicit untagged assumptions, separate alpha, and conversion before geometry.
CMYK/LAB/indexed/grayscale/high-depth expansion remains deliberately out of scope.
Legacy remains explicitly unmanaged. No palette or measurement algorithm was copied.

Twelve synthetic tests cover an independently calculated linear-RGB transfer ramp
(within one 8-bit code value), sRGB identity, alpha, conversion-before-reduction,
invalid/oversized/mismatched profiles, missing CMS, declared/assumed distinctions,
preview guards, and unchanged originals. Public `analyze(AnalysisRequest(...,
color_policy='srgb-v1'))` comparisons match measurement output and shared color
provenance across all eight EXIF orientations. These are bounded fixtures, not
certification of arbitrary profiles or display-system color management.

The live sibling advanced during this work. Rechecked at
`2026-09-21T08:02:39-07:00`, HEAD still `3696cab`:

- `IMAGE_LAB_INTEGRATION_PLAN.md`:
  `2ad4d3e05520e4aeac1910e220729c7ae254f43cc988c93940ee02fa066a4732`.
- `COLOR_POLICY.md`:
  `eceb90bdcba752e0bf03e25aaca7ad7c896afc9fa4cd4deb34ba53ab29edd717`.
- `imagescope/color_management.py`:
  `85a9336140c1d14eeee163fcfc17fc4b5c6b469748d30fab98ee32d873e4c6a5`.

The plan now records ROI-v1/preprocessing-v5 and 131 backend tests plus package
checks. These are backend-supplied claims, not independently rerun here. Whole-image
legacy/sRGB preprocessing remains v3/v4; this slice uses no ROI and does not expand
the consumer adapter's accepted versions. The backend also records the owner's
C4 consumer handoff report. Neither repository's release state was changed here.

Evidence: **53 editor tests passed**, extracted-wheel color-pipeline smoke passed,
and the full suite ran **227 tests with 14 failures / 3 errors**, with no new failing
identities against the known baseline. Full-suite status remains baseline-failing,
not green. Logs: `results/editor-color-regression-tests.log`,
`results/editor-color-wheel-smoke.log`, `results/editor-color-full-tests.log`.

Remaining gate: version and validate policy/provenance/profile transport in the
render worker; carry it through editor sessions and Qt previews; select matching
measurement policy; then test safe-copy output tagging and alpha/matte behavior.
The current worker still rejects managed-color claims. Do not enable editing UI or
color-guided adjustments solely because these in-memory fixtures pass. ROI remains
optional later work, not a reason to divert from the crop/resize/export plan.

## Coordination pass C6 — managed worker transport, 2026-09-21

The next editor slice connects the S5 color core to Image Lab's isolated render
worker. Private protocol v2 carries requested policy/assumption, source-bound
provenance, and a separate bounded ICC payload. Source snapshots include a PNG
sRGB declaration so parent validation can reject invented declarations. Legacy
remains the default; preparation remains color-neutral. No live viewer/Measures
policy or Imagescope source was changed.

Real-worker RGB/RGBA fixtures cover all eight EXIF orientations, exact core versus
worker preview/full pixels, public whole-image measurement parity, original bytes /
mtime, alpha, >2048px full output, and profile transport beyond the JSON-header
limit. Fault injection covers policy/provenance/profile drift and child reaping.
ICC parsing/conversion stays in the bounded child; the parent validates metadata,
lengths, digest and minimal ICC framing, not arbitrary profile semantics.

Evidence: **61 editor tests passed**; extracted-wheel actual-worker smoke passed.
The full suite ran **235 tests with 13 failures / 3 errors**, with no new failing
identities against S5. This remains baseline-failing, not green; intermittent test
success is not a repair. See `results/editor-color-worker-regression-tests.log`,
`results/editor-color-worker-wheel-smoke.log`, and
`results/editor-color-worker-full-tests.log`.

Provider reference checked at `2026-09-21T08:44:24-07:00`:

- `COLOR_POLICY.md`:
  `d6fceefaeee910fcefffbb8af9dc5085ed8e07827c5f458e92ed410c75a76c4f`.
- `imagescope/color_management.py` remains the C5 implementation:
  `85a9336140c1d14eeee163fcfc17fc4b5c6b469748d30fab98ee32d873e4c6a5`.

The color document now mentions opt-in histogram measurement-v7; default
measurements remain v6 and whole-image legacy/sRGB preprocessing remains v3/v4.
No histogram/ROI integration or broader consumer-version acceptance is implied.
No backend-wide test/build gate was rerun or claimed here.

Remaining acceptance: tagged Qt preview/session scheduling, matching measurement
requests, and safe-copy output tagging/alpha-matte behavior. Stage 0a and editor UI
remain gated. Managed raw worker output is not a safe encoded export, and passing
these fixtures is not full preview/display/export color certification.

## Coordination pass C7 — Qt preview alignment, 2026-09-21

Image Lab now has a bounded Qt image-provider bridge for managed worker previews.
It tags already-interpreted sRGB pixels without applying the original ICC again,
preserves alpha/channel layout, and rejects stale, duplicate, cancelled, or wrong-
recipe/policy completions. The supervisor retains the submitted recipe alongside
validated worker output; private protocol v2 is unchanged.

The public measurement adapter accepts explicit `srgb-v1` requests and validates
whole-image measurements-v6 / preprocessing-v4. Its defaults and live Measures
consumer remain legacy-v1/v3. Current-preview matching binds source path/content,
profile, original recipe, policy/assumption, interpretation, and Pillow/LittleCMS
identity. Original statistics are rejected for edited recipes, including same-size
flips. No measurements, ROI, histograms, or inference algorithms were reimplemented.

Accepted evidence is **bounded numeric software-preview agreement**, not a global
colorAgreement flag: Qt/PySide6 6.11.2, Pillow 12.3.0, offscreen/software Qt Quick,
RGB/RGBA, all EXIF orientations, known sRGB tags, and white alpha compositing within
two 8-bit channel values. Real asynchronous Image-provider loading and captured
pixels also pass from an extracted wheel. Physical monitor/HDR/hardware backends
and encoded-copy tagging/matte behavior remain outside this acceptance.

**69 editor tests passed** (8 new), and packaged Qt preview smoke passed. Full
suite: **243 tests, 14 failures, 3 errors**, no new failing identities against the
established baseline; not green. Evidence is in `results/editor-preview-*.log`,
with `results/editor-preview-qt.png` as the numeric capture fixture.

The bridge is not installed in the live viewer. Disposable-job scheduling, source
freshness/envelope handling, editor session/UI, and safe encoded export remain
unfinished. Source/policy alignment does not mean exact palette/display equality
or measurements of edited pixels. Keep the original readout disclosures and
color-guided controls unchanged until the corresponding integration gates pass.
No Imagescope source, dependency installation, or publication was changed here.

## Coordination pass C8 — editor session lifecycle, 2026-09-21

Image Lab now has a programmatic Qt session that schedules preparation/rendering
through the existing isolated worker and publishes through the C7 bridge. It keeps
one active supervisor job and one latest pending job; late results are consumed
without replacing newer source/recipe/policy generations. Geometry commands,
history, original comparison, explicit policy choice, and source-change errors
preserve the source and the draft's identity.

Dirty close/navigation/shutdown requires explicit discard with the current revision.
A stale confirmation cannot discard later edits or close a different session.
Closing cancels work without blocking Qt, and completion waits for child reaping.
Work-active and external-mutation guards are provided as hooks; they are **not yet
installed in existing viewer, queue or IPC routes**. There is no export/mark-saved
operation or new editing panel in this slice.

**83 editor tests passed**, including 14 new session tests. Real stalled-child,
QObject-destruction, stale-completion, coalescing, source-change and confirmation
cases pass. Extracted-wheel programmatic session smoke passes crop/rotate/resize,
preview/comparison, dirty guards and shutdown with original bytes/mtime unchanged.
Full suite: **257 tests, 13 failures, 3 errors**, with no new failing identities
versus C7; baseline-failing, not green. An intermittently passing theme/queue test
is still not considered repaired. Evidence: `results/editor-session-*.log`.

No additional Imagescope capability/version was accepted or implemented here.
The live Measures policy remains unchanged. Remaining work includes application
transition routing, accessible editor controls and gesture mapping, managed
measurement job coordination, safe encoded copies, and release stabilization.
Do not mark stage 2 or the overall phase complete from a programmatic session
smoke alone. No backend source changes, dependency installs, or publication occurred.

## Coordination pass C9 — live numeric geometry preview, 2026-09-21

The S8 session is now installed behind **Edit image** in the full-image viewer.
The live UI supports numeric crop/presets, rotate/flip, aspect-locked resize,
upscale consent, history, original comparison, explicit sRGB assumption, and
revision-bound discard. Un-applied form values are guarded too. Entry is pinned
to catalog identity/path; conflicting controller and IPC operations are blocked
until closing has reaped its child. Read-only IPC remains available. Normal quit
attempts close only the editing session first, without replaying a stale quit.

**91 editor tests passed**, including 8 live controller/QML/IPC tests. An extracted-
wheel actual Main.qml workflow passes at DPR 1/2 and logical 900×600 / 1280×820,
including pointer entry, numeric edits, keyboard Escape, confirmation and shutdown.
Source bytes/mtime remain unchanged and no QML warnings were emitted. Final full
suite: **265 tests, 13 failures, 3 errors**, no new failing identities against the
established baseline. The known theme/queue intermittent test failed on an earlier
run and passed on the final run; it is not repaired. Evidence and captures are
`results/editor-live-*`; the implementation record gives exact artifact paths.

No new Imagescope API/version, ROI/histogram feature, or color handoff is accepted
here. Live Measures remains legacy-v1 and is not shown as edited-image data.
Managed editor measurement scheduling, drag mapping, safe encoded-copy export and
color/alpha/metadata acceptance remain open. UI previews are explicitly session-only
and export-unavailable. Do not mark stage 2, stage 0a, or the phase complete from
these checks. No Imagescope edits, dependency installation, or publication occurred.

## Coordination pass C10 — staged drag crop, 2026-09-21

Image Lab now stages drag selection, corner resizing, movement and keyboard nudges
on its existing preview. Apply maps normalized painted-image coordinates through
inverse resize/flips/rotation to the oriented original recipe and commits one undo
step. Revision/readiness checks reject stale/comparison frames. Cancel, pending-draft
close guards and gesture cancellation preserve the recipe/selection as appropriate.
This trims the current preview; numeric bounds/Reset expand prior crops.

**99 editor tests passed**; extracted-wheel pointer workflow passes at DPR 1/2 and
logical 900×600 / 1280×820, with no QML warnings and unchanged originals. Mapping
coverage includes rotations/flips, resize, EXIF orientation, letterboxing, extreme
aspect ratios and stale/cancel paths. Full suite: **273 tests, 13 failures, 3 errors**,
no new failing identities against the established baseline. Evidence is recorded in
`docs/EDITOR_IMPLEMENTATION.md` and `results/editor-drag-*`.

No Imagescope API or new color/measurement capability was accepted. Managed editor
measurement jobs, encoded export and color/alpha/metadata acceptance remain open;
this is not completion of stage 0a, stage 2, or the overall phase. No backend edits,
dependency installation or publication occurred.

## Coordination pass C11 — copy-publication foundation, 2026-09-21

Image Lab now has a tested filesystem primitive for eventual export: anonymous
staging, pinned directories, source/reservation checks, mandatory verifier callback,
atomic no-overwrite linking and truthful partial/uncertain publication outcomes.
It is not wired into the live session and does not provide image encoding or color
acceptance. Source decoding/digest checks remain the isolated renderer's job.

**125 focused editor/publication tests passed**, including 26 new publication tests.
Extracted-wheel publication smoke passes with unchanged source bytes/mtime and
collision refusal. Complete serial full suite: **299 tests, 14 failures, 3 errors**,
all established failing identities including the intermittent theme/queue failure.
An earlier full-suite attempt crashed during desktop tests and is recorded as
incomplete; the crash is not claimed fixed. Evidence: `results/export-publication-*`.

No new Imagescope capability/version or color handoff is accepted. Managed editor
measurements, bounded encoding and encoded-color/alpha/metadata acceptance remain
open, along with live export lifecycle, controls and optional import. No backend
changes, dependency installations or release publication occurred.

## Coordination pass C12 — integrated editor export/inspection, 2026-09-21

Image Lab now owns a complete bounded full-source PNG/JPEG/WebP encoding and
no-overwrite publication workflow, with optional normal catalog import, while
Imagescope remains the read-only whole-image measurement provider. The editor's
managed inspection uses the public `AnalysisRequest(task='inspect', palette_size=6,
color_policy='srgb-v1', assume_srgb=...)` path. No private palette implementation,
reduced analysis raster export, backend source changes or dependency installs.

### Reference and accepted scope

Re-read `../imagescope/COLOR_POLICY.md`; observed HEAD remains `3696cab` (editable,
unpublished 0.1.0, not a sufficient identity for the live tree). SHA-256:

- `COLOR_POLICY.md`: `d6fceefaeee910fcefffbb8af9dc5085ed8e07827c5f458e92ed410c75a76c4f`
- `imagescope/color_management.py`: `85a9336140c1d14eeee163fcfc17fc4b5c6b469748d30fab98ee32d873e4c6a5`
- `imagescope/api.py`: `d5a012eaf5c5d82876413041cf51acdc8844ce1a7cb4938863716ad34777eac7`

Accepted consumer scope remains metadata-v1, whole-image measurements-v6/schema-v1,
legacy preprocessing-v3 and opt-in sRGB preprocessing-v4. The changed API digest is
recorded, not blanket acceptance of additional capabilities. No ROI/preprocessing-v5,
histogram-v7, grayscale/indexed/CMYK editor inputs or provider test-count claims are
accepted here. Provider-wide tests were not rerun.

ICC precedence, fail-closed invalid profiles, explicit untagged assumptions,
relative-colorimetric NOOPTIMIZE/BPC-off conversion before reduction and separate
alpha are unchanged. Editor results match snapshot digest/profile, policy/runtime
provenance and exact session generation. Source-policy alignment is separate from
original-preview alignment; edited recipes never acquire edited-statistics claims.

### Consumer evidence and limits

**148 focused tests pass.** Actual extracted-wheel edit → managed inspection →
full-resolution encode → atomic publish → optional import passes at 900×600 and
1280×820, DPR 1/2, with zero QML warnings and byte/mtime-identical originals. PNG
and lossless WebP match full-render pixels at 1400×2400 (larger than preview limits).
JPEG matte, deliberate sRGB tagging, metadata stripping, linear-profile numerical
references and cancellation/partial-import/reservation behavior are tested.

This closes the scoped software RGB/RGBA preview/original-measurement/encoded-output
consumer acceptance gap, **not monitor/HDR or universal-profile certification**.
Color-guided controls remain disabled; original measurement sampling is still
approximate and differs from preview sampling. Publication evidence is local Btrfs,
not hardware power-loss proof or certification of all permitted filesystem types.

Final full suite: **322 tests, 14 failures, 2 errors**, no new failing identities against
completed S11 evidence. The export-required RGBA-thumbnail fix removes one baseline
error; the known intermittent theme/queue failure recurred in the final run. Remaining failures,
earlier native crash and shutdown garbage-collection warning are not fixed claims.
See `docs/EDITOR_IMPLEMENTATION.md` and `results/editor-export-*`. Only disposable
in-repository test images were published; no user images or release were written.
