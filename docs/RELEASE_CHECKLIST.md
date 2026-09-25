# Image Lab 0.1.0 release acceptance

This records the 0.1.0 release decision and its remaining limitations.
Unchecked manual UI cases are **not certified** by automated acceptance; do not
represent them as passed. Run checks with disposable images and a fresh catalog,
never a personal library. The owner requested publication after being told the
historical Qt-native crash's exact corrupted object remains unidentified.

## Dependency and package

- [x] Owner chose CommonFIRE and the MIT license. `LICENSE` and the wheel/sdist
  declare MIT; OldJobobo remains credited as creator. A user-local installer and
  two-wheel release bundle are built and verified without changing system packages.
- [x] Confirm the CommonFIRE Image Lab repository and add `origin`. The owner
  selected `commonfire-foundation/image-lab`. At preparation it was created
  private and empty; source and release publication are separate steps.
- [x] Resolve the published Imagescope `v0.1.0rc1` conflict with the distinct
  `v0.1.0rc2` prerelease. The old RC1 public wheel
  (`fff09f61…`) differs from the locally bundled RC1 wheel (`7e71548c…`) and
  lacks the metadata and color-policy APIs required by Image Lab. A fresh install
  of the public provider plus the current Image Lab wheel passed `pip check` but
  failed the full source suite (330 tests, 14 failures, 26 errors); the three
  narrow analysis integration tests passed. Do not advertise an ordinary
  `imagescope==0.1.0rc1` install as compatible. See
  `results/release-public-provider-install.log`,
  `results/release-public-provider-api.log`, and
  `results/release-public-provider-full.log`.
- [x] Align Image Lab's dependency with the published compatible provider:
  `imagescope==0.1.0rc2`. The older sibling wheel labelled `0.1.0` lacks the
  accepted metadata/color/editor APIs; a version label and `pip check` alone do
  not establish runtime compatibility. No sibling source was modified.
- [x] Build an Imagescope RC1 wheel from a **copy** of the current development
  source inside Image Lab's `results/`, then install it and the rebuilt Image Lab
  wheel in a fresh virtual environment with dependency resolution enabled.
  `pip check`, `imagescope info --json`, both CLI `--help` commands, the packaged
  editor/export/import smoke, and 337/337 source tests passed. See the latest
  acceptance evidence below; this verifies a local development installation.
- [x] Include the compatible Imagescope RC1 wheel and its frozen source snapshot
  in a **superseded local candidate bundle**. Historical base revision (`3696cab`),
  source archive hash and wheel hash. This was built from a read-only copy of a
  dirty sibling checkout, not from an independently published provider release;
  **do not publish that superseded bundle**. The final bundle uses the published
  RC2 assets instead.
- [x] Inspect the rebuilt Image Lab wheel and sdist for QML, SVG assets, editor
  worker modules and metadata: both include 18 QML files, an SVG and the editor
  worker module. The wheel's editor/export/import path passed from an installed,
  non-editable package.

## Final RC2 artifacts (2026-09-24)

- Provider tag `v0.1.0rc2` resolves to
  `333cd177d6e0c8f63beae55c8ef5c46cea202faf`. The published wheel SHA-256
  is `f489cc0743efb76dc59d6685dbdc599e3d9bcb5f8efe9ced48ee9029af172f12`;
  published source archive SHA-256 is
  `db4a4c4e38ecbcaad264237db6aa38f8585a6a2d26b88e63901527e7ab255eac`.
  Both downloaded files passed the publisher's `SHA256SUMS` check and are copied
  byte-for-byte into the bundle.
- Final Image Lab wheel SHA-256:
  `2ba0d20b8f76f8c87fd2ab8107b8b464132e62d82830fce2cc605692f7df462d`.
  Final Image Lab sdist SHA-256:
  `f22cbfd71c45924687fa142a3d9037a77b6c4577ac643c6bd6f23f668c5e2257`.
  Bundle `image-lab-0.1.0.tar.gz` SHA-256:
  `51d0c40fff8a4bdc197f5e495e093b53d4483cdd96e238ea70e1386f2077a4d9`.
- Extracted bundle dry run, isolated project-local installation, dependency
  check, exact-wheel full source suite (342/342), and installed-wheel editor,
  managed measurements, PNG/JPEG/WebP export and library-import smoke passed.
  Evidence: `results/release-final/{installer-dry.log,installer.log,full-suite.log,smoke.log}`.
  The smoke verifies unchanged original bytes and mtime, sRGB and stripped
  metadata at both 900×600 and 1280×820. This exact final bundle was checked
  on the host only; prior VM tests used the pre-RC2 provider snapshot. A VM
  RC2/HDR/screen-reader certification is not claimed.

## Behavior and manual follow-up

- [x] Run the full suite with the **published RC2 wheel** and final bundled
  Image Lab wheel in a fresh Python 3.12 environment: **342/342** passed
  (`results/release-final/full-suite.log`). The older snapshot-based 341/341 run
  is superseded. Qt property-teardown, transient QML fixture and resource
  warnings remain documented separately; no test failure was treated as passed.
- [ ] With an **unanalyzed** still image in a disposable catalog, open the viewer,
  enter Edit image, crop and rotate/flip, resize in pixels, undo/redo/reset and
  compare original. Verify controls and original byte hash/mtime.
- [ ] Export PNG, JPEG (including explicit matte for alpha), and WebP copies to
  an empty destination. Check full-source dimensions, sRGB tag, metadata stripping,
  no overwrite, and original byte hash/mtime. Opt in to library import for one
  copy; confirm the original stays selected and the copy is a new catalog record.
  Reopen the saved copy in the viewer. Exercise a filename collision and an
  import failure/retry separately.
- [ ] Exercise cancel during preview/export, source revision after editor entry,
  unsaved close/Keep editing, paused queue, and blocked IPC navigation/removal.
  Verify draft preservation, comprehensible errors, and no lost queue state.
- [x] Defer **pixel editing during another image’s analysis/queued work** beyond
  0.1.0, per owner decision. It remains blocked to protect editor ownership;
  during inference, browsing, queue controls and unrelated details/rename/
  library removal remain usable. Do not advertise pixel editing as concurrent.
- [ ] Review captured UI at 900×600 and 1280×820, DPR 1 and 2. Test keyboard focus,
  numeric crop alternatives, text-field undo, and dialog reachability manually;
  automated checks do not certify screen readers or monitor/HDR behavior.

## Risk and scope decision

- [x] Triage the historical native crash as far as current evidence permits.
  The GC diagnostic observed GUI-affine QObject cycles collected by a worker on
  both host and VM; the exact native receiver remains unidentified. The owner
  requested the release after this uncertainty was disclosed. No blanket claim
  that every native crash is fixed is warranted.
- [ ] Document Qt property-teardown warning separately; an isolated PySide6
  reproduction is not evidence it caused the crash. No dependency workaround has
  been validated for that warning.
- [x] Check README claims and install instructions against the final artifacts.
  Percentage resize entry is deferred; pixel resizing ships. Brightness, contrast,
  saturation, regional measurements, histograms, color picking, persisted drafts,
  and color-guided adjustments are not 0.1.0 requirements. No hardware/HDR or
  screen-reader certification is claimed.

Local release-hardening checks (development environment, not a fresh dependency
install): initial 335-test run failed three intermittent Qt UI assertions; the
three isolated reruns and next 335-test run passed. After allowing unrelated
metadata/file actions during inference, a 336-test run failed two assertions
expecting the old global busy guard; focused updates passed. A subsequent quiet
full-suite attempt terminated with **SIGSEGV (139)** and an empty redirected log;
there is no native stack or assigned root cause. A rerun with Python faulthandler
and verbose tests completed all 336 tests, with the existing Qt property teardown
warning. This does **not** clear the crash gate. Evidence:
`results/release-candidate-tests.log`, `results/release-candidate-retry.log`,
`results/release-post-responsiveness.log`, `results/release-final-tests.log`,
`results/release-crash-trace.log`. A fresh Image Lab wheel/sdist build
(`results/release-build.log`) contains 41 Python modules and 18 QML files;
extracted-wheel export/import passed offscreen at DPR 1
(`results/release-fresh-smoke.log`). The earlier extracted-wheel smoke also passed
(`results/release-smoke.log`). Both host checks use the live editable Imagescope
checkout, not an immutable dependency wheel. The host environment's `pip check`
is nonzero because `reuse 6.2.0` lacks `python-magic`; that is unrelated to Image
Lab but prevents using that environment as fresh-install proof.

A separate Omarchy VM test ran from disposable guest directories with a project-
local Python 3.14 venv, Pillow 12.3.0, NumPy 2.5.3, PySide6 6.11.2, a fresh Image
Lab wheel and a wheel built from the current **dirty Imagescope source snapshot**.
That provider wheel declares `0.1.0rc1`; `pip check` correctly rejects the
Image Lab `imagescope==0.1.0` pin. This cannot certify a reproducible install.
The packaged export/import smoke passed offscreen and on the guest's real Wayland
workspace 8 (six copy/imports each, unchanged original, no QML warnings), and
three focused responsiveness tests passed. Captures at 900×600 and 1280×820 are
under `results/release-vm-captures/`. See `results/release-vm-dependencies.log`,
`results/release-vm-offscreen.log`, `results/release-vm-wayland.log`, and
`results/release-vm-responsiveness.log`. The long-path guest staging run of the
336-test suite failed 15 IPC tests because its test-local Unix socket paths
exceeded Linux's 103-byte limit, plus one exact-version assertion (`0.1.0rc1`
versus `0.1.0`). All 18 IPC protocol/integration tests passed from a shorter
owned guest directory; see `results/release-vm-tests.log` and
`results/release-vm-ipc-short.log`. A full suite from that shorter directory
**segfaulted** while `test_batch_pause_resume_and_missing_scope` waited for a
batch: faulthandler shows the main thread in Qt event delivery
`QObject::event`, with a worker thread inside `run_analyzer`. This is stronger
localization, **not** a proven root cause or fix; see
`results/release-vm-short-full.log`. A subsequent host core dump (PID 4088834)
shows a Qt MetaCall event returning with an invalid QObject private pointer;
this suggests a lifetime issue but does not identify the offending receiver.
A Python 3.12.13/PySide6 6.11.2 isolated desktop-suite run also segfaulted,
so limiting support to Python 3.14 is **not** a valid explanation. Two test-
cleanup experiments (explicit controller retirement and deferred-delete flush)
were reverted: the first introduced more crashes, while the second passed one
336-test run and then segfaulted in another. Evidence is in
`results/release-core-assembly.log`, `results/crash-py312/desktop-1.log`,
`results/crash-flush-full-1.log`, and `results/crash-flush-full-2.log`.
That crash gate remains open pending the risk decision below. Fresh matching-
provider install, manual editing with active work, and interactive screen-reader
checks remain open. Those owned guest staging directories and virtual environments
were removed after collecting evidence; the persistent VM was left running.
Workspace 1 was restored and no guest client remained open. No guest system
packages were installed or changed.

A later VM run with thread-deletion changes still segfaulted in Qt event delivery
(`results/crash-thread-reap-vm-desktop-1.log`); that experiment was reverted.
Replacing a contextless single-shot callback with a persistent timer survived two
VM desktop runs but a full VM run aborted in cyclic garbage collection on a
Python-backed QThread (`results/crash-next-timer-vm-full-2.log`); that experiment
was also reverted. A diagnostic run with automatic cyclic GC disabled completed
all 336 tests except the known provider version mismatch
(`results/crash-gc-disabled-vm-full.log`). This points to Python GC running in
worker threads while PySide owns Qt objects, but does not prove the identity of
the object that was corrupted in the original Qt event crash.

The candidate suspends automatic cyclic GC while Python-backed controller
submission/analysis QThreads run, restores its prior state and collects on the
GUI thread after they stop. Reference counting stays active throughout; GC is
not permanently disabled. A regression test checks overlapping work and prior
GC state. Two host full-suite runs passed **337/337** each
(`results/crash-gc-guard-host-full-{1,2}.log`), and two VM full-suite runs
completed **337 tests** each with only the expected `imagescope==0.1.0` assertion
failing against the source snapshot's `0.1.0rc1`
(`results/crash-gc-guard-vm-full{,-2}.log`). Two VM desktop-suite reruns passed
38/38 each. The freshly built wheel passed a VM packaged edit/export/import
smoke (`results/crash-gc-guard-vm-smoke.log`). No native crash occurred in these
runs, but the workload is nondeterministic and risk acceptance is still required
before release. The later owned guest staging directory and its venv were removed;
VM workspace 1 was empty and no guest system packages were changed.

Further stress acceptance from the current dirty Image Lab tree (`5dec0b1` plus
its uncommitted changes), in a short-path disposable VM directory with the
Imagescope `0.1.0rc1` development snapshot: three consecutive desktop suites
passed **38/38** each (`results/release-stress-vm-desktop-{1,2,3}.log`). Two
more full-suite runs completed **337 tests** each, with only the known exact-
version failure against `0.1.0rc1` (`results/release-stress-vm-full-{1,2}.log`).
A real Wayland workspace-8 session analyzed **75/75** images with the slow fake
backend over **182 seconds**, while 364 scripted Tab/selection interactions ran;
its worst 100 ms heartbeat gap was **0.179 s**, cyclic GC was restored, and QML
reported no warnings (`results/release-stress-vm-session-2.log`). An earlier
250-second session also analyzed 75/75 without a native crash, but its probe
mistook the terminal queue state `complete` for `done` and wrongly failed its
own assertion; this harness error is preserved in
`results/release-stress-vm-session.log`. Captures of the live queue at 900×600
and 1280×820 are in `results/release-stress-vm-{900,1280}.png`. Neither session
proves a nondeterministic crash cannot recur.

Follow-up root-cause probe: a disposable `gc.DEBUG_SAVEALL` harness disabled the
worker GC guard (without changing shipped source) and logged the objects that
would otherwise have been finalized. On **both host and VM**, a Python-backed
QThread's cyclic collection included a previous test's `Controller`, its
GUI-affine `QTimer`, `OmarchyPalette`, gallery model, editor, preview, and viewer
QObjects. Evidence: `results/probe-gc-host.log` and `results/probe-gc-vm.log`;
`results/probe-gc-selected.log` identifies the parented objects. This confirms
cross-thread collection of GUI-affine QObject cycles as a concrete unsafe
mechanism consistent with the native PySide/Qt crashes, not the exact native
receiver whose private pointer was corrupted in the historical core. The
SAVEALL probe deliberately retains garbage and had unrelated failures, so its
result is diagnostic, **not** a passing release test.

The mitigation now coordinates GC across all controllers rather than allowing
one to re-enable collection while another has a live worker. Desktop tests also
flush deferred deletes and collect orphaned Qt cycles on the GUI thread after
each case instead of letting the next worker collect them. The new multi-
controller regression test and desktop suite passed **39/39** on host and
**39/39** in an isolated VM Python 3.14/PySide6 6.11.2 environment:
`results/crash-rootfix-host-desktop.log` and
`results/crash-rootfix-vm-desktop.log`. A subsequent host full suite ran **342**
tests with **one** existing provider-version mismatch (`0.1.0` installed in
that development venv vs required `0.1.0rc1`); see
`results/crash-rootfix-host-full.log`. This reduces and directly addresses the
observed mechanism but does not mathematically rule out other Qt/native issues;
release acceptance still requires an explicit risk decision and final artifact
validation.

A *fresh host environment* installed the older sibling 0.1.0 wheel (SHA-256
`e84bb42dcaf39549e989417f3cb17091b46a0f01aea58e1d44aa483f2d3446e1`)
and Image Lab 0.1.0 wheel (SHA-256
`7e34b06c597ffc59546fe8964d383a6f1217e48293ad5a90a46922766716ca35`).
`pip check` passed, but a packaged editor smoke **failed** on the older
Imagescope API (`AnalysisRequest` has no `palette_size`); it also lacks
`MetadataRequest` and `inspect_metadata`. This is explicit evidence that
version metadata and `pip check` alone cannot close the dependency gate; see
`results/release-acceptance-current/{install,smoke}.log`. The current Image Lab
wheel paired with the development provider passed its packaged editor/export/
import smoke, including six copies and no QML warnings
(`results/release-acceptance-vm-package-smoke.log`). VM failure/keyboard-focused
editor/export tests passed **88/88** after supplying the test helpers path
(`results/release-acceptance-vm-failure-keyboard-2.log`). I visually checked the
captured editor and export dialog at 900×600 and editor at 1280×820 in
`results/editor-smoke/`; controls and modal actions were visible and reachable
in those captures/tests. These checks are not a manual screen-reader or HDR
certification, and the pixel-editing-during-analysis product decision is open.
The owned guest run was removed, workspace 1 restored and no guest clients or
system package changes remain.

Current Image Lab dependency correction (no Imagescope repository edits): the
project-local snapshot wheel is `imagescope-0.1.0rc1-py3-none-any.whl` (SHA-256
`7e71548c8b079d412487f2015f6673085c170100565f7208ae023ed76d7dc451`);
the rebuilt Image Lab wheel is SHA-256
`1be1d4521dd4ec8f421a6cf4da1253bbedf8863dda7e9f1b65a7753a0f40f246`.
The Image Lab wheel declares `imagescope==0.1.0rc1`, excluding the older
incompatible final-labelled wheel. A fresh project-local virtual environment
resolved both wheels normally and passed `pip check`, `imagescope info --json`,
and both `--help` entry points (`results/rc1-fresh-install.log`). The installed
wheel passed packaged six-format-copy editor/export/import acceptance with no
QML warnings (`results/rc1-packaged-smoke.log`), and the source suite using
this environment passed **337/337** (`results/rc1-fresh-full-suite.log`). This
closes the local version mismatch and makes development testing green; it does
not turn a copied dirty-source provider wheel into a published or independently
reproducible provider release. No tag or publish action was taken.

The owner approved MIT licensing, a CommonFIRE release destination and deferring
concurrent pixel editing. The local installer candidate is assembled with
`tools/build_release_bundle.py`; it checks both wheels' hashes and installs into
an isolated user environment, leaving existing launchers alone without an
explicit replacement flag. `tests/test_installer.py` checks checksum failure,
dry-run behavior and non-destructive launcher guards (4/4). An end-to-end run
in `results/installer-e2e/` replaced a disposable old symlink/desktop entry only
with approval, preserved their backups, passed dependency checks and the six-copy
packaged editor smoke, and reinstalled idempotently. The extracted tarball's
installer dry run passed. A later final-candidate tarball was installed from its
extracted contents into a second fresh user-local environment; dependency checks
and six-copy packaged editor acceptance passed (`results/installer-final/`).
The latest local candidate archive includes the Imagescope source snapshot
(58 files, MIT license, base revision `3696cab` plus the frozen working-tree
changes), wheel and manifest checksums. The source archive SHA-256 is
`a2102b8385dd54c0feb37a11e1d23d128ae3e0e040941ef7a3794217a73c1dbc`;
the bundle SHA-256 is
`fca769391a27e0c700184cb051eed02d1364dda7d7617397ae57359e1b8dab2f`;
the Image Lab wheel SHA-256 is
`eb204e09e56f14562874719e9eeb4aab00e89eab3dcf341e20c37eb0efd3b480`.
The final-candidate-v2 archive was extracted and installed in another fresh
project-local environment; dependency checks and six-copy packaged editor
acceptance passed (`results/installer-v2/`). These are local release-candidate
results, not evidence of a published org repository or an independently
released Imagescope artifact.

Previous development evidence (not a substitute for the fresh-wheel gate):
`docs/EDITOR_IMPLEMENTATION.md` S12–S13 and `results/stabilization-package/`.
