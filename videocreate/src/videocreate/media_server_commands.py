"""Local file hosting behind a user-configured HTTPS tunnel."""
import argparse
from pathlib import Path

from .cli import print_result, read_config
from .config.storage import ConfigError, atomic_json, user_config_path
from . import media_server


def command(argv):
    parser = argparse.ArgumentParser(prog='videocreate media-server')
    parser.add_argument('action', choices=['configure', 'run', 'start', 'stop', 'status', 'publish', 'list', 'revoke'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--public-base-url')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--kind', choices=['image', 'video', 'audio'])
    parser.add_argument('--lifetime', type=int, default=14400)
    parser.add_argument('--publication-id')
    parser.add_argument('--output', type=Path, help='Private link receipt; the URL is not printed')
    args = parser.parse_args(argv)
    path = user_config_path(args.config).resolve()
    if args.action == 'configure':
        from .config import management
        if not args.public_base_url:
            raise ConfigError('Configure requires --public-base-url')
        record = management.load(path)
        value = management.migrate(record['config'])
        value['local_media_server'] = {'port': args.port, 'public_base_url': args.public_base_url.rstrip('/'),
                                       'max_link_seconds': 604800}
        print_result(management.save(path, value, expected_token=record['token'], reason='Configure local HTTPS media tunnel'))
        return 0
    config = read_config(path)
    options = media_server.settings(config)
    if args.action == 'run':
        media_server.serve(path.parent, port=options['port'])
    elif args.action == 'start':
        print_result(media_server.start(path))
    elif args.action == 'stop':
        print_result(media_server.stop(path.parent))
    elif args.action == 'status':
        print_result({'ok': True, **media_server.status(path.parent), 'settings': options})
    elif args.action == 'list':
        print_result({'ok': True, 'publications': media_server.published(path.parent)})
    elif args.action == 'revoke':
        print_result(media_server.revoke(path.parent, args.publication_id))
    else:
        if not args.source or not args.kind or not args.output:
            raise ConfigError('Publish requires --source, --kind and --output for the private link receipt')
        if args.output.exists():
            raise ConfigError('Choose a new output receipt path; existing link evidence is preserved')
        if not media_server.status(path.parent)['running']:
            raise ConfigError('Start the local media service before publishing a file')
        result = media_server.publish(path.parent, args.source, kind=args.kind,
            public_base_url=options['public_base_url'], lifetime_seconds=args.lifetime,
            maximum_seconds=options['max_link_seconds'])
        atomic_json(args.output.resolve(), result)
        print_result({'ok': True, **{k: v for k, v in result.items() if k != 'url'},
                      'private_receipt': str(args.output.resolve()), 'public_fetch': 'not-yet-verified'})
    return 0
