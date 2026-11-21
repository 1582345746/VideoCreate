"""Offline configuration repair with byte-bound previews and exact originals."""
import copy
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from . import management as m
from .schema import validate_config
from .storage import ConfigError, atomic_json, parse_json
from ..runtime.state import state_lock


def sha(raw):return hashlib.sha256(raw).hexdigest()


def versions(text):
    """Read explicit root version tokens even when later punctuation is broken."""
    decoder=json.JSONDecoder();depth=0;index=0;found=[]
    while index<len(text):
        char=text[index]
        if char=='"':
            try:value,end=decoder.raw_decode(text,index)
            except ValueError:break
            if depth==1 and value=='schema_version':
                tail=end
                while tail<len(text) and text[tail].isspace():tail+=1
                if tail<len(text) and text[tail]==':':
                    tail+=1
                    while tail<len(text) and text[tail].isspace():tail+=1
                    try:item,_=decoder.raw_decode(text,tail);found.append(item)
                    except ValueError:pass
            index=end;continue
        if char in '{[':depth+=1
        elif char in '}]':depth-=1
        index+=1
    return found


def _read(path):
    raw=Path(path).read_bytes();value=None;text=None;errors=[]
    try:
        text=raw.decode('utf-8-sig');value=parse_json(text)
    except UnicodeError:errors=['Configuration text is not valid UTF-8; select a readable configuration draft or backup']
    except ConfigError as exc:errors=[str(exc)]
    explicit=versions(text) if text is not None else []
    newer=any(type(v) is not int or v not in (3,4) for v in explicit)
    if newer:
        status='read-only';errors=['Unsupported configuration version; preserve file and upgrade VideoCreate']
    elif value is None:status='syntax-error'
    else:
        errors=validate_config(value)
        status='schema-error' if errors else 'valid'
    return raw,value,{'path':str(Path(path).resolve()),'source_token':sha(raw),'bytes':len(raw),
        'status':status,'errors':errors,'can_repair':status in {'syntax-error','schema-error'},
        'paid_creates':0,'network_requests':0}


def inspect(path):
    path=Path(path).resolve();_,_,report=_read(path);rows=[]
    for backup in sorted((path.parent/'backups').glob('*.json')):
        try:
            raw,value,state=_read(backup)
            if state['status']=='valid':rows.append({'path':str(backup.resolve()),'sha256':sha(raw),
                'revision':value.get('revision',0),'schema_version':value['schema_version']})
        except (OSError,ValueError):continue
    return {**report,'backups':rows}


def _identity(uid,item):
    if not isinstance(item,dict):return None
    address,account=item.get('base_url'),item.get('account_id',uid)
    if not isinstance(address,str) or not isinstance(account,str):return None
    try:
        url=urlsplit(address)
        if (not url.hostname or url.username or url.password or url.query or url.fragment
                or url.port==-1 or (url.scheme!='https' and not
                    (url.scheme=='http' and url.hostname in {'localhost','127.0.0.1','::1'}))):return None
    except ValueError:return None
    return address.rstrip('/'),account


def _known(candidate, current, baseline):
    preserved=[];unverified=[]
    # The selected valid baseline defines identities it contains. Other current
    # entries are retained too, so an old backup cannot erase later identities.
    for origin,source in [('current',current),('baseline',baseline)]:
        if not isinstance(source,dict):continue
        for group in ('models','upstreams','bindings','routes'):
            entries=source.get(group,{})
            if not isinstance(entries,dict):
                unverified.append('$.current.'+group);continue
            for key,item in entries.items():
                if key in candidate[group]:continue
                if not isinstance(item,dict):
                    raise ConfigError('A damaged catalog entry must be explicitly repaired in the draft: '+group+'.'+key)
                kept=copy.deepcopy(item)
                if group in {'models','upstreams','bindings'}:kept['archived']=True
                if group=='bindings':kept['enabled']=False
                candidate[group][key]=kept
                preserved.append({'group':group,'id':key,'source':origin})
    identities={}
    for source in (current,baseline):
        if not isinstance(source,dict) or not isinstance(source.get('upstreams'),dict):continue
        for uid,item in source['upstreams'].items():
            identity=_identity(uid,item)
            if identity is None:unverified.append('$.upstreams.'+uid);continue
            if uid in identities and identities[uid]!=identity:
                raise ConfigError('Current and baseline disagree on upstream identity '+uid+'; reconcile the baseline using separate IDs')
            identities[uid]=identity
    protected=[]
    for uid,(address,account) in identities.items():
        proposed=candidate['upstreams'].get(uid,{})
        if proposed.get('base_url','').rstrip('/')!=address.rstrip('/') or proposed.get('account_id',uid)!=account:
            raise ConfigError('Preserve the known upstream address/account for '+uid+'; use a new ID for another account')
        protected.append(uid)
    return preserved,protected,unverified


def _preview(path, text, *, source_token, baseline=None):
    path=Path(path).resolve();raw,current,state=_read(path)
    if not source_token or state['source_token']!=source_token:
        raise ConfigError('Configuration bytes changed; inspect and preview again')
    if not state['can_repair']:
        raise ConfigError('Valid configurations use normal save/restore; unsupported versions remain read-only')
    candidate=parse_json(text)
    errors=validate_config(candidate)
    if errors:raise ConfigError('; '.join(errors))
    candidate=m.migrate(candidate)
    old=None;baseline_info=None
    if baseline is not None:
        baseline=Path(baseline).resolve()
        if baseline==path:raise ConfigError('Select a separate valid baseline backup')
        baseline_raw,old,checked=_read(baseline)
        if checked['status']!='valid':raise ConfigError('The selected baseline must be a valid supported configuration')
        baseline_info={'path':str(baseline),'sha256':sha(baseline_raw)}
    preserved,protected,unverified=_known(candidate,current,old)
    errors=validate_config(candidate)
    if errors:raise ConfigError('Retained identities need explicit correction in the draft: '+'; '.join(errors))
    report={'ok':True,'path':str(path),'source_token':sha(raw),'source_status':state['status'],
        'candidate_hash':m.fingerprint(candidate),'draft_sha256':sha(text.encode('utf-8')),
        'baseline':baseline_info,'preserved_entries':preserved,
        'protected_upstream_ids':sorted(protected),'unverified_identity_paths':sorted(unverified),
        'identity_basis':'selected-baseline-and-readable-current' if old else 'readable-current',
        'original_structure_verified':current is not None,
        'changed_paths':m.changed_paths(current,candidate) if current is not None else ['$ (original JSON could not be parsed)'],
        'counts':{group:len(candidate[group]) for group in ('models','upstreams','bindings','routes')},
        'original_backup':str(path.parent/'backups'/(path.stem+'-damaged-'+sha(raw)+'.raw')),
        'notes':['The exact original bytes are retained before replacement; credentials, projects and task evidence are not edited.',
            'Missing known catalog entries are retained archived/disabled; readable current and baseline identities must agree.',
            'An unparseable original cannot prove every historical identity; compare the local draft and backups before applying.',
            'This is offline validation, not proof of credential availability, task recovery or upstream capability.'],
        'paid_creates':0,'network_requests':0}
    report['preview_token']=m.fingerprint(report)
    return report,candidate,raw,current,old


def preview(path, text, *, source_token, baseline=None):
    return _preview(path,text,source_token=source_token,baseline=baseline)[0]


def apply(path, text, *, source_token, preview_token, baseline=None, on_prepared=None):
    path=Path(path).resolve()
    with state_lock(path.parent/'config-lock'):
        report,candidate,raw,current,old=_preview(path,text,source_token=source_token,baseline=baseline)
        if not preview_token or report['preview_token']!=preview_token:
            raise ConfigError('Repair draft or baseline changed; preview again before replacing configuration')
        backup=Path(report['original_backup']);backup.parent.mkdir(parents=True,exist_ok=True)
        try:
            with backup.open('xb') as stream:
                os.chmod(backup,0o600);stream.write(raw);stream.flush();os.fsync(stream.fileno())
        except FileExistsError:
            if backup.read_bytes()!=raw:raise ConfigError('Original backup path already contains different bytes; configuration preserved') from None
        if backup.read_bytes()!=raw:raise ConfigError('Original backup verification failed; configuration preserved')
        revisions=[v.get('revision',0) for v in (candidate,current,old) if isinstance(v,dict) and type(v.get('revision',0)) is int]
        candidate.update(revision=max([0,*revisions])+1,updated_at=m.stamp())
        # Recheck after the exact backup, too. Cooperating writers hold config-lock.
        if path.read_bytes()!=raw:raise ConfigError('Configuration changed while backing up; inspect again')
        if on_prepared is not None:on_prepared(m.fingerprint(candidate))
        atomic_json(path,candidate)
        audit={**report,'repaired_at':candidate['updated_at'],'revision':candidate['revision'],
            'after':m.fingerprint(candidate),'operation':'configuration-repair'}
        warning=None
        try:atomic_json(path.parent/'config-history'/('repair-'+audit['after']+'.json'),audit)
        except OSError:warning='Configuration repaired; history write failed. Exact original backup retained.'
        return {'ok':True,'path':str(path),'revision':candidate['revision'],'token':audit['after'],
            'original_backup':str(backup),'original_sha256':sha(raw),'preserved_entries':report['preserved_entries'],
            'original_structure_verified':report['original_structure_verified'],'warning':warning,
            'paid_creates':0,'network_requests':0}
