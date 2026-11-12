"""Media URL registration/check commands; no uploads or generation calls."""
import argparse
import getpass
from datetime import datetime
from pathlib import Path

from .cli import print_result, read_config
from .config.storage import ConfigError, atomic_json, load_json, user_config_path
from .media_references import ROLES, bind_url, list_links, register, resolve_transports


def command(argv):
    parser = argparse.ArgumentParser(prog='videocreate media-ref')
    parser.add_argument('action', choices=['register', 'link', 'check', 'list', 'host'])
    parser.add_argument('project', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--kind', choices=sorted(ROLES))
    parser.add_argument('--role', choices=sorted(set.union(*ROLES.values())))
    parser.add_argument('--reference', type=Path, help='Registered reference JSON')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--upstream')
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--url-file', type=Path, help='Read URL locally; never print it or put it in command arguments')
    inputs.add_argument('--url-env', help='Name of an environment variable containing the URL')
    expiry = parser.add_mutually_exclusive_group()
    expiry.add_argument('--expires-at', help='ISO 8601 timestamp including timezone')
    expiry.add_argument('--permanent', action='store_true', help='User declares a stable public URL')
    parser.add_argument('--minimum-validity', type=int, default=7200, help='Required remaining validity in seconds')
    parser.add_argument('--lifetime', type=int, default=14400, help='Hosted link lifetime in seconds')
    args = parser.parse_args(argv)
    root = args.project.resolve()
    if not (root / 'project.json').is_file():
        raise ConfigError('Use an existing VideoCreate project')
    if args.action == 'list':
        print_result({'ok': True, **list_links(root)})
        return 0
    if args.action in {'register', 'host'}:
        if not args.source or not args.kind or not args.role:
            raise ConfigError('Register requires --source, --kind and --role')
        ref = register(root, args.source, kind=args.kind, role=args.role)
        target = root / 'assets/media-references' / (ref['sha256'] + '-' + ref['role'] + '.reference.json')
        atomic_json(target, ref)
        if args.action == 'register':
            print_result({'ok': True, 'reference': ref, 'reference_file': str(target),
                          'plan_modified': False, 'paid_creates': 0})
            return 0
        args.reference = target
    if not args.reference or not args.upstream:
        raise ConfigError('Link/check requires --reference and --upstream')
    path = user_config_path(args.config)
    config = read_config(path)
    upstream = config['upstreams'].get(args.upstream)
    if not upstream:
        raise ConfigError('Unknown upstream')
    ref = load_json(args.reference)
    options = {'upstream_id': args.upstream, 'account_id': upstream.get('account_id', args.upstream),
               'store_root': path.parent}
    if args.action == 'host':
        from . import media_server
        if args.lifetime < args.minimum_validity:
            raise ConfigError('Hosted link lifetime must cover the required validity')
        if not media_server.status(path.parent)['running']:
            raise ConfigError('Start the configured media-server before hosting reference media')
        settings = media_server.settings(config)
        item = media_server.publish(path.parent, root / ref['path'], kind=ref['kind'],
            public_base_url=settings['public_base_url'], lifetime_seconds=args.lifetime,
            maximum_seconds=settings['max_link_seconds'])
        try:
            linked = bind_url(root, ref, **options, url=item['url'], expires_at=item['expires_at'])
        except Exception:
            media_server.revoke(path.parent, item['publication_id'])
            raise
        print_result({'ok': True, 'reference': ref, 'reference_file': str(args.reference),
            'publication_id': item['publication_id'], 'transport': linked, 'plan_modified': False, 'paid_creates': 0})
    elif args.action == 'link':
        timestamp = None
        if args.expires_at:
            try:
                date = datetime.fromisoformat(args.expires_at.replace('Z', '+00:00'))
                if date.tzinfo is None:
                    raise ValueError()
                timestamp = date.timestamp()
            except ValueError:
                raise ConfigError('Expiry must be ISO 8601 with a timezone') from None
        if not args.permanent and timestamp is None:
            raise ConfigError('Declare --expires-at or --permanent')
        url = None if args.url_env else (args.url_file.read_text(encoding='utf-8-sig').strip() if args.url_file
                                       else getpass.getpass('HTTPS media file URL (hidden): '))
        print_result({'ok': True, **bind_url(root, ref, **options, url=url, url_env=args.url_env,
                                          expires_at=timestamp, permanent=args.permanent)})
    else:
        if args.minimum_validity < 0:
            raise ConfigError('Minimum validity must not be negative')
        records = resolve_transports(root, [ref], **options, minimum_validity=args.minimum_validity)
        print_result({'ok': True, 'references': [{k: v for k, v in record.items() if k != 'url'} for record in records],
                      'paid_creates': 0})
    return 0
