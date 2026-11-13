"""Catalog and selection entry points. All mutations use the same local service as the GUI."""
import argparse
from pathlib import Path

from .config.storage import ConfigError, load_json, redact_config, user_config_path


def providers_command(argv):
    from .cli import print_result
    from .config import management as m
    parser = argparse.ArgumentParser(prog='videocreate providers')
    parser.add_argument('action', choices=['list', 'compare', 'quotas', 'show', 'migrate', 'save', 'archive', 'restore', 'credential', 'discover', 'pricing', 'import-models', 'repair-inspect', 'repair-preview', 'repair-apply'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--upstream')
    parser.add_argument('--project', type=Path, help='Register an existing v3 project for local quota accounting')
    parser.add_argument('--kind', choices=['video', 'image'])
    parser.add_argument('--file', type=Path)
    parser.add_argument('--token')
    parser.add_argument('--preview-token')
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--use-defaults', action='store_true', help='Explicitly retain unattended default selection')
    parser.add_argument('--group', choices=['upstreams', 'models', 'bindings'])
    parser.add_argument('--id')
    parser.add_argument('--version')
    parser.add_argument('--family', default='custom')
    parser.add_argument('--binding', action='append', help='Two to four binding IDs for offline comparison')
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--operation', default='text-to-video')
    parser.add_argument('--resolution', default='720p')
    parser.add_argument('--aspect-ratio', default='16:9')
    parser.add_argument('--reason', default='explicit catalog edit')
    args = parser.parse_args(argv)
    path = user_config_path(args.config)
    if args.action.startswith('repair-'):
        from .config import repair
        if args.apply:raise ConfigError('Repair uses repair-preview then repair-apply with its preview token')
        if args.action=='repair-inspect':
            if args.file or args.token or args.preview_token or args.baseline:raise ConfigError('repair-inspect only needs --config')
            result=repair.inspect(path)
        else:
            if not args.file or not args.token:raise ConfigError('Repair needs --file with the draft and --token from repair-inspect')
            text=args.file.read_text(encoding='utf-8-sig')
            if args.action=='repair-preview':
                if args.preview_token:raise ConfigError('Use --preview-token with repair-apply')
                result=repair.preview(path,text,source_token=args.token,baseline=args.baseline)
            else:result=repair.apply(path,text,source_token=args.token,preview_token=args.preview_token,baseline=args.baseline)
        print_result(result);return 0
    if args.preview_token or args.baseline:raise ConfigError('--preview-token/--baseline are only consumed by configuration repair')
    record = m.load(path)
    if args.action == 'quotas':
        if not args.upstream:
            raise ConfigError('Quota status requires --upstream')
        from .runtime import quotas
        if args.project:
            from .planning.project import load_project
            load_project(args.project)
            quotas.watch(path.parent, args.project)
        result = quotas.status(path.parent, record['config'], args.upstream)
    elif args.action == 'compare':
        from .catalog.presentation import compare
        result = compare(record['config'], args.binding or [], store_root=path.parent,
            scenario={'operation':args.operation,'seconds':args.seconds,'resolution':args.resolution,'aspect_ratio':args.aspect_ratio})
    elif args.action == 'pricing':
        if not args.upstream:
            raise ConfigError('Pricing discovery requires --upstream')
        from .catalog.pricing import discover
        result = discover(record['config'], args.upstream, store_root=path.parent)
    elif args.action == 'discover':
        if not args.upstream:
            raise ConfigError('Discovery requires --upstream')
        from .catalog.discovery import models
        result = models(record['config'], args.upstream, store_root=path.parent)
    elif args.action == 'import-models':
        if not args.upstream or not args.file or not args.kind:
            raise ConfigError('Import requires --upstream, --kind and --file with an ids list')
        from .catalog.discovery import import_models
        values = load_json(args.file)
        if not isinstance(values.get('ids'), list):
            raise ConfigError('Import file requires an ids list')
        changed, ids = import_models(record['config'], args.upstream, values['ids'], kind=args.kind, family=args.family)
        if args.apply:
            if not args.token:
                raise ConfigError('Apply requires the current --token')
            result = {**m.save(path, changed, expected_token=args.token, reason='import catalog drafts'), 'added': ids}
        else:
            result = {'ok': True, 'applied': False, 'draft_ids': ids, 'paid_creates': 0}
    elif args.action == 'migrate':
        result = m.migration(path, apply=args.apply, ask=not args.use_defaults)
    elif args.action == 'list':
        result = {'ok': True, 'config': str(path), 'revision': record['revision'],
                  'bindings': m.catalog(record['config'], upstream=args.upstream, kind=args.kind), 'paid_creates': 0}
    elif args.action == 'show':
        result = {**record, 'config': redact_config(record['config']), 'paid_creates': 0}
    elif args.action == 'save':
        if not args.file or not args.token:
            raise ConfigError('Save needs --file and the current --token')
        result = m.save(path, load_json(args.file), expected_token=args.token, reason=args.reason)
    elif args.action == 'restore':
        if not args.file or not args.token:
            raise ConfigError('Restore needs --file and the current --token')
        result = m.restore(path, args.file, expected_token=args.token)
    elif args.action == 'archive':
        if not args.group or not args.id or not args.token:
            raise ConfigError('Archive needs --group, --id and --token')
        result = m.save(path, m.archive(record['config'], args.group, args.id), expected_token=args.token, reason=args.reason)
    else:
        import getpass
        from .config.secrets import store_credential
        if not args.id or not args.version:
            raise ConfigError('Credential input needs an account --id and a new --version')
        auth = store_credential(path.parent, args.id, getpass.getpass('API key (hidden): '), version=args.version)
        result = {'ok': True, 'auth_reference': auth, 'paid_creates': 0,
                  'note': 'Encrypted locally; assign this reference to the intended upstream account.'}
    print_result(result)
    return 0


def selection_command(argv):
    from .cli import print_result, read_config
    from . import selection
    parser = argparse.ArgumentParser(prog='videocreate selection')
    parser.add_argument('action', choices=['list', 'choose', 'status', 'impact'])
    parser.add_argument('project', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--kind', choices=['video', 'image'], default='video')
    parser.add_argument('--model')
    parser.add_argument('--upstream')
    parser.add_argument('--operation')
    parser.add_argument('--request-file', type=Path)
    parser.add_argument('--selection-id')
    parser.add_argument('--number', type=int)
    parser.add_argument('--scope', choices=['project', 'once'], default='project')
    parser.add_argument('--job', action='append')
    args = parser.parse_args(argv)
    path = user_config_path(args.config)
    config = read_config(path)
    if args.action == 'impact':
        result = selection.switch_impact(args.project, job_ids=args.job)
    elif args.action == 'list':
        result = selection.menu(args.project, config, kind=args.kind, store_root=path.parent, model=args.model,
            upstream=args.upstream, operation=args.operation,
            request=load_json(args.request_file) if args.request_file else None)
    elif args.action == 'choose':
        if not args.selection_id or args.number is None:
            raise ConfigError('Choose needs --selection-id and --number from the displayed list')
        result = selection.choose(args.project, config, selection_id=args.selection_id, number=args.number,
                                  store_root=path.parent, scope=args.scope)
    else:
        result = {'ok': True, 'choices': {k: selection.project_choice(args.project, k) for k in ('image', 'video')},
                  'paid_creates': 0}
    print_result(result)
    return 0
