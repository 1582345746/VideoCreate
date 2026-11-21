"""Token-bound generation previews and execution shared by CLI and desktop UI."""
import copy
import hashlib
from pathlib import Path

from . import image_production, selection
from .config.management import fingerprint
from .config.storage import ConfigError
from .planning.project import content_hash, load_project, validate_plan, within
from .runtime import jobs
from .runtime.budget import estimate, image_parameters, reserve, summary
from .runtime.state import read_state

MODES = ('run', 'resume', 'content', 'replan')


def _context(root, config_path):
    from .cli import read_config
    root, config_path = Path(root).resolve(), Path(config_path).resolve()
    bundle, state, config = load_project(root), read_state(root), read_config(config_path)
    choices = {kind: selection.project_choice(root, kind) for kind in ('video', 'image')}
    return root, config_path, bundle, state, config, choices


def _context_hash(bundle, state, config, choices):
    return content_hash({'plan': bundle, 'state': state, 'config': fingerprint(config), 'choices': choices})


def _ordered(planned, requested):
    result, visiting = [], set()
    def add(jid):
        if jid in result:
            return
        if jid in visiting:
            raise ConfigError('Generation job dependencies contain a cycle')
        visiting.add(jid)
        for dependency in planned[jid].get('depends_on', []):
            if dependency in planned:
                add(dependency)
        result.append(jid)
        visiting.remove(jid)
    for jid in requested:
        add(jid)
    return result


def _row(binding, job, *, action, input_hash, prepared, seconds, kind, config, operation):
    currency = binding.options.get('pricing', {}).get('currency')
    parameters = {'operation': operation}
    if kind == 'video':
        parameters.update(resolution=config['_brief']['resolution'], aspect_ratio=config['_brief']['aspect_ratio'])
    else:
        parameters = image_parameters(binding, operation)
    return {'job_id': job['id'], 'kind': kind, 'action': action,
        'binding': binding.id, 'model': binding.model, 'remote_model': binding.remote_model,
        'upstream': binding.upstream_id, 'operation': operation, 'generated_seconds': seconds,
        'input_hash': input_hash, 'request_fingerprint': content_hash(prepared),
        'price': {'currency': currency, 'estimate': estimate(binding, seconds, currency, parameters=parameters) if currency else None},
        'budget_estimate': estimate(binding, seconds, config.get('budget', {}).get('currency', 'CNY'), parameters=parameters)}


def _prepare(root, config_path, *, job_ids, mode, reason, bindings, max_new_requests, poll_timeout):
    root, config_path, bundle, state, config, choices = _context(root, config_path)
    original_hash = _context_hash(bundle, state, config, choices)
    if mode not in MODES or type(max_new_requests) is not int or max_new_requests < 0:
        raise ConfigError('Choose run/resume/content/replan and a nonnegative new-request limit')
    if type(poll_timeout) is not int or poll_timeout <= 0:
        raise ConfigError('Polling timeout must be a positive number of seconds')
    if not isinstance(job_ids, list) or not job_ids or any(not isinstance(j, str) for j in job_ids):
        raise ConfigError('Select explicit planned task IDs')
    requested = list(dict.fromkeys(job_ids))
    if mode in {'content', 'replan'} and (len(requested) != 1 or not reason.strip()):
        raise ConfigError('A new candidate requires one selected task and an actual reason')
    check = validate_plan(bundle, root)
    if not check['ok']:
        raise ConfigError('; '.join(check['errors']))
    kind = 'image' if image_production.is_image(bundle) else 'video'
    planned = {j['id']: j for j in bundle['generation-plan'].get('image_jobs' if kind == 'image' else 'jobs', [])}
    if set(requested) - set(planned):
        raise ConfigError('Selected IDs are not planned provider tasks; local sources/GIFs use their own services')
    ordered = _ordered(planned, requested)
    bindings = dict(bindings or {})
    if set(bindings) - set(ordered) or any(not isinstance(v, str) for v in bindings.values()):
        raise ConfigError('Binding overrides must name tasks in the selected dependency set')
    if any(bid not in config['bindings'] or config['models'][config['bindings'][bid]['model']]['kind'] != kind for bid in bindings.values()):
        raise ConfigError('Unknown binding or wrong media kind')
    if mode == 'resume' and bindings:
        raise ConfigError('Recovery uses original routes; omit new binding overrides')
    if 'animation' in bundle and kind == 'video':
        from .animation.pipeline import execution_guard
        execution_guard(root, bundle, ordered)
    retry = mode if mode in {'content', 'replan'} else None
    rows, fixed, items = [], {}, []
    display_config = {**config, '_brief': bundle['brief']}
    for jid in ordered:
        job, prior = planned[jid], state['jobs'].get(jid, {})
        if prior and prior.get('kind', 'video') != kind:
            raise ConfigError(jid + ': saved attempt belongs to a different media kind')
        replacement = bool(retry and jid in requested)
        if prior.get('status') == 'submitting':
            raise ConfigError(jid + ': original submission is active or unresolved; inspect it before proceeding')
        if prior.get('status') == 'submission_unknown' and not (kind == 'image' and mode == 'resume' and prior.get('provider_response')):
            raise ConfigError(jid + ': submission unknown; reconcile the original attempt')
        if replacement and prior.get('status') not in ({'completed', 'failed', 'rejected', 'output_invalid'} if kind == 'image' else {'completed', 'failed', 'rejected'}):
            raise ConfigError(jid + ': only a terminal task can request a new candidate')
        if kind == 'video':
            if mode == 'resume' and not prior.get('task_id'):
                raise ConfigError(jid + ': recovery requires the original known task; no create was sent')
            if prior and not prior.get('task_id') and not replacement:
                raise ConfigError(jid + ': original attempt needs explicit retry/reconciliation')
            try:
                binding, _, _, compilation, prepared, _ = jobs._prepare_job(root, bundle, job, config,
                    config_path.parent, prior, retry=retry, explicit_jobs=set(requested), binding_override=bindings)
            except selection.SelectionRequired as exc:
                exc.payload = {**exc.payload, 'job_id': jid}
                raise
            current_hash = jobs.generation_inputs(root, bundle, job, compilation)
            if prior and prior.get('input_hash') != current_hash and not (mode == 'replan' and jid in requested):
                raise ConfigError(jid + ': inputs changed; explicitly replan only this task')
            action = 'create' if not prior or replacement else 'resume'
            if action == 'create':
                fixed[jid] = binding.id
            row = _row(binding, job, action=action, input_hash=current_hash, prepared=prepared,
                seconds=job['seconds'], kind=kind, config=display_config, operation=job['operation'])
        else:
            if mode == 'resume':
                if prior.get('status') == 'completed':
                    current = next(r for r in image_production.rows(root, bundle, state) if r['job_id'] == jid)
                    if current['status'] != 'completed':
                        raise ConfigError(jid + ': completed image changed; recover its original or explicitly replan')
                    action = 'skip'
                elif prior.get('status') in {'submission_unknown', 'output_invalid'} and prior.get('provider_response'):
                    response_path = within(root, prior['provider_response'])
                    action = 'reprocess'
                else:
                    raise ConfigError(jid + ': synchronous image recovery needs its saved original response or an upstream-result receipt')
                binding = jobs.pinned_binding(config, prior.get('binding_snapshot', {}), config_path.parent)
                prepared = {'response_sha256': hashlib.sha256(response_path.read_bytes()).hexdigest()} if action == 'reprocess' else {}
                row = _row(binding, job, action=action, input_hash=prior['input_hash'], prepared=prepared,
                    seconds=0, kind=kind, config=display_config, operation=job['operation'])
            else:
                if prior and not replacement and prior.get('status') != 'completed':
                    raise ConfigError(jid + ': original image needs explicit recovery or retry')
                from .assets import _image_input_hash, _select_image_route
                from .adapters.image import BindingImageClient
                item = next(i for i in image_production.items(root, bundle, [jid]) if i['job_id'] == jid)
                if jid in bindings and (not prior or replacement):
                    item.update(binding_id=bindings[jid], model=config['bindings'][bindings[jid]]['model'])
                try:
                    pair = selection.resolve(root, config, kind='image', store_root=config_path.parent,
                        model=item.get('model'), binding=item.get('binding_id'), operation=job['operation'])
                    model, binding_id = pair or (item.get('model'), item.get('binding_id'))
                    model, candidates, _ = _select_image_route(config, requested_model=model, binding_id=binding_id,
                        prompt=item['prompt'], references=item['references'], size=item['size'], quality=item['quality'],
                        output_format=item['output_format'], store_root=config_path.parent)
                except selection.SelectionRequired as exc:
                    exc.payload = {**exc.payload, 'job_id': jid}
                    raise
                binding = candidates[0]
                current_hash = _image_input_hash(root, model=model, prompt=item['prompt'], size=item['size'],
                    quality=item['quality'], output_format=item['output_format'], references=item['references'])
                if prior and prior.get('input_hash') != current_hash and mode != 'replan':
                    raise ConfigError(jid + ': image inputs changed; explicitly replan this task')
                if prior and not replacement:
                    current = next(r for r in image_production.rows(root, bundle, state) if r['job_id'] == jid)
                    if current['status'] != 'completed':
                        raise ConfigError(jid + ': original image bytes are not current; recover or explicitly replan')
                prepared = BindingImageClient(binding).prepare(item['prompt'], item['references'], size=item['size'],
                    quality=item['quality'], output_format=item['output_format'])
                action = 'create' if not prior or replacement else 'skip'
                fixed[jid] = binding.id
                items.append({**item, 'model': model, 'binding_id': binding.id})
                row = _row(binding, job, action=action, input_hash=current_hash, prepared=prepared,
                    seconds=0, kind=kind, config=display_config, operation=job['operation'])
        row.update(explicit=jid in requested, task_id=prior.get('task_id'), status=prior.get('status', 'not-submitted'))
        rows.append(row)
    creates = [r for r in rows if r['action'] == 'create']
    limit = 0 if mode == 'resume' else max_new_requests
    if len(creates) > limit:
        raise ConfigError(f'Selected tasks and dependencies need {len(creates)} new requests; this operation permits {limit}')
    execution_config = copy.deepcopy(config)
    budget = execution_config.setdefault('budget', {})
    count = sum(i['kind'] == kind and i.get('status') != 'not-submitted' for i in state['ledger'])
    budget['max_'+kind+'_requests'] = min(budget.get('max_'+kind+'_requests', 12), count + limit)
    simulated = copy.deepcopy(state)
    for index, row in enumerate(creates):
        reserve(simulated, budget, attempt_id='preview-'+str(index), job_id=row['job_id'], kind=kind,
            estimated=row['budget_estimate'])
    current = _context(root, config_path)
    if original_hash != _context_hash(*current[2:]):
        raise ConfigError('Plan, tasks, saved configuration or project selection changed during preflight; refresh')
    arguments = {'job_ids': requested, 'mode': mode, 'reason': reason, 'bindings': bindings,
        'max_new_requests': max_new_requests, 'poll_timeout': poll_timeout}
    report = {'ok': True, 'project': str(root), 'kind': kind, 'mode': mode,
        'selected_jobs': requested, 'ordered_jobs': ordered, 'jobs': rows, 'new_requests': len(creates),
        'max_new_requests': limit, 'budget': summary(state), 'paid_creates': 0,
        'note': 'Preflight may verify reference HTTPS links; it creates no media. Estimates are not actual charges.'}
    report['token'] = content_hash({'context': original_hash, 'arguments': arguments, 'report': report})
    return report, arguments, execution_config, fixed, items


def preview(root, config_path, *, job_ids, mode='run', reason='', bindings=None, max_new_requests=1, poll_timeout=900):
    return _prepare(root, config_path, job_ids=job_ids, mode=mode, reason=reason, bindings=bindings,
        max_new_requests=max_new_requests, poll_timeout=poll_timeout)[0]


def execute(root, config_path, *, expected_token, job_ids, mode='run', reason='', bindings=None,
            max_new_requests=1, poll_timeout=900, progress=None):
    if not expected_token:
        raise ConfigError('Read a generation preview before executing')
    report, arguments, config, fixed, items = _prepare(root, config_path, job_ids=job_ids, mode=mode,
        reason=reason, bindings=bindings, max_new_requests=max_new_requests, poll_timeout=poll_timeout)
    if report['token'] != expected_token:
        raise ConfigError('Generation preview changed; review current tasks, routes and budget')
    root, store_root = Path(root).resolve(), Path(config_path).resolve().parent
    before = read_state(root)
    mode = arguments['mode']
    if report['kind'] == 'video':
        result = jobs.generate(root, config, store_root=store_root, job_ids=arguments['job_ids'],
            retry=mode if mode in {'content', 'replan'} else None, reason=arguments['reason'],
            binding_override=fixed, poll_timeout=arguments['poll_timeout'], progress=progress, allow_create=mode != 'resume')
    elif mode == 'resume':
        from .assets import reprocess_image
        results = []
        for row in report['jobs']:
            if progress:
                progress({'job_id': row['job_id'], 'phase': row['action']})
            results.append(reprocess_image(root, row['job_id'], config=config, store_root=store_root)
                if row['action'] == 'reprocess' else {'ok': True, 'job_id': row['job_id'], 'skipped': True})
        result = {'ok': all(r['ok'] for r in results), 'images': results}
    else:
        from .assets import generate_image, generate_images
        if mode in {'content', 'replan'}:
            result = generate_image(root, config, store_root=store_root, **items[0], retry=mode, reason=arguments['reason'])
        else:
            result = generate_images(root, config, store_root=store_root, items=items)
    after = read_state(root)
    prior_ids = {r['attempt_id'] for r in before['ledger']}
    result['new_recorded_attempts'] = sum(r['attempt_id'] not in prior_ids and r.get('status') != 'not-submitted' for r in after['ledger'])
    result['approval'] = 'unverified; generation does not approve media'
    return result
