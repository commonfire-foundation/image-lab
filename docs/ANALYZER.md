# Imagescope integration

Image Lab consumes the standalone `imagescope==0.1.0rc2` distribution. It no longer
ships or builds an internal analyzer. With sibling checkouts, install both into
the same environment:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e ../imagescope -e '.[desktop]'
.venv/bin/python -m pip check
.venv/bin/python -m imagescope info --json
.venv/bin/image-lab-ui
```

The desktop starts `[sys.executable, '-m', 'imagescope']`; this is not resolved
through a separate CLI on PATH. Catalog thumbnail decoding and the legacy CLI
also import Imagescope from that same interpreter. The version is pinned because
these consumers currently use internal decoder, profile, and validation helpers.
Do not upgrade that pin without running the integration suite.

Imagescope's `README.md` and `PROTOCOL.md` are authoritative for backend commands,
limits, privacy, model requirements, and protocol behavior. In the usual sibling
layout they are at `../imagescope/README.md` and `../imagescope/PROTOCOL.md` relative
to the project root. `inspect` does not require Ollama; descriptions do.

Image Lab owns catalog state, thumbnails, queues, process supervision, result
validation at the consumer boundary, and legacy-record translation. Backend-only
tests live in Imagescope; Image Lab retains desktop and integration tests.

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
  .venv/bin/python -m unittest discover -s tests -v
```

No database migration is required. Existing queued jobs keep their protocol and
prompt guards. Restart running Image Lab processes after changing the installation.
