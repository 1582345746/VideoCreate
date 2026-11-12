"""Offline generation-plan edits keep task identities and local-source ownership."""
import copy

from .config.storage import ConfigError

COLLECTIONS = ('jobs', 'image_jobs')
TERMINAL = {'completed', 'failed', 'rejected'}


def changes(bundle, candidate, state):
    before, after = bundle['generation-plan'], candidate['generation-plan']
    for key in ('local_sources', 'local_gifs'):
        if before.get(key) != after.get(key):
            raise ConfigError('Use the local import/GIF service to edit ' + key + '; generation authoring preserves its snapshots')
    rows=[]
    for collection in COLLECTIONS:
        old={job['id']:job for job in before.get(collection,[])}
        new={job['id']:job for job in after.get(collection,[])}
        for identity,job in old.items():
            record=state['jobs'].get(identity)
            if not record:continue
            if identity not in new:
                raise ConfigError(identity+': saved tasks cannot be deleted, renamed or moved between media kinds; keep the original plan entry')
            if job!=new[identity] and record.get('status') not in TERMINAL:
                raise ConfigError(identity+': original submission is active or unresolved; finish/reconcile it before editing this job')
        for identity in new.keys()-old.keys():
            if state['jobs'].get(identity):
                raise ConfigError(identity+': this ID already belongs to saved task history; choose a new ID')
        for identity in sorted(old.keys()|new.keys()):
            if old.get(identity)==new.get(identity):continue
            prior=state['jobs'].get(identity,{})
            row={'job_id':identity,'kind':'video' if collection=='jobs' else 'image',
                'change':'added' if identity not in old else 'removed' if identity not in new else 'updated',
                'saved_status':prior.get('status','not-submitted'),
                'has_saved_task':bool(prior),'has_task_id':bool(prior.get('task_id'))}
            if identity in old and identity in new:
                route=lambda item:{key:item[key] for key in ('model','binding_id') if key in item}
                if route(old[identity])!=route(new[identity]):
                    row['route_change']={'before':route(old[identity]),'after':route(new[identity]),
                        'original_binding':prior.get('binding_snapshot',{}).get('binding_id'),
                        'scope':'future explicit attempt; existing task remains pinned'}
            rows.append(row)
    return {'jobs':rows,'paid_creates':0,
        'note':'Saved task entries cannot be removed. Active/unknown jobs are held. Completed jobs keep all candidates; changed plans need an explicit replan before a new create. Job order is not timeline order.'}


def reference_from_json(root, value, *, image=False):
    """Validate local registered bytes; never read a transport URL or modify plans."""
    if not isinstance(value,dict) or value.get('kind') not in {'image','video','audio'}:
        raise ConfigError('Choose an explicitly typed registered reference JSON')
    if image and value['kind']!='image':raise ConfigError('Image jobs accept image references only')
    if image:
        reference={key:copy.deepcopy(value[key]) for key in ('path','sha256') if key in value}
        if set(reference)!={'path','sha256'}:raise ConfigError('Image reference needs a path and SHA256')
        from .image_production import references
        references(root,{'id':'reference-import','references':[reference]})
        return reference
    from .reference_slices import REFERENCE_FIELDS
    from .media_references import prepare_references
    reference={key:copy.deepcopy(value[key]) for key in REFERENCE_FIELDS if key in value}
    prepare_references(root,[reference])
    return reference
