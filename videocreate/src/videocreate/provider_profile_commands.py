"""Offline upstream onboarding, saved documentation and named context lookup."""
import argparse
from pathlib import Path
import sys

from .config import management
from .config import provider_profiles as profiles
from .config.storage import ConfigError, load_json, user_config_path


def command(argv):
    from .cli import print_result
    parser = argparse.ArgumentParser(prog='videocreate providers')
    sub = parser.add_subparsers(dest='action', required=True)
    listing = sub.add_parser('profile-list', help='List saved upstream names, aliases and document counts')
    show = sub.add_parser('profile-show', help='Read one upstream context, document versions and implemented protocols')
    imp = sub.add_parser('profile-import', help='Preview/apply one upstream packet and immutable local documents')
    for child in (listing, show, imp):
        child.add_argument('--config', type=Path)
    show.add_argument('--upstream', required=True, help='Saved ID, display name or alias')
    show.add_argument('--kind', choices=['image', 'video'])
    show.add_argument('--model-name')
    imp.add_argument('--file', type=Path, required=True)
    imp.add_argument('--apply', action='store_true')
    imp.add_argument('--token')
    imp.add_argument('--preview-token')
    imp.add_argument('--credential-stdin', action='store_true', help='At commit only, read the key from private stdin; never put it in argv/packet')
    args = parser.parse_args(argv); path = user_config_path(args.config)
    if args.action == 'profile-import':
        def read_key():
            if sys.stdin.isatty():
                import getpass
                return getpass.getpass('API key (hidden): ')
            value = sys.stdin.read(65537)
            if len(value) > 65536:
                raise ConfigError('Credential input too long')
            return value.strip()
        result = profiles.import_profile(path, load_json(args.file), base_dir=args.file.resolve().parent,
            apply=args.apply, token=args.token, preview_token=args.preview_token,
            credential=read_key if args.credential_stdin else None)
    else:
        record = management.load(path)
        if record['errors']:
            raise ConfigError('Validate configuration before reading upstream profiles')
        result = profiles.list_profiles(record['config'], path) if args.action == 'profile-list' else profiles.show_profile(
            record['config'], path, args.upstream, kind=args.kind, model_name=args.model_name)
    print_result(result)
    return 0
