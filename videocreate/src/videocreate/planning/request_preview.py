"""Local, ordered evidence for one planned video request."""
from collections import Counter

from ..asset_library import project_media_revision
from ..config.storage import ConfigError, load_json
from ..media_references import digest
from .project import within


def describe_inputs(root, bundle, job, inputs):
    assets = bundle['director']['assets']
    shots = [shot for shot in bundle['director']['shots'] if shot['id'] in job['shot_ids']]
    uses = {}
    for shot in shots:
        ids = set(shot.get('asset_ids', []))
        ids.update(line.get('voice_asset_id') for line in shot.get('audio', {}).get('lines', []))
        for asset in assets:
            if asset['id'] in ids:
                for path in asset.get('references', []):
                    uses.setdefault(path, []).append({'shot_id': shot['id'], 'asset_id': asset['id']})

    counts = Counter()
    references = []
    for ref in inputs.get('media_references', job.get('references', [])):
        kind = ref.get('kind', 'image')
        counts[kind] += 1
        item = {key: ref[key] for key in ('path', 'role', 'sha256')}
        item.update(kind=kind, index_in_kind=counts[kind], shot_assets=uses.get(ref['path'], []))
        revision = project_media_revision(root, ref['path'], ref['sha256'])
        if revision:
            item['library_revision'] = revision
        if ref.get('duration_seconds') is not None:
            item['duration_seconds'] = ref['duration_seconds']
        if 'derivation' in ref:
            pointer = ref['derivation']
            manifest = within(root, pointer['path'])
            record = load_json(manifest)
            if digest(manifest) != pointer['sha256']:
                raise ConfigError('Reference slice changed during preview')
            item.update(derivation=pointer, derivation_operation=record['operation'])
            if record['operation'] == 'cast-sheet-v1':
                cells = []
                for index, cell in enumerate(record['cells']):
                    row, column = divmod(index, record['columns'])
                    visible = [s['id'] for s in shots if cell['asset_id'] in s.get('actors', []) or
                               cell['asset_id'] in s.get('asset_ids', [])]
                    cells.append({**cell, 'row': row+1, 'column': column+1, 'shot_ids': visible})
                item['cast_cells'] = cells
                references.append(item)
                continue
            source = record['source']
            item['source_sha256'] = source['sha256']
            if record['operation'] == 'lossless-png':
                revision = project_media_revision(root, source['path'], source['sha256'])
                if revision:
                    item['library_revision'] = revision
                item['shot_assets'] = uses.get(source['path'], [])
            else:
                item['source_interval'] = record['interval']
                if record['operation'] == 'extract-dialogue':
                    item.update(speaker=record['speaker'], audio_source='original-mix', listening_status='unverified')
        references.append(item)
    extra = {}
    if 'event_map' in job:
        from ..timeline.events import attached_event_map
        extra['local_event_timing'] = attached_event_map(root, bundle, job)
    return {'operation': job['operation'], 'seconds': job['seconds'], **extra,
            'generate_audio_requested': inputs['generate_audio'], 'reference_counts': dict(counts),
            'references': references, 'verification': 'planned-inputs-only'}
