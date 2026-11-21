"""Exact catalog terms for Codex; no credential lookup, selection or task recovery."""
from ..config.management import catalog, fingerprint
from ..config.storage import ConfigError


def identify(config, *, kind, model_name=None, upstream_name=None, upstream=None):
    if kind not in {'image','video'}:
        raise ConfigError('Catalog identity lookup needs an explicit image or video kind')
    for value in (model_name,upstream_name,upstream):
        if value is not None and (not isinstance(value,str) or not value.strip() or len(value)>16000):
            raise ConfigError('Catalog identity terms must be nonempty strings of at most 16000 characters')
    # Match stored spelling exactly. Codex extracts terms from the request; this
    # helper neither parses arbitrary sentences nor invents name equivalences.
    known_upstreams=config['upstreams']
    if upstream_name is None:
        upstream_matches={uid:[] for uid in known_upstreams}
    elif upstream_name in known_upstreams:
        upstream_matches={upstream_name:['upstream_id']}
    else:
        upstream_matches={uid:[field for field in ('display_name','platform') if row.get(field)==upstream_name]
            for uid,row in known_upstreams.items() if any(row.get(field)==upstream_name for field in ('display_name','platform'))}
    if upstream is not None:
        upstream_matches={uid:fields for uid,fields in upstream_matches.items() if uid==upstream}
    rows=[row for row in catalog(config,kind=kind) if row['upstream_id'] in upstream_matches]
    exact_model=model_name in config['models']
    matches=[]
    for row in rows:
        model=config['models'][row['model']]
        if model_name is None:
            fields=[]
        elif exact_model:
            if row['model']!=model_name:continue
            fields=['model_id']
        else:
            values={'remote_model':row['remote_model'],'binding_name':row['display_name'],
                    'model_name':model.get('display_name'),'family':row['family']}
            fields=[name for name,value in values.items() if value==model_name]
            if not fields:continue
        state=('archived' if row['archived'] else 'draft' if row['setup_status']=='draft' or
               row['adapter']=='unconfigured' else 'enabled' if row['enabled'] else 'disabled')
        matches.append({'binding_id':row['id'],'model_id':row['model'],'upstream_id':row['upstream_id'],
            'upstream_name':row['upstream_name'],'name':row['display_name'],'remote_model':row['remote_model'],
            'kind':kind,'family':row['family'],'adapter':row['adapter'],'operations':list(row['operations']),
            'state':state,'registered_in_route':row['id'] in config['routes'].get(row['model'],{}).get('candidates',[]),
            'matched_by':{'upstream':upstream_matches[row['upstream_id']],'model':fields}})
    # Never decrypt external stores just to print names. Suppress known inline
    # credentials/references even if they were pasted into a saved label.
    sensitive=sorted({a[field] for u in known_upstreams.values() for a in [u.get('auth',{})]
        for field in ('api_key','env','secret_ref') if isinstance(a.get(field),str) and a[field]},key=len,reverse=True)
    def clean(value):
        if isinstance(value,str):
            for secret in sensitive:value=value.replace(secret,'[hidden]')
            return value
        if isinstance(value,list):return [clean(item) for item in value]
        if isinstance(value,dict):return {key:clean(item) for key,item in value.items()}
        return value
    identifiers_redacted=(any(clean(row[key])!=row[key] for row in matches
        for key in ('binding_id','model_id','upstream_id')) or any(clean(uid)!=uid for uid in upstream_matches))
    ambiguities=[]
    for key,name in (('upstream_id','upstream'),('model_id','model')):
        if len({row[key] for row in matches})>1:ambiguities.append(name)
    if len(matches)>1 and not ambiguities:ambiguities.append('binding')
    return {'ok':True,'status':'no_matches' if not matches else 'ambiguous' if len(matches)>1 else
            'review_required' if identifiers_redacted else 'identified',
        'config_token':fingerprint(config),'kind':kind,'matches':clean(matches),
        'upstream_matches':clean([{'id':uid,'name':known_upstreams[uid].get('display_name') or uid,
            'archived':bool(known_upstreams[uid].get('archived')),'matched_by':fields}
            for uid,fields in sorted(upstream_matches.items())]),
        'needs_choice':ambiguities,'identifiers_redacted':identifiers_redacted,
        'matching':'exact-case-sensitive-terms-with-stable-ID-priority',
        'readiness':'not-checked','credentials_checked':False,'selection_changed':False,
        'network_requests':0,'paid_creates':0,
        'next':'Pass canonical IDs through normal selection/request preflight; multiple matches require clarification; never use name lookup to recover an existing task'}
