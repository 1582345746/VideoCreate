"""Shared, offline continuation decisions for the CLI and project manager."""
from pathlib import Path

from . import production
from .config.storage import ConfigError
from .planning.project import content_hash, load_project
from .runtime.state import read_state


def _snapshot(root, output_name):
    root = Path(root).resolve()
    bundle, state = load_project(root), read_state(root)
    current = production.status(root, output_name=output_name)
    if content_hash(bundle) != content_hash(load_project(root)) or state != read_state(root):
        raise ConfigError('Project changed while reading the next step; refresh and try again')
    step = current['next'] or {'id': 'delivery', 'name': '交付'}
    stage = step['id']
    profile = bundle['brief'].get('workflow_profile')
    image = profile in {'image-only', 'gif-only', 'gif-local'}
    result = {'ok': True, 'project': str(root), 'stage': stage, 'name': step['name'],
        'policy': current['policy'], 'output_name': output_name,
        'token': content_hash({'plan': bundle, 'state': state, 'status': current, 'output': output_name}),
        'executable': False, 'paid_creates': 0,
        'editable_layers': [key for key in ('brief', 'story', 'director', 'generation-plan', 'timeline')
            if not ('animation' in bundle and key in {'story', 'director', 'generation-plan'})
            and not (image and key == 'timeline')],
        'jobs': current['jobs'], 'errors': current['errors'], 'review': current['review'],
        'reusable': current['impact']}
    if stage in production.AUTHORING:
        inputs = production._authoring_inputs(bundle, root)
        row = next(s for s in current['stages'] if s['id'] == stage)
        value = inputs[stage]
        if content_hash(value) != row['input_hash']:
            raise ConfigError('Stage content changed while reading; refresh and try again')
        layer = {'theme': 'brief', 'outline': 'story', 'script': 'director',
            'characters': 'director', 'storyboard': 'generation-plan' if image else 'director',
            'references': 'generation-plan'}[stage]
        # These sources belong to the animation sidecar, not a competing form.
        if 'animation' in bundle and layer in {'story', 'director', 'generation-plan'}:
            layer = None
        if profile == 'gif-local' and stage in {'storyboard', 'references'}:
            layer = None
        result.update(action='inspect-authoring', input_hash=row['input_hash'], value=value,
            edit_layer=layer, assets_only=stage == 'characters',
            note='核对当前计划后可登记理由；此操作只核对计划，实际媒体继续使用审片记录。')
    elif stage == 'editing' and not image:
        result.update(action='render', executable=True, note='渲染当前已保存时间线，完成后仍需实际观看和听音。')
    elif stage == 'review':
        result.update(action='review-page', executable=True,
            note='打开实际素材审片页；完成观看、听音和观察记录后，再导入审核结果。')
    elif stage == 'delivery':
        result.update(action='deliver', executable=True, note='导出当前交付清单，保留实际审核状态。')
    elif stage == 'import-local-sources':
        result.update(action='import-video', note='选择本地视频及保留区间，或静态图片及停留时长，继续已有项目。')
    elif stage == 'import-gif-source':
        result.update(action='import-gif', note='选择视频或有序静帧；本地 GIF 转换无需上游配置。')
    elif stage == 'author-mixed-sources':
        result.update(action='choose-mixed-sources', note='可导入本地视频/静态图片，也可编写需要生成的镜头和任务。')
    elif stage == 'editing' and image:
        result.update(action='repair-gif', local_gifs=current.get('local_gifs', []),
            note='本地 GIF 配方或源文件已变化；查看具体 GIF 后使用 gif-rebuild，保留已有派生片。')
    elif stage == 'reconcile':
        result.update(action='reconcile', blocked_jobs=step.get('jobs', []),
            entry_points=['jobs status', 'jobs resolve --receipt'],
            note='提交结果未知：核对原提交并使用原任务证据处理，保留原路线和任务号。')
    elif stage == 'generation':
        result.update(action='generation',
            entry_points=['jobs status', 'production images-run' if image else 'jobs run'],
            note='查看已有任务；已知任务恢复原路线。新建或重做须使用明确的任务入口和现有授权范围。')
    else:
        result.update(action='repair-plan', note='先修复列出的计划错误，再继续当前项目。')
    return result, bundle, state


def describe(root, *, output_name='preview.mp4'):
    """Read-only decision; never writes checkpoints, selects routes or creates tasks."""
    return _snapshot(root, output_name)[0]


def execute(root, *, expected_token, output_name='preview.mp4'):
    """Execute one explicitly described local action, rejecting a stale decision."""
    result, bundle, state = _snapshot(root, output_name)
    if not expected_token or result['token'] != expected_token:
        raise ConfigError('Next step changed; read the current next action before executing')
    action = result['action']
    root = Path(root).resolve()
    if action == 'render':
        from .timeline.render import render
        value = render(root, bundle, state, output_name=output_name)
    elif action == 'review-page':
        from . import image_production
        if image_production.is_image(bundle):
            value = image_production.page(root, bundle)
        else:
            from .review.page import export
            value = export(root, output_name=output_name)
    elif action == 'deliver':
        value = production.delivery(root, output_name=output_name)
    else:
        # No generic generation dispatcher: it could submit never-created jobs.
        raise ConfigError('Next step requires its explicit entry: ' + action)
    return {**value, 'action': action, 'paid_creates': 0}
