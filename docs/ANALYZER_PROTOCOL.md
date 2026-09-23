# Analyzer protocol ownership

The authoritative versioned result/event contract is `PROTOCOL.md` in the
standalone Imagescope repository (`../imagescope/PROTOCOL.md` from this project's
root in the sibling-checkout layout).

Image Lab currently consumes protocol 1 and schema 1 through
`image_lab_ui/analyzer_client.py`. It launches `python -m imagescope`, checks
model/profile/prompt identity, bounds output, validates terminal results and exit
codes, and rejects malformed or incomplete streams. See `tests/test_analyzer_process.py`
for consumer-side failure, timeout, and cancellation coverage.

Do not maintain a second backend protocol specification in this repository.
