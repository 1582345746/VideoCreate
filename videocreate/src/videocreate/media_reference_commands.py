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
    parser.add_argument('action', choices=['register', 'link', 'check', 'list', 'host', 'attach', 'slice', 'extract-dialogue', 'cast-sheet'])
    parser.add_argument('project', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--spec', type=Path, help='Cast sheet JSON with columns and ordered character cells')
    parser.add_argument('--kind', choices=sorted(ROLES))
    parser.add_argument('--role', choices=sorted(set.union(*ROLES.values())))
    parser.add_argument('--reference', type=Path, help='Registered reference JSON')
    parser.add_argument('--asset-id', help='Attach a reference directly from a project asset card')
    parser.add_argument('--media-index', type=int, help='One-based index for a card containing multiple files')
    parser.add_argument('--as-png', action='store_true', help='Attach a lossless PNG copy of a visual asset')
    parser.add_argument('--speaker', help='Assigned speaker of a source video interval')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--upstream')
    parser.add_argument('--job', help='Job ID for an explicit local plan attachment')
    parser.add_argument('--start', type=float, help='Reference slice start in source seconds, inclusive')
    parser.add_argument('--end', type=float, help='Reference slice end in source seconds, exclusive')
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
    if args.action == 'cast-sheet':
        from .cast_sheet import create_sheet
        if not args.spec:
            raise ConfigError('Choose a cast sheet layout with --spec')
        print_result(create_sheet(root, load_json(args.spec)))
        return 0
    if args.action == 'list':
        print_result({'ok': True, **list_links(root)})
        return 0
    if args.action in {'slice', 'extract-dialogue'}:
        if not args.reference or args.start is None or args.end is None:
            raise ConfigError('Slice requires --reference, --start and --end')
        from .reference_slices import slice_reference
        if args.action == 'extract-dialogue' and not args.speaker:
            raise ConfigError('Extract-dialogue requires --speaker')
        print_result(slice_reference(root, load_json(args.reference), start=args.start, end=args.end,
                                     extract_speaker=args.speaker if args.action == 'extract-dialogue' else None))
        return 0
    if args.action == 'attach':
        if not args.job or bool(args.reference) == bool(args.asset_id):
            raise ConfigError('Attach requires --job and exactly one of --reference or --asset-id')
        if args.reference and (args.media_index is not None or args.as_png):
            raise ConfigError('--media-index and --as-png apply only to a project asset card')
        from .planning.project import load_project, validate_plan, within
        from .runtime.state import state_lock
        from .media_references import prepare_references
        import copy
        import time
        from .reference_slices import REFERENCE_FIELDS
        with state_lock(root):
            bundle = load_project(root)
            job = next((j for j in bundle['generation-plan']['jobs'] if j['id'] == args.job), None)
            if job is None:
                raise ConfigError('Unknown job ID')
            if args.asset_id:
                from .asset_library import digest, project_media_revision
                asset = next((a for a in bundle['director']['assets'] if a['id'] == args.asset_id), None)
                if asset is None or not asset.get('references'):
                    raise ConfigError('Select a project asset card with a reference file')
                paths = asset['references']
                index = 1 if len(paths) == 1 and args.media_index is None else args.media_index
                if index is None or not 1 <= index <= len(paths):
                    raise ConfigError('Choose --media-index from 1 to ' + str(len(paths)))
                path = paths[index - 1]
                kind = 'audio' if asset['kind'] == 'voice' else 'image'
                if args.role not in ROLES[kind]:
                    raise ConfigError('Choose a supported --role for the selected project asset')
                sha = digest(within(root, path))
                project_media_revision(root, path, sha)
                reference = {'path': path, 'sha256': sha, 'kind': kind, 'role': args.role}
                if args.as_png:
                    from .image_reference_png import convert_under_lock
                    reference = convert_under_lock(root, reference)
            else:
                reference = load_json(args.reference)
                if 'kind' not in reference:
                    raise ConfigError('Attach needs an explicitly typed registered reference')
                reference = {k: reference[k] for k in REFERENCE_FIELDS if k in reference}
            prepare_references(root, [reference])
            before = copy.deepcopy(bundle['generation-plan'])
            refs = job.setdefault('references', [])
            if any('kind' not in ref for ref in refs):
                raise ConfigError('Type the existing legacy references explicitly before attaching new media')
            if reference not in refs:
                refs.append(copy.deepcopy(reference))
            job['operation'] = 'reference-to-video'
            report = validate_plan(bundle, root)
            if not report['ok']:
                raise ConfigError('; '.join(report['errors']))
            plan_path = within(root, bundle['project'].get('files', {}).get('generation-plan', 'generation-plan.json'))
            if bundle['generation-plan'] != before:
                atomic_json(root/'references/plan-history'/('before-attach-' + str(time.time_ns()) + '.json'), before)
                atomic_json(plan_path, bundle['generation-plan'])
        print_result({'ok': True, 'job_id': args.job, 'reference': reference,
            'plan_modified': before != bundle['generation-plan'], 'paid_creates': 0,
            'note': 'Only the plan changed. Existing tasks stay pinned; an input change requires explicit replan.'})
        return 0
    if args.action == 'host' and args.reference and args.source:
        raise ConfigError('Host accepts either an existing reference or a new source, not both')
    if args.action == 'register' or args.action == 'host' and not args.reference:
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
        from .media_references import prepare_references
        prepare_references(root, [ref])
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
