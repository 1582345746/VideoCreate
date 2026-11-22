"""Scope reference adaptation and identity/wardrobe decisions to the current shot."""
import json

from ..config.storage import ConfigError


def validate(shot, assets):
    plan = shot.get('adaptation')
    if plan is None:
        return []
    problems = []
    if set(plan['preserve']) & set(plan['allow_change']):
        problems.append('a reference element cannot be both preserved and changed')
    mode = plan['mode']
    cast = plan.get('cast', [])
    if mode in {'replace-region', 'replace-actor'} and not cast:
        problems.append('character replacement requires a source-to-target cast mapping')
    if mode == 'replace-region' and not plan.get('region', '').strip():
        problems.append('regional replacement needs an explicit target region')
    if mode == 'rhythm-only' and ('rhythm' not in plan['preserve'] or cast):
        problems.append('rhythm-only requires preserved rhythm and no source cast replacements')
    names = set()
    for actor in cast:
        name = actor['source_actor'].strip()
        if not name or name in names:
            problems.append('give each source actor a unique nonempty identifier')
        names.add(name)
        for field in ('identity_asset_id', 'wardrobe_asset_id'):
            if field not in actor:
                continue
            aid = actor[field]
            if aid not in shot.get('asset_ids', []) or assets.get(aid, {}).get('kind') != 'character':
                problems.append(field + ' must name a character card selected for this shot: ' + aid)
    return [shot['id'] + '.adaptation: ' + problem for problem in problems]


def directions(shot, assets, job, root):
    plan = shot['adaptation']
    scope = {'replace-actor': 'Replace the complete source performer, including their body.',
             'replace-region': 'Replace the mapped performer only inside the specified region. Preserve other performers and the surrounding action.',
             'rhythm-only': 'Borrow the timing of the reference. Create the shot using the selected subjects and scene.'}
    lines = [scope[plan['mode']], 'Shot reference decisions: ' + json.dumps(plan, ensure_ascii=False, separators=(',', ':'))]
    if not root or not plan.get('cast'):
        return lines
    from ..cast_sheet import image_slots, slots_for_asset
    slots = image_slots(root, job.get('references', []))
    for actor in plan['cast']:
        for field, purpose in [('identity_asset_id', 'face and body identity'), ('wardrobe_asset_id', 'clothes and headwear')]:
            if field not in actor:
                continue
            aid = actor[field]
            indices = slots_for_asset(slots, assets[aid])
            if not indices:
                raise ConfigError(shot['id'] + ': attach the selected ' + field + ' to this video job: ' + aid)
            names = ', '.join(f'images[{i}] row {r} column {c}' if r else f'images[{i}]' for i, r, c in indices)
            lines.append(actor['source_actor'] + ' uses ' + names + ' for ' + purpose + ' (' + aid + ').')
    return lines
