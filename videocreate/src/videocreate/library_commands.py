"""Local asset library commands. No network or model calls."""
import argparse
from pathlib import Path

from . import asset_library
from .cli import print_result
from .config.storage import ConfigError, user_config_path


def command(argv):
    parser = argparse.ArgumentParser(prog='videocreate library')
    parser.add_argument('action', choices=['list', 'show', 'add', 'import', 'impact'])
    parser.add_argument('project', nargs='?', type=Path)
    location = parser.add_mutually_exclusive_group()
    location.add_argument('--config', type=Path)
    location.add_argument('--store-root', type=Path,
                          help='Directory containing a portable asset-library folder')
    parser.add_argument('--library-id')
    parser.add_argument('--version')
    parser.add_argument('--asset-id')
    parser.add_argument('--title')
    parser.add_argument('--tag', action='append', default=[])
    parser.add_argument('--notes', default='')
    parser.add_argument('--query', default='')
    parser.add_argument('--kind', choices=asset_library.KINDS)
    args = parser.parse_args(argv)
    store = args.store_root if args.store_root is not None else user_config_path(args.config).parent
    if args.action in {'add', 'import', 'impact'} and (not args.project or not args.asset_id):
        raise ConfigError('This action requires project and --asset-id')
    if args.action in {'add', 'show', 'import'} and not args.library_id:
        raise ConfigError('This action requires --library-id')
    if args.action in {'show', 'import'} and not args.version:
        raise ConfigError('Choose the exact --version from library list')
    if args.action == 'list':
        result = asset_library.catalog(store, kind=args.kind, query=args.query)
    elif args.action == 'show':
        result = asset_library.describe(store, args.library_id, args.version)
    elif args.action == 'add':
        result = asset_library.publish(args.project, store, args.asset_id, args.library_id,
                                      title=args.title, tags=args.tag, notes=args.notes)
    elif args.action == 'import':
        result = asset_library.import_asset(args.project, store, args.library_id, args.version, args.asset_id)
    else:
        result = asset_library.impact(args.project, args.asset_id)
    print_result(result)
    return int(not result['ok'])
