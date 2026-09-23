# Image Lab

A small local experiment for wallpaper tagging and measurable image properties.
The CLI never edits, renames, or moves originals and creates no database,
embeddings, sorting, model downloads, or network services. The optional Qt Quick
desktop interface adds a local SQLite catalog, thumbnail cache, and explicitly
confirmed same-folder file renaming. Scanning and analysis leave originals untouched.

## Setup

Linux and Python 3.11+ are required. Imagescope is a separate dependency, not
currently published to PyPI. With its checkout next to this one at `../imagescope`:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e ../imagescope -e '.[desktop]'
.venv/bin/imagescope --help
.venv/bin/image-lab --help
```

For a headless installation using only `image-lab`, use `-e .` instead.
The editable Imagescope installation picks up changes from its separate checkout;
there is no bundled analyzer or fallback. Always launch Image Lab with this Python
environment. Existing processes must be restarted after upgrading.

Image Lab pins `imagescope==0.1.0` because it currently uses internal decoder and
validation helpers as well as the versioned CLI protocol. For non-development
installs, install a matching Imagescope wheel before the Image Lab wheel.
`python tools/build_packages.py --sdist` now builds Image Lab only (pip and
setuptools 68+ must already be installed).

Analyzer dependencies are Pillow and NumPy. A standard 64-bit difference hash is implemented
locally, so ImageHash is not required. Dependency installation is an explicit setup
step, not something the CLI does automatically.

## Standalone analyzer

```sh
.venv/bin/python -m imagescope describe image.jpg --profile wallpaper --json
.venv/bin/python -m imagescope inspect image.jpg --json
.venv/bin/python -m imagescope info --json
```

`imagescope` is the installed command. It accepts file paths or encoded images
through stdin, with no Qt, database, folder scanner, or persistent queue. See
`docs/ANALYZER.md` and `docs/ANALYZER_PROTOCOL.md` for installation, limits,
resource policy, and the versioned result/event contract.

The desktop launches it via a subprocess in its worker thread, without shell
interpolation, and translates successful results into the existing catalog format.
Bounded, nonblocking pipe reads and GIL-releasing waits keep Python-backed QML
bindings responsive while the analyzer runs. The desktop still owns job
selection, source fingerprints, retries, persistence, and queue progress. It
rejects incomplete/malformed streams and incompatible protocol versions. No
personal database migration is required. `image-lab-ui` launches the desktop.
The `image-lab` CLI (e.g. `image-lab analyze`) remains a compatibility wrapper
over the same core operation.

## Local UI control

A running `image-lab-ui` exposes a private, per-catalog Unix socket. Use the same
Python environment to control it without simulating clicks:

```sh
.venv/bin/image-lab ctl status --json
.venv/bin/image-lab ctl window focus
.venv/bin/image-lab ctl library list --limit 20
.venv/bin/image-lab ctl viewer open 12
.venv/bin/image-lab ctl analyze --ids 12 34 --json
.venv/bin/image-lab ctl events --json
```

Pass `--data-dir` for a non-default catalog; the client never starts a GUI or
creates a catalog automatically. Long operations return IDs for
`image-lab ctl operation wait ID`. Use `image-lab-ui --no-ipc` to disable control.
Restart older GUI processes after upgrading.

See `docs/IPC.md` for usage and safety, `docs/IPC_PROTOCOL.md` for the wire contract,
and `docs/IPC_PLAN.md` for the implementation plan and verification record.

## Desktop contact sheet (PySide6 / QML)

Install the optional desktop dependency into the project virtual environment:

```sh
.venv/bin/python -m pip install -e '.[desktop]'
.venv/bin/image-lab-ui
```

After installing both projects and PySide6 into the same environment, launch
from the project root using that environment's Python:

```sh
.venv/bin/python -m image_lab_ui.app
```

Choose a small folder first. The app recursively indexes supported images in a
background thread, caches thumbnails, and displays a virtualized contact sheet.
Select a tile and click **Generate tags** to run the existing local Ollama model.
Search matches file paths and saved model predictions. Only one scan or analysis
runs at a time; the UI remains available while it works. A central queue bar shows
the active filename, elapsed time, and actual analysis stage. The image sidebar
shows only that image's queued/analyzing/complete/failed state and saved results.
Scans can be stopped;
analysis finishes its current request before ordinary window close (request
timeout up to five minutes, plus a small process-shutdown allowance). OS-level
quit interrupts the client; Ollama may still finish already submitted work.
Browsing existing results does not require Ollama.

To forget an image, right-click its tile and choose **Remove from library…**,
or select it and use the same action in the sidebar. For multiple images, Ctrl-click tiles (or use **Select all**) and choose
**Remove selected…**. Both actions ask for confirmation. Originals stay on disk;
their catalog records, saved tags, edits, and analysis history are removed.
Scanning the folder again adds them back without the old details. Disposable
thumbnail cache files are retained. Finish active work and remove affected images
from the analysis queue before removing them from the library.

Double-click a tile to open the full-image viewer. **File info** uses Imagescope's
public metadata-v1 API in a cancelable background process: format, stored/oriented
dimensions, mode, declared transparency, ICC identification, sequence details,
source digest, and structured warnings. File size, modification time, and location
remain visible. Unknown frame counts, profile details, and EXIF values stay unknown;
header inspection does not validate the pixel stream or establish edit eligibility.
**Refresh** reloads the current source; stale navigation/load results are discarded.

Metadata-v1 exposes top-level EXIF only. Nested lens/capture/exposure fields and DPI
are unavailable through this provider; omitted rational values remain unknown.
There is no secondary Pillow reader or silent fallback. A compatible Imagescope
installation exposing `MetadataRequest` and `inspect_metadata` is required; missing
APIs and unsupported contract versions appear as errors, without auto-installing
anything. The accepted development-provider snapshot is recorded in
`docs/IMAGESCOPE_COORDINATION.md`.

**Library notes** keeps generated descriptions, tags, and saved corrections separate
from these facts, including when the original is missing or inspection fails.
Inspection never modifies originals, converts colors, runs inference, or displays
GPS fields. Existing analysis and viewer rendering behavior are unchanged.

The viewer's **Measures** tab runs Imagescope's existing read-only `inspect`
measurements on demand, without a model call or writing Library notes. It displays
the provider's palette, luminance, and transparency data—not a second palette
extractor. Color policy, algorithm/preprocessing versions, source digest, working
raster dimensions, alpha handling, and sampling limits remain visible. Results
are bound to the original source and current load; navigation, close, and source
revision changes discard stale work.

This slice uses unchanged `legacy-v1` preparation: the measurements are unmanaged,
not verified against the viewer's colors. **Preview/measurement color agreement
remains a gate before color-guided adjustments.** Palette shares are approximate;
working-image visibility bounds are not exact original-pixel crop coordinates.
Only the first frame is measured. These are readouts, not editing controls.

Pixel editing (crop, rotate/flip, resize, and safe copy export) is described
in `docs/EDITOR_PLAN.md`. Imagescope dependencies and pending handoffs are recorded
in `docs/IMAGESCOPE_COORDINATION.md`. The internal recipe/render foundation,
isolated snapshot/render worker, and shared color-preparation core are implemented
and tested; progress is recorded in `docs/EDITOR_IMPLEMENTATION.md`. The worker now
supports opt-in managed color with validated provenance and ICC transport. A tagged
Qt preview bridge and original-measurement alignment are fixture-verified.

Choose **Edit image** in the full-image viewer for a **geometry editing workbench**:
numeric crop bounds, original-ratio/square/4:3/3:2/16:9/9:16/21:9 presets,
rotate/flip, aspect-locked pixel resize, explicit upscale consent, undo/redo/reset,
and original comparison. Output dimensions are shown in the size controls; the
header explains when pending changes or original comparison prevent export. Untagged
RGB/RGBA inputs use sRGB by convention, with a nonblocking notice—no confirmation
is needed. Originals remain untouched; exported copies are deliberately tagged sRGB.
Embedded profiles and PNG sRGB declarations take precedence, and broken profiles or
unsupported modes still fail closed. Turning off the untagged sRGB interpretation
shows a bounded unmanaged reference until you re-enable it. Preview failures are
shown on the canvas, not just in the sidebar. Enter applies numeric fields. **Drag crop**
lets you draw a selection, resize corners, or move inside it; arrow keys nudge it
by one source pixel (Shift: ten). Apply commits one undo step and clears resize;
Escape cancels the staged crop. It trims the current preview—use numeric bounds or
Reset to expand a previous crop. Outside drag mode, Escape or Back to image uses a
revision-bound discard dialog, including un-applied fields/selections. Apply or
revert pending fields before other geometry commands.

**Export copy…** writes PNG, JPEG or WebP from the full-resolution source, never
from the preview. PNG/WebP preserve alpha; JPEG requires an explicit `#RRGGBB`
matte for RGBA input. Outputs are deliberately tagged sRGB and strip EXIF/GPS/XMP.
Choose an existing, non-symlinked destination folder and a new filename: originals,
existing files and missing-but-catalog-reserved paths are never overwritten.
Unsupported safe-publication facilities/filesystems fail closed. Encoding is capped
at 60 seconds, 40MP and 192 MiB of encoded output; kernel filesystem I/O/reaping can
still delay cancellation. A commit that wins a cancellation race remains a saved copy.

**Add the saved copy to my library** is off by default. Import keeps the original
selected, preserves filters, and creates ordinary library metadata—not cloned AI
notes. If import fails, the saved copy stays on disk and **Import saved copy** retries
after verifying its identity/content. Warnings or uncertain publication explicitly
require inspection; they never advance the saved checkpoint. Successful confirmed,
synced export records the exact recipe/color interpretation, so later edits become
dirty again. Undo history is still session-only; no persistent draft is created.

The editor's **Original measurements…** uses managed Imagescope inspection, with
source digest/profile/policy and editing-revision checks. It never labels whole-source
values as edited-image statistics. Rapid edits cancel/stale-reject inspection; preview
and export have priority. The separate viewer **Measures** tab stays legacy/unmanaged.
No color-guided adjustments, regional measurements or histograms are enabled.

Keyboard: Ctrl+Z / Ctrl+Y or Ctrl+Shift+Z for recipe history outside text fields;
Ctrl+Shift+S for Export copy; Escape closes the current dialog or cancels drag before
leaving editing. Text fields keep their native undo. Numeric alternatives, accessible
control names, and the two supported layouts/DPRs have automated coverage; this is
not screen-reader, monitor-profile or HDR certification.

Finish or clear queued work before entering. While editing, conflicting library,
queue, settings, navigation and IPC actions are blocked; read-only IPC inspection
remains available. A normal window-close request closes a clean editor automatically,
or asks about unsaved edits. Active work gets a visible wait/close dialog; queued
items are preserved when paused. After confirmation and worker completion, the
window closes without a second request. Keep editing/Keep open cancels that request. Software/fixture color and
packaged export/import acceptance are recorded in `docs/EDITOR_IMPLEMENTATION.md`.
The latest full-suite run passes all 335 tests, plus fresh packaged export/import
checks at both supported layouts and display scales. The earlier native crash has
not reproduced and is not claimed fixed. A Qt-property teardown warning also
reproduces without Image Lab; see the implementation record for remaining limits.

Large images use a bounded working preview rather than being rejected above
25 megapixels. JPEGs shrink during decoding; other formats decode in a separate,
memory/time-limited process. Originals and their catalog dimensions are preserved.
See `docs/ANALYZER.md` for the remaining safety ceilings and preprocessing details.

The desktop defaults to Qt Quick software rendering so browsing does not compete
with inference for the GPU. Set `QT_QUICK_BACKEND=rhi` before launch to opt into
hardware rendering. Analysis updates only changed tile roles; batch progress
reserves its layout space between jobs to avoid shifting the image grid.

Desktop data is personal user state, independent of the checkout or launch directory:

- Database: `$XDG_DATA_HOME/image-lab/catalog.sqlite3`, normally
  `~/.local/share/image-lab/catalog.sqlite3`.
- Disposable thumbnails: `$XDG_CACHE_HOME/image-lab/thumbnails/`, normally
  `~/.cache/image-lab/thumbnails/`.
- Reserved preferences location: `$XDG_CONFIG_HOME/image-lab/`, normally
  `~/.config/image-lab/`. No preferences file is currently created; UI preferences
  are stored alongside the catalog in SQLite.

Unset or relative XDG values use the standard home-directory defaults. An explicit
`--data-dir` keeps a development/test catalog self-contained, including thumbnails,
unless `--cache-dir` is also supplied. For an explicit location or initial folder:

```sh
python -m image_lab_ui.app --data-dir ./results/desktop --folder ~/Wallpapers/pixel
```

To migrate a development catalog once, close all Image Lab windows and run:

```sh
python -m image_lab_ui.migrate --source ./results/desktop
```

Migration uses SQLite's backup API (including committed WAL data), copies cached
thumbnails, rewrites their paths, and preserves predictions and batch history.
It keeps the source as a backup and refuses to replace an existing destination
catalog or conflicting cached file. Both catalogs are locked during migration.
A failed migration never overwrites the source. Missing thumbnails can be rebuilt
by rescanning the original folder without losing unchanged images' predictions.
The CLI's experimental JSONL results stay wherever `--output` specifies.

The catalog remembers paths, dimensions, source modification time/size, analysis
metadata, and predictions. Reimporting the same folder does not duplicate rows.
A changed source invalidates its previous prediction on rescan; analysis refuses
to attach results if the source changed. A failed retry preserves previous good
predictions and displays the new error. Scanning and analysis remain read-only;
renaming requires an explicit confirmation.

This is not a full organizer yet: no move/delete actions or automatic folder
watching. Removed sources remain in the catalog; old cache files are not yet
garbage-collected. Qt model rows load in pages of 120, the grid creates only nearby
tiles, previews are size-bounded, and inference is on demand. Large-library
performance and memory use still need profiling.

### Omarchy appearance

Image Lab reads the active Omarchy `colors.toml` and updates its palette live,
including the gallery, sidebar, queue, controls, and dialogs. The integration is
an internal `OmarchyPalette` component—not an external theme manager or plugin.

Omarchy 4's `~/.local/state/omarchy/current/theme/colors.toml` takes precedence
over the legacy `~/.config/omarchy/current/theme/colors.toml`; absolute
`XDG_STATE_HOME` / `XDG_CONFIG_HOME` overrides are also recognized. The app reopens
the logical path every 500ms, so directory replacements and symlink swaps are
picked up without requiring hooks or modifying Omarchy configuration.

Theme updates only change colors, not the gallery model, selection, scroll
position, or running queue. Incomplete/malformed palettes and the brief missing
path during a theme switch retain the last good colors. Without an available
Omarchy palette at startup, Image Lab uses its built-in fallback. Both light and
dark palettes are supported. The folder chooser uses Qt's themed dialog rather
than a separate native-platform appearance.

### Library filters

**All images**, **Needs tags**, **Tagged**, and **Failed** filter the gallery
alongside filename/tag search. Counts follow the search across the whole catalog,
not just loaded tiles, and update as analysis finishes. **Failed** includes failed
regeneration with preserved tags, so it can overlap **Tagged** or **Needs tags**.

Switching filters clears the current checkboxes, not queued work. **Select all**,
**Generate selected**, and **Generate missing** respect the current search/filter.
Use **Needs tags → Select all → Generate selected** to fill gaps; for failed
regeneration with saved tags, use **Regenerate…** or **Retry** in the queue.

### App menu

The top-right **☰ App menu** provides **Choose folder…**, **View queue**,
**Settings…**, **About Image Lab**, and **Quit**. It supports mouse and keyboard navigation.
Folder import follows the same availability rules as the toolbar button, and
Quit uses the normal close guard rather than interrupting active work.

### Settings

Open **App menu → Settings…** to control GIF autoplay in the expanded viewer and
sidebar, and contact-sheet animation on hover. All three are enabled by default.
With autoplay off, the sidebar and contact sheet show still frames; the expanded
viewer starts paused and its **Play GIF** button still works.

**Save settings** applies changes immediately and remembers them in the current
catalog's SQLite database across launches. **Cancel** discards the draft. Failed
saves keep the panel open and leave the active preferences unchanged. Separate
`--data-dir` catalogs keep separate preferences. Settings do not change originals,
saved image metadata, or analysis behavior.

### Expanded image viewer

Single-click a tile to inspect it in the sidebar as before. **Double-click** a tile,
or **right-click → Open**, to open a full-window viewer inside Image Lab. **Enter**
also opens the focused gallery tile. The image fits the available space without
cropping, alongside a scrollable details panel with the description, wrapping tag
chips, medium, mood, composition, detection flags, and source path. Saved user
corrections are reflected here too.

Use **Back to library** or **Escape** to return without resetting the gallery's
scroll position, search/filter, or batch checkboxes. The viewer stays on the opened
image even when background catalog updates change the gallery selection. It loads
a bounded, asynchronous preview (up to 4096 pixels per axis for stills, 2048 for
GIFs), rather than a full resolution zoomable editor; closing it releases the image source. Missing originals
show an error while retaining their saved details. Viewing is read-only.

### Animated GIFs

By default, existing catalog entries ending in `.gif` (case-insensitive) play
automatically in the sidebar and expanded viewer—no reimport is needed. The expanded viewer offers
**Pause GIF / Play GIF**. GIFs retain their encoded frame timing and loop behavior.

Contact-sheet tiles keep their cached still thumbnail until hovered, then play a
512-pixel-bounded preview. A **GIF** label identifies them. Leaving a tile unloads
its animation; opening the expanded viewer unloads tile and sidebar animations to
avoid redundant playback. Closing the viewer releases its animation and restores
the sidebar preview. Decoded GIF frames are not cached en masse, though unusually
large or complex GIFs can still be expensive to decode.

This is display-only support: it does not change originals, rebuild thumbnails,
or turn image analysis into temporal/video analysis.

### Editing image details

Select an analyzed image and choose **Edit details**. An image reference stays
beside your draft. **Description & tags** contains the caption and removable tag
chips; **Mood & details** holds medium, mood, composition, and writing/watermark
flags. Enter or comma adds an entry; pasted comma- or newline-separated lists
are supported. Remove a chip with its × button. Blank entries and case-insensitive
duplicates are removed.

**Save changes** or **Ctrl+Enter** commits both tabs, including entries still being
typed. **Cancel** discards the entire draft. Failed saves retain the draft and show
an error above the fixed action bar. Fields scroll on smaller windows, with Save
and Cancel always available. The editor follows the current light or dark palette.

Corrections are stored separately in the local catalog, not in the image file or
original model response. The sidebar marks edited results; search and filename
suggestions use the corrected values. Regenerating analysis preserves corrected
fields while updating fields you haven't changed. Saving an empty description or
list explicitly clears that field. Existing catalogs gain the edits column
automatically without losing saved results.

Editing is blocked during active work or while the image is queued. Stale drafts
are rejected if the source or saved metadata changed. An unchanged rescan (including
thumbnail rebuilding) preserves corrections; rescanning a changed source resets
both analysis and corrections to avoid attaching old details to different content.
Current search/filter settings stay active, so saving corrections may remove the
image from those results; its details remain selected in the sidebar.

### Filename suggestions

Select an analyzed image and click **Suggest names** in the image sidebar.
Image Lab builds up to five distinct filename ideas locally from its saved caption,
tags, mood, and medium. No model request or image reanalysis is needed. Sparse
metadata may produce fewer suggestions; missing descriptions and tags show a
prompt to generate tags first.

Pick a suggestion and optionally edit it. **Copy name** only copies to the
clipboard. **Rename file…** opens an old-name/new-name confirmation; choose
**Rename file** there to change the actual file. Generated options use lowercase,
hyphen-separated words. Renaming requires the original extension and directory,
refuses existing destinations (including symlinks), and preserves the catalog ID,
thumbnail, saved tags, and selected image. The current search and filter remain
active, so an image renamed out of a filename search may leave the gallery results.

Renaming is blocked during active scanning/analysis/submission and while the image
is queued. Changed or missing sources must be rescanned first. Catalog path
conflicts are rejected even if the corresponding file is missing. When a name is
taken, the conflict dialog offers an available numbered variant (such as
`misty-forest-2.jpg`), skipping existing files, directories, symlinks, and catalog
paths. **Use this name…** opens a fresh confirmation; it does not rename yet.
Availability is checked again at confirmation, so another file appearing in the
meantime is never overwritten. Already-numbered names continue the sequence.
The lookup tries up to 1,000 variants; if none is available, choose a name manually.
Supported systems use an atomic no-overwrite rename (Linux `renameat2`, or Windows rename);
other platforms/filesystems fail safely rather than replacing an existing file.
If the catalog update fails, Image Lab attempts to restore the old filename and
reports any restoration failure with the paths involved. Filesystem and database
changes are not one crash-atomic transaction: after a process/power failure during
renaming, restore the old filename or rescan the folder if needed. There is no
automatic undo history yet.

### Analysis queue

- **Generate tags** on one image and multi-image actions feed the same serial
  queue. Add more work while analysis runs; duplicate waiting/running images are
  skipped. Submissions (including analyzer metadata lookup) run off the UI thread.
- Check thumbnail boxes, Ctrl-click tiles, or press Space on the focused tile.
  **Select all** selects all current search results, including unloaded pages.
  Changing search clears checkboxes, not queued work.
- **Generate selected** queues checked images without saved predictions.
  **Generate missing** queues all missing predictions in the current search,
  including unloaded pages. **Regenerate…** confirms replacement of selected AI
  results. Good predictions survive failed regeneration.
- The fixed-height queue bar below the library shows the current image, stage,
  elapsed time, waiting count, and completions/failures for the current run.
  Its progress bar includes removed jobs as terminal, never as successful.
  New requests join the active run; a new run begins after the previous one ends.
- **View queue** opens a drawer without resizing the gallery. Running and waiting
  images appear first, followed by recent history, with 50 entries per page.
  **View image** inspects a result without following the analyzer automatically.
- **Pause after current** saves the in-flight result, then waits. Adding work to a
  paused queue does not resume it. **Resume** continues (or cancels a pending pause).
  **Remove** cancels one waiting image; **Clear waiting** confirms clearing all
  pending work. Neither interrupts the current image or deletes saved results.
- Failures do not stop the queue. Failed entries show their error and a **Retry**
  action using current source metadata, model, and prompt. Older failed attempts
  cannot be retried again once a newer attempt exists.
- Pause and wait for the current image before closing to resume later. Folder
  scanning is unavailable while analysis is running or waiting.

Jobs persist source modification time/size, model, prompt/version, state, elapsed
time, and errors. Prediction saves and successful job completion commit together.
After an interrupted run, unfinished work is paused and offered for explicit
resume. Changed source files or analyzer settings fail safely rather than silently
attaching results to a different version; rescan/retry as appropriate. Only one
queue has pending work, and duplicate active image jobs are prevented.
A catalog lock prevents two current desktop instances from executing its queue.
Close any older pre-queue app windows before starting this version.

Inference stays serial and keeps the model warm between images; Ollama's existing
five-minute keep-alive allows unloading afterward. Browsing and image selection
stay independent of the running job; detailed progress lives in the queue.
No automatic retries, parallel inference, or model downloads occur.

## Start with pixel analysis

```sh
mkdir -p results
.venv/bin/image-lab analyze ~/Wallpapers --limit 30 --output results/pixels-01.jsonl
```

Directories are scanned recursively; the limit selects the first files in sorted
absolute-path order, not a representative random sample. For a balanced test,
supply individual paths from different styles instead. Symlinks to image files
are resolved; originals are only read. Output paths must have an existing parent.
Existing output files are refused, including if the output names an input file.

Measurements:
- EXIF-oriented dimensions, aspect ratio, source format and frame count
- SHA-256 of original bytes for exact duplicates
- Six-color thumbnail palette with approximate pixel fractions
- Mean and standard deviation of linear sRGB relative luminance (0–1)
- 64-bit difference hash for near-duplicate candidates (compare Hamming distance)
- 3×3 edge-density grid, top-to-bottom and left-to-right, as a busyness heuristic

Animated images use the first frame. Transparency is composited onto white for
both analysis and model input; the presence of an alpha channel is recorded.
Color management/ICC conversion is not implemented: luminance assumes sRGB.
Palette and edge measurements are approximate. Difference hashes are not reliable
for cropped or rotated matches and are not proof that files are duplicates.

## Check Ollama, then enable vision

```sh
.venv/bin/image-lab doctor
```

This only queries the loopback Ollama API. An empty loaded-model list does not
establish whether GPU acceleration works. During an actual vision run, inspect
`ollama ps` in another terminal and check GPU memory/backend information. The
RX 6600-series backend and available VRAM need verification on Wintermute.

When ready, explicitly download the model (several GB):

```sh
ollama pull qwen3-vl:4b
.venv/bin/image-lab analyze ~/Wallpapers --vision --limit 30 --output results/qwen-01.jsonl
```

Images go only to `127.0.0.1:11434`, never to a hosted inference API. The model must
already be installed. The harness processes one image at a time, supplies a JPEG
preview bounded to 768×768 by default, requests thinking off, and uses a
4096-token context and 1024-token output budget. Use `--preview-size 1024` for
more detail; supported sizes are 256, 512, 768, and 1024. GPU fit and throughput
are not guaranteed.

On the tested Ollama 0.20.6 / qwen3-vl:4b combination, `think: false` alone did
not reliably suppress thinking. The harness now supplies the full schema in the
prompt and prefills the assistant response with `{"caption":`, then validates
the continuation. Complete JSON responses are accepted too. Other models may
handle assistant prefilling differently and need their own smoke test. Thinking
text is never used as a substitute for a final answer.

The `wallpaper-v2` prompt favors short, visible-content labels and spatial
composition terms. `text_present` includes unreadable writing-like glyphs and
non-Latin lettering; it is not OCR. A central logo alone is not treated as a
watermark. These remain model predictions, not guarantees. Label arrays are
lowercased, whitespace-normalized, and exact duplicates/empty labels removed.
When cleanup changes output, the original validated prediction is retained as
`vision_raw`. Synonyms and questionable claims are not silently rewritten.

Each JSONL record includes pixel measurements, validated model output or an error,
elapsed time, and—in vision mode—the model digest, Ollama version, prompt, and
Ollama load/evaluation timing fields. Records also capture request settings,
actual preview dimensions, stop reason, and thinking-character count. Invalid
responses retain timing and raw final content, but not raw thinking. Exhausted
token budgets and empty final answers produce explicit errors; no automatic
retry hides failures. The `*_duration` timing values are nanoseconds, while
`eval_count` and `prompt_eval_count` are token counts. Medium uses a controlled vocabulary;
subjects, mood, lighting, composition and tags are currently free-form labels.
Model predictions, especially watermark detection, are not verified facts.
Interrupted runs retain completed records. Per-image errors are recorded and
produce a nonzero exit status. Run-wide setup errors stop before opening output.

## Evaluate

Use 30–50 varied photos, illustrations, anime, abstract images, dark scenes, and
images with text. Review caption accuracy, tag usefulness, and errors. Separate
first-load latency from warm runs using `load_duration`; all Ollama durations are
nanoseconds. Peak GPU memory is not sampled by this scaffold and should be checked
externally. Do not automatically act on generated labels.

## Initial local smoke test

Three wallpapers were tested on Ollama 0.20.6 with qwen3-vl:4b. Ollama reported
100% GPU placement and about 4.6 GB of model VRAM allocation (not peak GPU usage).

| Image | Original 1024px harness | Tuned 512px | Tuned 1024px |
| --- | --- | --- | --- |
| Purple abstract waves | 87.7s | 10.5s | 14.2s |
| Anime illustration | failed after 78.8s | 10.8s | 17.1s |
| Rocky ocean scene | 70.9s | 8.9s | 15.8s |

Both tuned runs produced three schema-valid records with no reported thinking.
The original first image included about 9.9s of model loading; tuned runs used a
warm model. These are single-run observations, not a general benchmark. The
smaller-preview-only experiment still failed: the JSON continuation and explicit
schema were important for reliability, not just the resolution change.

Captions identified the main content reasonably well. Labels still need review:
the illustration's writing-like symbols were not flagged as text, and mood and
composition labels can be subjective or redundant. Three images are not enough
to establish sorting accuracy. Local records live in `results/`.

## Current evaluation

The current 768px default preserved pixel-art detail that the 512px trial missed.
With the `wallpaper-v2` prompt, seven development wallpapers plus three held-out
wallpapers all returned valid JSON with no reported thinking. Warm runs took
8.0–9.0 seconds, median 8.48 seconds. The held-out images were not used to tune
the prompt. This is a small local smoke test, not a general accuracy benchmark.

Manual review found useful main-subject captions across photography, abstract,
anime, flat illustration, rendered art, and pixel art. Both writing-bearing
development images were flagged as text; the central logo was not called a
watermark. There was no positive watermark example in this set, so watermark
recall is untested. Remaining issues include redundant synonyms, occasional
colors/backgrounds in subjects, ambiguous artistic medium, and soft prompt
limits being exceeded. Schema maxima remain hard limits; prompt preferences
are not silently enforced by truncating predictions.

See `EVALUATION.md` for the reviewed samples and limitations. Local raw results:
`results/final-v2-768.jsonl` and `results/holdout-v2-768.jsonl`.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests use generated images and mocked Ollama responses. No model or running server
is required. Test temporary files are confined to this project directory.
