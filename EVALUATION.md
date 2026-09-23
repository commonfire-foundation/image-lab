# Local vision smoke-test review

## Library details redesign — 2026-09-22

- Full suite: **335 passed** (`results/details-redesign-full-tests.log`).
- New live tests cover token entry/paste/deduplication/removal, pending values across
  tabs, cancel/reopen, Ctrl+Enter, empty lists, long labels and fixed-footer bounds.
  Existing stale-save, correction persistence and original-preservation tests pass.
- Extracted-wheel screenshots and save acceptance cover dark/light palettes,
  900×600 and 1280×820 windows, at DPR 1 and 2, with zero QML warnings and unchanged
  original bytes (`results/details-redesign-package/`). Generated fixtures only;
  no personal catalog or image was modified. No live-model run or manual
  screen-reader certification is claimed. The known shutdown GC warning remains.
- Reproducer: `tools/smoke_details_editor.py OUTPUT_DIRECTORY`, with the intended
  extracted package on `PYTHONPATH` and software/offscreen Qt rendering.

## Geometry-editor stabilization — 2026-09-22

- Full suite: **331 passed** (`results/stabilization-full-tests.log`).
- Fresh extracted-wheel editing/export/import passed at 900×600 and 1280×820,
  DPR 1 and 2: twelve full-resolution copies, unchanged originals, zero QML warnings
  (`results/stabilization-package/`).
- The former queue/IPC failures were primarily obsolete fake-backend signatures,
  not demonstrated production inference failures. No new real-model run was made.
- Fifteen repeated lifecycle tests passed without reproducing the historical native
  crash. It remains unresolved, not claimed fixed. The shutdown GC warning has a
  separate minimal PySide6 Property reproducer with no Image Lab imports.
- See `docs/EDITOR_IMPLEMENTATION.md`, S13, for changes, evidence and remaining gaps.

## Local UI IPC verification

The initial UI IPC implementation passed 132 tests on Linux/Python 3.14,
including real-socket, separate-client tests and the existing desktop suite.
Installed-wheel acceptance (`tools/smoke_ui_ipc.py`) passed outside the checkout
using disposable catalogs and fake inference. This is not a live-model quality
check. See `docs/IPC_PLAN.md` and `results/ipc-full-tests.log` for scope/evidence.

## Imagescope dependency migration

Image Lab now depends on the separate `imagescope==0.1.0` package; the bundled
`image_analyzer` and combined-package build were removed. The historical inference
results below predate this migration and are not a new live-model verification.

Migration verification on Python 3.14:
- All 112 Image Lab tests passed with Imagescope installed editable from its sibling checkout.
- Image Lab wheel and source archive built; neither bundles the backend.
- Separate installed wheels passed discovery, inspection subprocess, catalog
  thumbnail, and desktop QML loading checks outside the source checkout.
- Local virtual environments reused existing system runtime dependencies; no fresh
  dependency-resolution or Python-version matrix check was performed.
- No new real-model inference run was performed.

Evidence: `results/imagescope-migration/tests.log`, `build.log`, and
`installed-smoke.log`. An internal-backend backup is kept in the same directory.

## Setup

- Ollama 0.20.6, qwen3-vl:4b, digest `1343d82ebee38e26a4dd6b0180b915eb91550184e67c505dea97509571c8f683`.
- Prompt `wallpaper-v2`, JSON continuation, 768px maximum-side JPEG, temperature 0, seed 42, context 4096, output budget 1024.
- Local inference only; source filenames are not sent to the model.
- Seven development images and three held-out images from the local Wallpapers directory.
- Manual visual review by the coding assistant, not independent human ground truth. No numeric semantic accuracy claim.

## Final observations

All ten images returned schema-valid output with no reported thinking. Warm end-to-end latency ranged from 8.014 to 8.992 seconds, median 8.4755 seconds. Earlier runs reported full GPU placement and 4.6 GB model VRAM allocation; this is not measured peak GPU memory. Cold-start performance is not established by these warm runs.

| Sample | Main-content review | Medium | Text flag | Remaining caveat |
| --- | --- | --- | --- | --- |
| abstract/purple_abstract_waves.jpg | Correct purple/black flowing pattern | abstract | false | Subjects contain colors rather than entities |
| anime/b-012.jpg | Captures character, halo, cross | illustration | true | Caption redundantly describes cross placement |
| fauna/parrot.png | Correctly sees moon and bats, despite misleading filename | illustration | false | Repeated bat labels cleaned transparently |
| logo/space_logo_jp.jpg | Captures lettering and orbital graphic | illustration | true | Medium is an interpretive category |
| minimal/b-035.jpg | Correct character on right with negative space | illustration | false | Mood remains subjective |
| nature/sea_rock_island.jpg | Correct rock/ocean/waves | photograph | false | Ocean/water/sea synonyms remain |
| pixel/pixel_torii_town.jpg | Correct gate, lanterns, buildings | pixel-art | false | Eleven tags exceed the soft eight-tag preference, but satisfy schema |
| abstract/neon_triangle_cloud.jpg (held out) | Correct glowing frame and cloud | 3d-render | false | Calls triangular 3D frame a triangle rather than pyramid |
| nature/koi_pond.jpg (held out) | Correct koi and floating leaves | photograph | false | Exact count happened to be right but isn't guaranteed |
| pixel/pixel_boat_sunset.jpg (held out) | Correct boat, sunset, birds | pixel-art | false | Extra vector tag is questionable |

No sample was predicted to contain a watermark. The set has no known positive watermark example, so this does not establish watermark detection quality. Text presence means visible writing-like marks, not successful transcription.

## Experiments and decisions

1. Original 1024px prompt: two successes, illustration failed after exhausting tokens on thinking despite `think: false`.
2. Smaller preview and JSON-only instructions alone: still failed.
3. JSON assistant prefix plus full schema: fixed observed completion failures.
4. Concise prompt v1: improved text presence but incorrectly called flat bat illustration pixel art.
5. More explicit medium definitions at 512px: fixed bats but missed pixel style in the gate scene.
6. Same prompt at 768px: classified both correctly. Adopted as current default; resolution remains configurable.
7. Whitespace/case normalization and exact deduplication: deterministic cleanup, raw validated predictions preserved when changed. No semantic claims corrected or invented by code.
8. Three held-out samples: all completed and produced useful broad descriptions. No further prompt tuning against these samples.

## Scope of the result

Good enough for a local tagging experiment and human-reviewed search labels. Not evidence for unattended sorting, deletion, identity recognition, exhaustive OCR, or reliable watermark screening. A larger independently labeled sample is needed before making quality claims about the full library. Keep original images read-only.

## Evidence

Local, ignored artifacts under `results/` include final development and holdout JSONL files, contact sheets, earlier candidate results, and original failure diagnostics. These are not required for the unit tests and are not bundled with the source.

## Analyzer extraction acceptance

- 55 tests pass, including real subprocess/fake-model protocol failures, stdin,
  input limits, cancellation, batch stop/pause/resume/retry, and preservation of
  good predictions after a malformed process result.
- The same suite runs without Qt: 39 pass, 16 desktop/migration tests skip.
- Independent `image-analyzer` and `image-lab` wheels and source archives build.
  The analyzer installs in a fresh environment with Pillow/NumPy and no Qt or
  desktop package. Its source archive rebuilds without the combined checkout.
- An installed standalone analyzer described `purple_abstract_waves.jpg` in
  14.002 seconds on the first acceptance run with no model initially loaded.
  Its caption and exact wallpaper prompt matched the previously stored result.
  This is a regression smoke check, not proof of deterministic model output.
- The final installed desktop/analyzer wheels completed a real two-image batch
  against a disposable catalog, pausing after the first image and resuming the
  second. Two succeeded, zero failed, no QML warnings, and both original SHA-256
  hashes remained unchanged. Existing personal catalog contents were not migrated
  or used as a test destination.
- Evidence: `results/analyzer-extraction-tests.log`,
  `results/analyzer-no-qt-tests.log`, `results/analyzer-live-installed.json`, and
  `results/analyzer-live-desktop-final.json`. The latter identifies the installed
  modules and the disposable catalog containing saved results.

Remaining limits: no cross-application GPU scheduler, no new semantic accuracy
study, only the wallpaper task and Ollama backend, and cancellation of the client
cannot guarantee cancellation of work already submitted to Ollama.
