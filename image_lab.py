"""Compatibility CLI/API for the original Image Lab experiments.

New consumers should use imagescope or the imagescope command.
"""
import argparse
import json
from pathlib import Path
import sys

from imagescope import AnalysisRequest, AnalyzerError, analyze
from imagescope.contracts import DEFAULT_MODEL as MODEL, DEFAULT_ENDPOINT as API
from imagescope.images import EXTENSIONS, prepare_image
from imagescope.measurements import measure
from imagescope.profiles.wallpaper import (MEDIA, SCHEMA, PROMPT_VERSION, VISION_PROMPT,
                                              validate_description, clean_description)
from imagescope.backends.ollama import OllamaBackend, VisionResponseError, JSON_PREFIX
from image_lab_ui.records import legacy_record


def api(endpoint, payload=None):
    return OllamaBackend(API).request(endpoint, payload)


def inspect_image(path):
    metadata, image = prepare_image(Path(path))
    metadata.update(measure(image))
    return metadata, image


def describe_image(image, model, preview_size=768):
    return OllamaBackend(transport=api).describe(image, model, preview_size)


def discover(inputs):
    files = set()
    for text in inputs:
        path = Path(text).expanduser()
        if path.is_dir():
            files.update(p.resolve() for p in path.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS)
        elif path.is_file():
            files.add(path.resolve())
        else:
            raise ValueError(f"Input does not exist: {path}")
    return sorted(files)



def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'ctl':
        from image_lab_ui.control_cli import main as control_main
        return control_main(argv[1:])
    parser = argparse.ArgumentParser(description='Compatibility Image Lab CLI; new integrations can use imagescope')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('ctl', help='Control a running Image Lab GUI (ctl --help)')
    sub.add_parser('doctor', help='Read Ollama inventory and loaded-model reports')
    command = sub.add_parser('analyze', help='Analyze files or recursively scan directories')
    command.add_argument('inputs', nargs='+')
    command.add_argument('--vision', action='store_true')
    command.add_argument('--model', default=MODEL)
    command.add_argument('--preview-size', type=int, choices=[256,512,768,1024], default=768)
    command.add_argument('--output', type=Path, required=True)
    command.add_argument('--limit', type=int, default=30)
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor':
            print(json.dumps({'version':api('version'), 'installed':api('tags'), 'loaded':api('ps')}, indent=2))
            print('GPU acceleration is not verified by inventory alone; inspect loaded size_vram during inference.', file=sys.stderr)
            return 0
        if args.limit < 1:
            raise ValueError('--limit must be at least 1')
        files = discover(args.inputs)[:args.limit]
        if not files:
            raise ValueError('No supported images found')
        backend = OllamaBackend(transport=api)
        if args.vision:
            backend.check_model(args.model)  # Preserve preflight-before-output behavior.
        errors = 0
        with args.output.open('x', encoding='utf-8') as output:
            for index, path in enumerate(files, 1):
                print(f'[{index}/{len(files)}] {path.name}', file=sys.stderr)
                # Each image gets a fresh deadline; the checked identity is reusable.
                current = OllamaBackend(transport=api)
                current.identities.update(backend.identities)
                result = analyze(AnalysisRequest(path, task='describe' if args.vision else 'inspect',
                    model=args.model, preview_size=args.preview_size, measurements=True), backend=current)
                record = legacy_record(result, path)
                if result['status'] != 'ok':
                    errors += 1
                    print(f"  Could not complete: {record['error']}", file=sys.stderr)
                output.write(json.dumps(record) + '\n')
                output.flush()
        print(f'Saved {len(files)} records to {args.output}; {errors} failed.', file=sys.stderr)
        return 1 if errors else 0
    except (OSError, ValueError, AnalyzerError) as exc:
        print(f'Cannot proceed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
