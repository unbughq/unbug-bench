#!/usr/bin/env python3
"""Print the Sealing Board for the campaign controller, from live records (read-only).

Usage on the control VM, next to campaign_observe.py:
  python3 campaign_board.py            # JSON: every case in every batch
  python3 campaign_board.py --live     # only cases still running in a live batch
  python3 campaign_board.py --text     # the same board as a table

Reads the campaign root's config.json (state_dir, database_url_file) like campaign_observe.py.
Nothing is written, launched or sent to a worker. The board replaces hand-edited status files:
regenerate it, never edit it.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'factory'))
from durable.board import read_board, render_board


def config(root: Path) -> dict:
    value = json.loads((root / 'config.json').read_text())
    return {'state_dir': value['state_dir'],
            'database_url': Path(value['database_url_file']).read_text().strip(),
            # The campaign controller runs as its own unit (unbug-durable-case-campaign.service).
            'status_service_unit': value.get('status_service_unit', 'unbug-durable-case-campaign.service')}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('UNBUG_CAMPAIGN_ROOT', Path(__file__).parent)))
    parser.add_argument('--live', action='store_true', help='only cases still running in a live batch')
    parser.add_argument('--text', action='store_true', help='print a table instead of JSON')
    args = parser.parse_args(argv)
    board = read_board(config(args.root), live_only=args.live)
    print(render_board(board) if args.text else json.dumps(board, sort_keys=True), end='' if args.text else '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
