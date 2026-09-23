"""Fake executable for process-boundary tests; never contacts a model."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from imagescope.cli import info
from imagescope import AnalysisRequest, AnalyzerError, analyze
from imagescope.profiles.wallpaper import PROMPT_VERSION

parser = argparse.ArgumentParser()
parser.add_argument('--mode', default='success')
known, _ = parser.parse_known_args()
if 'info' in sys.argv:
    if known.mode == 'slow-info':
        time.sleep(1.5)
    if known.mode == 'bad-info':
        print('unavailable')
        raise SystemExit(1)
    print(json.dumps(info()))
    raise SystemExit(0)


def emit(kind, **fields):
    print(json.dumps({'protocol_version':1, 'type':kind, **fields}), flush=True)


if known.mode == 'crash':
    import os
    os._exit(7)
if known.mode == 'garbage':
    print('not json', flush=True)
    raise SystemExit(0)
if known.mode == 'incompatible':
    print(json.dumps({'protocol_version':999,'type':'hello','schema_version':1}), flush=True)
    raise SystemExit(0)
emit('hello',schema_version=1)
if known.mode == 'hang':
    time.sleep(60)
if known.mode == 'truncated':
    print('{"type":', end='', flush=True)
    raise SystemExit(0)
if known.mode == 'flood':
    print('x' * (2*1024*1024),flush=True)
    raise SystemExit(0)

path = Path(sys.argv[sys.argv.index('describe')+1])


class Backend:
    def check_model(self, model):
        if known.mode == 'offline':
            raise AnalyzerError('backend_unavailable','Ollama offline')
        return {'name':model,'digest':'test'}, {'version':'test'}
    def describe(self, image, model, preview_size, *, profile):
        if profile != 'wallpaper':
            raise AnalyzerError('invalid_request', 'Fake backend expects the wallpaper profile')
        if known.mode == 'slow':
            time.sleep(2)
        if known.mode == 'fail-one' and path.name == 'batch-0.png':
            raise AnalyzerError('invalid_response','bad JSON')
        return {'caption':'Red', 'subjects':[], 'medium':'abstract', 'mood':[], 'lighting':[],
                'composition':[], 'tags':['red'], 'text_present':False, 'watermark_present':False}, {}


if '--expect-profile-version' in sys.argv and sys.argv[sys.argv.index('--expect-profile-version')+1] != PROMPT_VERSION:
    from imagescope.contracts import empty_result
    result=empty_result(AnalysisRequest(path))
    result['error']={'code':'analyzer_changed','message':'Analyzer changed since queuing; retry with the current model/prompt'}
else:
    result=analyze(AnalysisRequest(path, measurements=True), backend=Backend(),
                   on_progress=lambda stage,label:emit('progress',stage=stage,label=label))
if known.mode == 'wrong-path': result['input']['path']='/other/image.png'
emit('result',result=result)
if known.mode == 'duplicate': emit('result',result=result)
if known.mode == 'nonzero': raise SystemExit(7)
raise SystemExit(0 if result['status']=='ok' else 1)
