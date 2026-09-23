"""Human/JSON CLI for the running UI; no Qt imports or catalog writes."""
import argparse
import json
import math
import sys
import time

from .ipc_client import Client, instances
from .ipc_protocol import ControlError, decode
from .storage import storage_paths


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--data-dir', default=argparse.SUPPRESS)
    common.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
    common.add_argument('--timeout', type=float, default=argparse.SUPPRESS)
    common.add_argument('--wait-timeout', type=float, default=argparse.SUPPRESS)
    root = argparse.ArgumentParser(prog='image-lab ctl', parents=[common],
                                   description='Control a running Image Lab GUI; never launches one.')
    commands = root.add_subparsers(dest='command', required=True)

    def leaf(sub, name, method):
        result = sub.add_parser(name, parents=[common])
        result.set_defaults(method=method)
        return result

    def group(name):
        return commands.add_parser(name, parents=[common]).add_subparsers(dest='action', required=True)

    for name, method in [('status','app.status'), ('capabilities','app.capabilities'),
                         ('instances','instances'), ('events','events.subscribe')]:
        p = leaf(commands, name, method)
        if name == 'events':
            p.add_argument('--count', type=int, default=0, help='Stop after this many events; 0 streams until timeout')
    for name, actions in [('window', ('show','hide','focus','close')),
                          ('viewer', ('status','open','close','next','previous','play','pause')),
                          ('view', ('search','filter','page','reveal')),
                          ('selection', ('get','set','clear','highlight','matches')),
                          ('library', ('list','get','import','scan-stop')),
                          ('queue', ('status','list','pause','resume','stop','retry','remove')),
                          ('panel', ('open','close')),
                          ('settings', ('get','set')),
                          ('details', ('get','update')),
                          ('rename', ('preview','apply')),
                          ('operation', ('get','wait'))]:
        sub = group(name)
        for action in actions:
            p = leaf(sub, action, 'operation.get' if name == 'operation' else f'{name}.{action}')
            if (name, action) in [('viewer','open'), ('view','reveal'), ('selection','highlight'),
                                  ('library','get'), ('details','get'), ('details','update'),
                                  ('rename','preview'), ('rename','apply')]:
                p.add_argument('image_id', type=int)
            if name == 'operation':
                p.add_argument('operation_id')
            if name == 'queue' and action in ('retry','remove'):
                p.add_argument('job_id', type=int)
            if name == 'panel':
                p.add_argument('panel', choices=['queue','settings','details','about'])
            if name == 'selection' and action == 'set':
                p.add_argument('ids', nargs='*', type=int)
            if name == 'library' and action == 'import':
                p.add_argument('path')
            if name == 'view' and action == 'search':
                p.add_argument('query')
            if name == 'view' and action == 'filter':
                p.add_argument('filter', choices=['all','needs_tags','tagged','failed'])
            if (name,action) in [('library','list'), ('selection','matches')]:
                p.add_argument('--query')
                p.add_argument('--filter', choices=['all','needs_tags','tagged','failed'])
            if action == 'list':
                p.add_argument('--offset', type=int)
                p.add_argument('--limit', type=int)
            if name in ('settings','details') and action in ('set','update'):
                p.add_argument('--values', required=True, help='JSON object of settings or full metadata values')
            if name == 'details' and action == 'update':
                p.add_argument('--revision', required=True)
            if name == 'rename':
                p.add_argument('--expected-path', required=True)
                p.add_argument('--name', required=True)
                if action == 'apply':
                    p.add_argument('--confirm', dest='confirmation', required=True,
                                   help='Exact confirmation token from rename preview')
    p = leaf(commands, 'analyze', 'analyze')
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument('--ids', nargs='+', type=int)
    choice.add_argument('--missing', action='store_true')
    p.add_argument('--replace', action='store_true')
    p.add_argument('--query')
    p.add_argument('--filter', choices=['all','needs_tags','tagged','failed'])
    return root


def output(value, machine=False):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=None if machine else 2), flush=True)


def main(argv=None):
    args = parser().parse_args(argv)
    machine = getattr(args, 'json', False)
    try:
        timeout = getattr(args, 'timeout', 10)
        wait = getattr(args, 'wait_timeout', 300)
        if not all(math.isfinite(v) and 0 < v <= 86400 for v in (timeout, wait)):
            raise ControlError('invalid_request', 'Timeouts must be finite and between 0 and 86400 seconds')
        if getattr(args, 'count', 0) < 0:
            raise ControlError('invalid_request', 'Event count must be nonnegative')
        if args.method == 'instances':
            output(instances(), machine)
            return 0
        params = {k: v for k,v in vars(args).items() if v is not None and k not in
                  {'method','command','action','json','data_dir','timeout','wait_timeout','count','missing'}}
        if 'values' in params:
            params['values'] = decode(params['values'])
        if args.method == 'analyze':
            if args.missing:
                if args.replace:
                    raise ControlError('invalid_request', '--replace cannot accompany --missing')
                args.method = 'analyze.missing'
                params.pop('replace', None)
            elif args.query is not None or args.filter is not None:
                raise ControlError('invalid_request', '--query/--filter require --missing')
        catalog = storage_paths(getattr(args, 'data_dir', None)).data
        with Client(catalog, timeout=timeout) as client:
            result = client.call(args.method, params)
            if args.command == 'operation' and args.action == 'wait':
                deadline = time.monotonic() + wait
                while result['state'] not in ('succeeded','failed','cancelled'):
                    if time.monotonic() >= deadline:
                        raise ControlError('timeout', 'Operation wait expired; work continues')
                    time.sleep(min(0.1, max(0, deadline-time.monotonic())))
                    client.timeout = min(timeout, max(0.001, deadline-time.monotonic()))
                    result = client.call('operation.get', params)
                output(result, machine)
                return 0 if result['state'] == 'succeeded' else 1
            output(result, machine)
            if args.command == 'events':
                deadline = time.monotonic() + wait
                sequence = result['sequence']
                count = 0
                while not args.count or count < args.count:
                    message = client.receive(max(0.001, deadline-time.monotonic()))
                    if (message.get('type') != 'event' or message.get('instance_id') != result['instance_id']
                            or message.get('sequence') != sequence + 1):
                        raise ControlError('conflict', 'Event stream changed or has a gap; resnapshot')
                    sequence = message['sequence']
                    output(message, machine)
                    count += 1
        return 0
    except KeyboardInterrupt:
        return 130
    except ControlError as exc:
        if machine:
            output({'error': {'code': exc.code, 'message': str(exc)}}, True)
        else:
            print(f'{exc.code}: {exc}', file=sys.stderr)
        return {'invalid_request': 2, 'unknown_method': 2, 'unavailable': 3,
                'unsupported_protocol': 3, 'timeout': 4}.get(exc.code, 1)
