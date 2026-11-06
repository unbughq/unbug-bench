"""Read-only laptop client for the controller's existing operator CLI."""
import argparse
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys

from durable.contract import BATCH_ID
from durable.report import render_text


def connection(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('Connection file must be owned by you with permissions 600.')
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('Connection file is too large.')
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {'ssh', 'command', 'batch'}:
        raise ValueError('Connection file needs ssh, command and batch fields.')
    for key in ('ssh', 'command'):
        if not isinstance(value[key], list) or not value[key] or any(
                not isinstance(arg, str) or not arg or '\0' in arg for arg in value[key]):
            raise ValueError('Connection commands must be nonempty argument lists.')
    if not isinstance(value['batch'], str) or not BATCH_ID.fullmatch(value['batch']):
        raise ValueError('Connection file has an invalid default batch.')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(prog='unbug', description=__doc__,
        epilog='Controller administration: bin/unbug --config CONFIG COMMAND')
    parser.add_argument('--connection', type=Path, default=Path.home() / '.config/unbug/client.json',
                        help='saved SSH connection (default: ~/.config/unbug/client.json)')
    commands = parser.add_subparsers(dest='op', required=True)
    for name in ('status', 'report'):
        command = commands.add_parser(name, help='read the current batch scorecard')
        command.add_argument('batch', nargs='?', help='override the saved default batch')
        command.add_argument('--json', action='store_true', help='emit the controller JSON')
    args = parser.parse_args(argv)
    try:
        profile = connection(args.connection)
    except FileNotFoundError:
        print('No controller connection configured. See README.md: Check factory status.', file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print('Invalid controller connection. Check its fields and permissions (600).', file=sys.stderr)
        return 1
    batch = args.batch or profile['batch']
    if not BATCH_ID.fullmatch(batch):
        parser.error('invalid batch ID')
    # SSH interprets a remote command as shell text; quote every argument once.
    remote = shlex.join([*profile['command'], args.op, batch])
    try:
        result = subprocess.run([*profile['ssh'], remote], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        print('Controller status timed out. Check SSH access and the controller service.', file=sys.stderr)
        return 1
    except OSError:
        print('Cannot start SSH. Check the saved connection and SSH installation.', file=sys.stderr)
        return 1
    if result.returncode:
        # Provider/remote stderr may contain private details; show fixed operational errors.
        message = ('SSH authentication failed.' if 'Permission denied' in result.stderr else
                   'SSH host verification failed.' if 'Host key verification failed' in result.stderr else
                   'Controller status failed. Check SSH access and the controller service.')
        print(message, file=sys.stderr)
        return 1
    try:
        card = json.loads(result.stdout)
        if card['batch'] != batch:
            raise ValueError('wrong batch')
        text = render_text(card)
    except (ValueError, KeyError, TypeError):
        print('Controller returned an invalid status response. Check the remote CLI configuration.', file=sys.stderr)
        return 1
    print(json.dumps(card, sort_keys=True) if args.json else text, end='\n' if args.json else '')
    return 0
