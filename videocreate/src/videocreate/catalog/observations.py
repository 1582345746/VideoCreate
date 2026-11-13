"""Account-scoped catalog observations and diffs; absence never removes config."""
import copy
from datetime import datetime
from pathlib import Path

from ..config.management import fingerprint,stamp
from ..config.storage import ConfigError,atomic_json,load_json
from ..runtime.state import state_lock


def identity(config,upstream):
    item=config.get('upstreams',{}).get(upstream)
    if not item:raise ConfigError('Unknown upstream')
    return {'upstream':upstream,'base_url':item['base_url'].rstrip('/'),
        'account_id':item.get('account_id',upstream)}


def url(origin):
    base=origin['base_url']
    return base+('/models' if base.endswith('/v1') else '/v1/models')


def ids(values):
    if not isinstance(values,list) or len(values)>10000:
        raise ConfigError('Catalog needs at most 10000 explicit model IDs')
    if any(not isinstance(v,str) or not v.strip() or len(v)>1024 or
            any(ord(c)<32 or 0xD800<=ord(c)<=0xDFFF for c in v) for v in values):
        raise ConfigError('Catalog model IDs must be nonempty Unicode strings without control characters, at most 1024 characters')
    return list(dict.fromkeys(values))


def checked(packet,origin):
    fields={'schema_version','identity','url','observed_at','ids','evidence_kind','observation_hash'}
    if not isinstance(packet,dict) or set(packet)!=fields or type(packet.get('schema_version')) is not int or packet['schema_version']!=1:
        raise ConfigError('Unsupported catalog observation; preserve the file and refresh with this version')
    value=copy.deepcopy(packet);digest=value.pop('observation_hash')
    if fingerprint(value)!=digest:raise ConfigError('Catalog observation changed; refresh or choose an intact observation')
    if value['identity']!=origin or value['url']!=url(origin):
        raise ConfigError('Catalog observation belongs to a different upstream address or account')
    if value['evidence_kind']!='catalog-only' or ids(value['ids'])!=value['ids']:
        raise ConfigError('Catalog observation is not an exact catalog-only ID list')
    try:
        instant=datetime.fromisoformat(value['observed_at'])
        if instant.tzinfo is None:raise ValueError()
    except (TypeError,ValueError):raise ConfigError('Catalog observation needs a dated, timezone-aware source') from None
    return packet


def folder(store_root,origin):
    return Path(store_root)/'runtime'/'catalog-observations'/fingerprint(origin)


def _history(store_root,origin):
    result=[];invalid=0
    for path in folder(store_root,origin).glob('*.json'):
        try:
            packet=checked(load_json(path),origin)
            if path.stem!=packet['observation_hash']:raise ConfigError('Observation filename mismatch')
            result.append((packet,path))
        except (OSError,ValueError):invalid+=1
    result.sort(key=lambda row:(datetime.fromisoformat(row[0]['observed_at']),row[0]['observation_hash']))
    return result,invalid


def report(config,upstream,packet,*,previous=None,evidence=None,invalid=0):
    origin=identity(config,upstream);checked(packet,origin)
    if previous:checked(previous,origin)
    current=packet['ids'];seen=set(current);before=set(previous['ids']) if previous else set()
    local={}
    for bid,item in config['bindings'].items():
        if item['upstream']==upstream:local.setdefault(item['remote_model'],[]).append(bid)
    missing=sorted(set(local)-seen)
    rows=[]
    # Include disappeared, never-imported names as well as missing local bindings.
    # They remain historical observations, not new local model records.
    absent=sorted((before|set(local))-seen)
    for remote in [*current,*absent]:
        present=remote in seen
        change=('added' if remote not in before else 'unchanged') if previous and present else (
            'not-in-latest' if previous and remote in before else 'first-observation' if present else 'not-observed')
        rows.append({'remote_model':remote,'catalog_status':'present' if present else 'absent',
            'local_bindings':local.get(remote,[]),'local_status':'registered' if remote in local else 'not-configured',
            'change':change,'importable':present and remote not in local})
    return {'ok':True,'upstream':upstream,'identity':origin,'url':packet['url'],'observed_at':packet['observed_at'],
        'ids':list(current),'observation':packet,'evidence':str(evidence) if evidence else None,
        'evidence_kind':'catalog-only','previous_observation':previous['observation_hash'] if previous else None,
        'previous_observed_at':previous['observed_at'] if previous else None,'baseline_available':bool(previous),
        'changes':{'added_since_previous':sorted(seen-before) if previous else None,
            'not_in_latest_since_previous':sorted(before-seen) if previous else None,
            'new_to_configuration':[remote for remote in current if remote not in local],
            'local_not_in_observation':missing},'rows':rows,'unreadable_observations':invalid,
        'config_changed':False,'paid_creates':0,'network_requests':0,
        'note':'Catalog observations describe this account at one time; absence does not delete, disable or prove model removal. Names do not verify protocol, capabilities, pricing or quality.'}


def record(config,upstream,values,*,store_root):
    origin=identity(config,upstream);values=ids(values);target=folder(store_root,origin)
    with state_lock(target):
        history,invalid=_history(store_root,origin)
        packet={'schema_version':1,'identity':origin,'url':url(origin),'observed_at':stamp(),
            'ids':values,'evidence_kind':'catalog-only'}
        packet['observation_hash']=fingerprint(packet)
        path=target/(packet['observation_hash']+'.json');atomic_json(path,packet)
        result=report(config,upstream,packet,previous=history[-1][0] if history else None,evidence=path,invalid=invalid)
    return result


def show(config,upstream,*,store_root,file=None):
    origin=identity(config,upstream);history,invalid=_history(store_root,origin)
    if file is not None:
        packet=checked(load_json(Path(file)),origin);path=Path(file).resolve()
        prior=[row for row in history if datetime.fromisoformat(row[0]['observed_at'])<datetime.fromisoformat(packet['observed_at'])]
        previous=prior[-1][0] if prior else None
    else:
        if not history:
            return {'ok':True,'status':'no-observation','upstream':upstream,'identity':origin,
                'unreadable_observations':invalid,'paid_creates':0,'network_requests':0,'config_changed':False,
                'note':'No intact observation for this address/account. Use explicit read-only refresh; legacy unscoped catalogs are retained.'}
        packet,path=history[-1];previous=history[-2][0] if len(history)>1 else None
    return report(config,upstream,packet,previous=previous,evidence=path,invalid=invalid)
