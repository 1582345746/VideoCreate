"""Allowlisted offline provider diagnostics; export exactly the current preview."""
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .catalog import observations
from .catalog.bindings import configured_binding
from .catalog.evidence import STAGES, status as evidence_status
from .config.management import fingerprint,stamp
from .config.schema import validate_config
from .config.storage import ConfigError,parse_json


def _read(path):
    try:raw=Path(path).read_bytes()
    except FileNotFoundError:return None,None
    except OSError:raise ConfigError('Configuration could not be read locally; no diagnostic file was written') from None
    token=hashlib.sha256(raw).hexdigest()
    try:return token,parse_json(raw.decode('utf-8-sig'))
    except (ValueError,UnicodeError):return token,None


def _time(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is not None:return parsed.astimezone(timezone.utc).isoformat()
    except (AttributeError,ValueError,TypeError):pass
    return None


def _limits(caps):
    # User-entered strings are not copied, including custom resolution/MIME labels.
    result={key:caps[key] for key in ('max_prompt_bytes','max_reference_images','max_additional_reference_images',
        'max_animation_frames','max_animation_duration_seconds','image_to_video_requires_primary') if key in caps}
    if caps.get('duration'):result['duration']={k:caps['duration'][k] for k in ('minimum','maximum','step')}
    if caps.get('prompt_limit'):result['prompt_limit']={k:caps['prompt_limit'][k] for k in ('maximum','counting_rule')}
    result['audio_control']=caps.get('audio_control','unknown')
    for key,pattern in [('resolutions',r'[0-9]{2,5}p'),('aspect_ratios',r'[0-9]{1,3}:[0-9]{1,3}'),
            ('image_sizes',r'auto|[0-9]{2,5}x[0-9]{2,5}'),('output_formats',r'png|jpeg|jpg|webp|gif')]:
        values=caps.get(key,[])
        result[key]=[v for v in values if re.fullmatch(pattern,v)]
        result[key+'_omitted_count']=len(values)-len(result[key])
    result['conditions']=[]
    for condition in caps.get('conditions',[]):
        when={k:v if (k=='operation' or re.fullmatch(r'[0-9]{2,5}p' if k=='resolution' else r'[0-9]{1,3}:[0-9]{1,3}',v))
            else '[custom value omitted]' for k,v in condition['when'].items()}
        result['conditions'].append({'when':when,'max_seconds':condition['max_seconds']})
    typed=caps.get('media_reference_limits')
    result['typed_references_configured']=bool(typed)
    if typed:
        result['media_reference_limits']={key:typed[key] for key in ('maximum_total_count','maximum_total_bytes',
            'minimum_url_validity_seconds','allowed_combinations','audio_reference_with_generated_audio') if key in typed}
        for kind in ('image','video','audio'):
            result['media_reference_limits'][kind]={key:value for key,value in typed[kind].items()
                if type(value) in (int,float,bool)}
    return result


def _catalog(config,uid,store_root):
    try:
        value=observations.show(config,uid,store_root=store_root)
        result={'status':'not-observed' if value.get('status')=='no-observation' else 'observed',
            'ignored_observations':value['unreadable_observations']}
        if value.get('observation'):
            result.update(observed_at=_time(value['observed_at']),model_count=len(value['ids']),
                baseline_available=value['baseline_available'],
                changes={k:len(v) if v is not None else None for k,v in value['changes'].items()})
        return result
    except (OSError,ValueError,TypeError):return {'status':'unreadable'}


def _build(path,*,upstream=None,include_identifiers=False,generated_at=None):
    if type(include_identifiers) is not bool:raise ConfigError('Diagnostic identifier option must be boolean')
    if upstream is not None and (not isinstance(upstream,str) or not upstream):raise ConfigError('Diagnostic upstream must be an explicit identifier')
    source,config=_read(path)
    report={'schema_version':1,'product':'VideoCreate','report_type':'provider-diagnostics',
        'generated_at':generated_at or stamp(),'disclosure':'identifiers' if include_identifiers else 'anonymous',
        'environment':{'videocreate_version':__version__,'python_version':'.'.join(map(str,sys.version_info[:3])),
            'platform':platform.system(),'ffmpeg_found':bool(shutil.which('ffmpeg')),'ffprobe_found':bool(shutil.which('ffprobe'))},
        'configuration':{'status':'missing' if source is None else 'unreadable'},
        'upstreams':[],'bindings':[],'routes':[],'defaults':{},'selection':{},
        'network_requests':0,'external_credential_reads':0,'paid_creates':0,
        'inline_credential_handling':'Inline values in saved configuration are used only to redact optional labels; values are never exported.',
        'scope':'saved configuration and local evidence summaries; no environment secrets, DPAPI, network, projects scan or generation',
        'omitted':['credentials and references','account and credential version IDs','notes and free text',
            'local paths and task IDs','raw logs and receipts','full URLs, queries and signatures','actual price amounts'],
        'note':'Catalog, contract, smoke and quality observations are independent. No credential, complete request, availability, billing or artistic-quality approval is performed.'}
    if config is None:return source,report
    errors=validate_config(config)
    version=config.get('schema_version')
    report['configuration']={'status':'invalid' if errors else 'valid',
        'supported_version':type(version) is int and version in (3,4),'validation_issue_count':len(errors)}
    if type(version) is int:report['configuration']['schema_version']=version
    if errors:return source,report
    if upstream is not None and upstream not in config['upstreams']:raise ConfigError('Selected diagnostic upstream no longer exists; reload the configuration')
    report['configuration']['revision']=config.get('revision',0)
    report['configuration']['scope']='one-upstream' if upstream else 'all-upstreams'
    urefs={uid:'upstream-'+str(i+1).zfill(3) for i,uid in enumerate(config['upstreams'])}
    brefs={bid:'binding-'+str(i+1).zfill(3) for i,bid in enumerate(config['bindings'])}
    mrefs={mid:'model-'+str(i+1).zfill(3) for i,mid in enumerate(config['models'])}
    # Inline values can be removed without decrypting or consulting env vars.
    secrets=[u['auth']['api_key'] for u in config['upstreams'].values() if u['auth'].get('api_key')]
    def label(value):
        for secret in sorted(secrets,key=len,reverse=True):value=value.replace(secret,'[redacted]')
        return ''.join(c if ord(c)>=32 and not 0xD800<=ord(c)<=0xDFFF else '?' for c in value)[:1024]
    selected={uid for uid in config['upstreams'] if upstream is None or uid==upstream}
    bids={bid for bid,b in config['bindings'].items() if b['upstream'] in selected}
    for uid,u in config['upstreams'].items():
        if uid not in selected:continue
        mode=next(({'api_key':'inline','env':'environment','secret_ref':'encrypted-reference'}[k] for k in ('api_key','env','secret_ref') if k in u['auth']),'unknown')
        row={'ref':urefs[uid],'archived':u.get('archived',False),'credential':{'mode':mode,'availability':'not-checked'},
            'local_limits':{k:u[k] for k in ('max_concurrent_submissions','request_timeout_seconds') if k in u},
            'configured_quotas':{k:v for k,v in u.get('quotas',{}).items()},
            'binding_count':sum(b['upstream']==uid for b in config['bindings'].values()),'catalog':_catalog(config,uid,Path(path).parent)}
        if include_identifiers:row['identifiers']={'id':label(uid),'api_host':label(urlsplit(u['base_url']).hostname or '')}
        report['upstreams'].append(row)
    for bid,b in config['bindings'].items():
        if bid not in bids:continue
        row={'ref':brefs[bid],'upstream_ref':urefs[b['upstream']],'model_ref':mrefs[b['model']],
            'kind':config['models'][b['model']]['kind'],'adapter':b['adapter'],'enabled':b['enabled'],
            'archived':b.get('archived',False) or config['models'][b['model']].get('archived',False) or config['upstreams'][b['upstream']].get('archived',False),
            'draft':b['adapter']=='unconfigured' or b.get('setup_status')=='draft','operations':list(b['operations']),
            'pricing':{'configured':bool(b.get('pricing')),'status':(b.get('pricing') or {}).get('status','unspecified'),
                'tiers':len((b.get('pricing') or {}).get('tiers',[])),'listed_only':bool(b.get('listed_pricing')) and not bool(b.get('pricing'))},
            'evidence':{}}
        if include_identifiers:row['identifiers']={'id':label(bid),'model':label(b['model']),'remote_model':label(b['remote_model'])}
        try:
            binding=configured_binding(config,bid)
            row['limits']=None if row['draft'] else _limits(binding.capabilities)
            for op in b['operations']:
                value=evidence_status(Path(path).parent,binding,operation=op)
                row['evidence'][op]={'stages':{stage:{'status':value['stages'][stage]['status'],
                    'receipt_count':len(value['stages'][stage]['receipts'])} for stage in STAGES},
                    'stale_receipt_count':len(value['stale_receipts'])}
        except (OSError,ValueError,TypeError,KeyError):row['local_contract_status']='unreadable'
        else:row['local_contract_status']='draft' if row['draft'] else 'configured'
        row['issues']=[name for name,condition in [('draft',row['draft']),('disabled',not row['enabled']),('archived',row['archived']),
            ('contract-unreadable',row['local_contract_status']=='unreadable'),('price-unverified',row['pricing']['status']!='confirmed')] if condition]
        report['bindings'].append(row)
    for mid,route in config['routes'].items():
        candidates=[brefs[bid] for bid in route['candidates'] if bid in bids]
        if not candidates:continue
        report['routes'].append({'model_ref':mrefs[mid],'policy':route['policy'],'candidates':candidates,
            'outside_scope_candidates':len(route['candidates'])-len(candidates),
            'preferred_binding':brefs[route['preferred_binding']] if route['preferred_binding'] in bids else None})
    visible_models={config['bindings'][bid]['model'] for bid in bids}
    report['defaults']={kind:mrefs[mid] if mid in visible_models else None for kind,mid in config['defaults'].items() if kind in ('video_model','image_model')}
    report['selection']={kind:{k:v for k,v in config.get('selection',{}).get(kind,{}).items() if k in ('when_unspecified','remember_scope')}
        for kind in ('image','video')}
    report['counts']={'upstreams':len(report['upstreams']),'bindings':len(report['bindings']),'routes':len(report['routes']),
        'drafts':sum(row['draft'] for row in report['bindings']),'enabled':sum(row['enabled'] for row in report['bindings'])}
    return source,report


def preview(path,*,upstream=None,include_identifiers=False):
    source,report=_build(Path(path),upstream=upstream,include_identifiers=include_identifiers)
    value={'ok':True,'schema_version':1,'source_token':source,'options':{'upstream':upstream,'include_identifiers':include_identifiers},'report':report}
    return {**value,'preview_token':fingerprint(value)}


def export(path,preview,output,*,token):
    fields={'ok','schema_version','source_token','options','report','preview_token'}
    try:
        if set(preview)!=fields or type(preview['schema_version']) is not int or preview['schema_version']!=1 or preview['ok'] is not True:raise ValueError()
        if token!=preview['preview_token'] or token!=fingerprint({k:v for k,v in preview.items() if k!='preview_token'}):raise ValueError()
        if set(preview['options'])!={'upstream','include_identifiers'}:raise ValueError()
        if not _time(preview['report']['generated_at']):raise ValueError()
    except (ValueError,TypeError,KeyError):raise ConfigError('Diagnostic preview is invalid or changed; create a fresh preview') from None
    source,current=_build(Path(path),generated_at=preview['report']['generated_at'],**preview['options'])
    if source!=preview['source_token'] or current!=preview['report'] or _read(path)[0]!=source:
        raise ConfigError('Configuration or diagnostic observations changed; preview again before exporting')
    target=Path(output).resolve()
    if target==Path(path).resolve() or target.suffix.casefold()!='.json':raise ConfigError('Choose a new diagnostic JSON file separate from the configuration')
    payload=(json.dumps(current,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    temporary=None
    try:
        fd,temporary=tempfile.mkstemp(prefix='.videocreate-diagnostic-',suffix='.tmp',dir=target.parent)
        with os.fdopen(fd,'wb') as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
        if _read(path)[0]!=source:raise ConfigError('Configuration changed during diagnostic export; preview again')
        # Atomic no-replace publication: an existing file is never overwritten.
        os.link(temporary,target)
    except FileExistsError:raise ConfigError('Diagnostic output already exists; choose a new filename') from None
    except OSError:raise ConfigError('Diagnostic file could not be exported; choose an existing writable local folder') from None
    finally:
        if temporary is not None:Path(temporary).unlink(missing_ok=True)
    return {'ok':True,'status':'exported','output':str(target),'report_sha256':hashlib.sha256(payload).hexdigest(),
        'network_requests':0,'external_credential_reads':0,'paid_creates':0,'config_changed':False}
