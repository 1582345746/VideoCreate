"""Read actual history; evaluate route resolution with synthetic credentials only.

No real project is copied/rewritten or resumed. This proves local identity
resolution survives Web metadata/default/rotation/archive edits, not remote
task availability or successful content recovery.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from collections import Counter
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(ROOT/'_local') or output.exists():raise RuntimeError('Choose a fresh F-drive evidence directory')
    output.mkdir(parents=True)
    sys.path.insert(0,str(ROOT/'videocreate/src'))
    from videocreate.config import management as m
    from videocreate.config.storage import atomic_json,ConfigError,load_json,user_config_path
    from videocreate.config_web.changes import Changes
    from videocreate.config_web.service import ConfigService
    from videocreate.runtime.jobs import pinned_binding
    from videocreate.config.bridge import engine_settings
    from videocreate.cli import legacy_engine
    engine=legacy_engine()
    attempts=[]
    def no_network(event,args):
        if event in {'socket.connect','socket.getaddrinfo'}:
            attempts.append(event);raise RuntimeError('History verification is strictly offline')
    sys.addaudithook(no_network)
    config_path=user_config_path().resolve();original=config_path.read_bytes()
    value=load_json(config_path)
    # The real auth objects never enter a fixture or a resolver. Preserve only
    # account/version labels needed to assess the original snapshot identity.
    value=copy.deepcopy(value)
    for upstream in value['upstreams'].values():upstream['auth']={'type':'bearer','api_key':'synthetic-history-key'}
    fixture=output/'synthetic-config.json';atomic_json(fixture,value)
    web=Changes(ConfigService(fixture,read_only=False))
    def change(op,data,identity=None,key=None):
        preview=web.preview({'operation':op,'id':identity,'values':data,'expected_token':m.load(fixture)['token']},session='history-fixture')
        return web.commit({'preview_token':preview['preview_token'],**({'credential':key} if key else {})},session='history-fixture')
    baseline=m.load(fixture)['config']
    for uid in baseline['upstreams']:
        change('upstream.update',{'name':'Duplicate fixture label','notes':'Synthetic history compatibility edit'},uid)
        change('upstream.rotate',{'same_account':True},uid,key='synthetic-rotated-history-key')
    for bid,binding in baseline['bindings'].items():
        change('binding.update',{'display_name':'Duplicate fixture model','pricing':{'currency':'USD','per_request':.01}},bid)
    # Reverse the preferred route when a valid alternative exists; media
    # choices remain independent and are not written into any real project.
    choices={}
    for kind in ('image','video'):
        available=[bid for bid,b in baseline['bindings'].items() if b['enabled'] and not b.get('archived')
            and b['adapter']!='unconfigured' and baseline['models'][b['model']]['kind']==kind
            and bid in baseline['routes'].get(b['model'],{}).get('candidates',[])]
        choices[kind]={'binding':available[-1] if available else '', 'policy':'use-default' if available else 'ask'}
    change('defaults.update',choices)
    for uid in baseline['upstreams']:change('upstream.archive',{},uid)
    modified=m.load(fixture)['config']
    # Guard all resolver entry points: a regression cannot reach real DPAPI.
    with mock.patch('videocreate.runtime.jobs.resolve_key',return_value='synthetic-history-key'), \
         mock.patch('videocreate.config.bridge.resolve_key',return_value='synthetic-history-key'):
        settings_before=engine_settings(baseline,store_root=output)
        settings_after=engine_settings(modified,store_root=output,require_secrets=False)
        summaries=[];inputs=[];counts=Counter();blocked=Counter();statuses=Counter()
        for path in sorted((ROOT/'projects').rglob('project.json')):
            state=path.parent/'state.json';raw=path.read_bytes();project=json.loads(raw.decode('utf-8-sig'))
            inputs.append({'path':path.relative_to(ROOT).as_posix(),'sha256':sha(raw)})
            counts['project_directories']+=1
            if not state.is_file():counts['without_state']+=1;continue
            raw=state.read_bytes();packet=json.loads(raw.decode('utf-8-sig'))
            inputs.append({'path':state.relative_to(ROOT).as_posix(),'sha256':sha(raw)})
            counts['state_files']+=1
            for jid,record in packet.get('jobs',{}).items():
                if not isinstance(record,dict):continue
                snapshot=record.get('binding_snapshot')
                if not snapshot:continue
                statuses['v3:'+str(record.get('status'))]+=1
                def resolved(config):
                    try:
                        binding=pinned_binding(config,snapshot,output)
                        # Hash the identity and exact wire contract. No URLs,
                        # account labels, task IDs, prompts or keys in report.
                        return {'status':'resolved','identity_hash':m.fingerprint(binding.snapshot())}
                    except ConfigError as e:
                        message=str(e)
                        reason='original_upstream_missing' if 'upstream is missing' in message else 'original_address_or_account_changed' if 'address/account changed' in message else 'original_credential_unavailable'
                        return {'status':'blocked','reason':reason}
                before,after=resolved(baseline),resolved(modified)
                assert before==after,'Web edits changed original snapshot resolution'
                counts['v3_snapshots']+=1;counts['v3_'+before['status']]+=1
                counts['v3_known_task_ids']+=bool(record.get('task_id'))
                counts['v3_unknown_submission_records']+=record.get('status')=='submission_unknown'
                if before['status']=='blocked':blocked['v3:'+before['reason']]+=1
                summaries.append({'project':path.parent.relative_to(ROOT).as_posix(),'record_hash':sha(str(jid).encode()),
                    'kind':'v3-snapshot','state':record.get('status'),'has_task_id':bool(record.get('task_id')),
                    'before':before,'after':after,'unchanged':True})
            for sid,record in packet.get('shots',{}).items():
                video=record.get('video',{}) if isinstance(record,dict) else {}
                if not isinstance(video,dict) or not video.get('task_id'):continue
                statuses['legacy:'+str(video.get('status'))]+=1
                provider=video.get('upstream_id') or video.get('provider')
                model=video.get('model') or project.get('video_model') or 'grok-imagine-video-1.5'
                def legacy(settings):
                    try:
                        row=engine.resolved_video_upstream(settings,provider,model)
                        if not row:return {'status':'blocked','reason':'original_alias_or_binding_missing'}
                        # A legacy record lacks a modern binding snapshot.
                        # Stable lookup is useful but cannot prove old endpoint.
                        return {'status':'resolved-without-snapshot','identity_hash':m.fingerprint({k:row.get(k) for k in ('id','upstream_id','base_url','adapter','model_map')})}
                    except ConfigError:return {'status':'blocked','reason':'ambiguous_platform_alias'}
                    except engine.SkillError:return {'status':'blocked','reason':'ambiguous_platform_alias'}
                before,after=legacy(settings_before),legacy(settings_after)
                assert before==after,'Web edits changed legacy model/account resolution'
                counts['legacy_known_tasks']+=1;counts['legacy_'+before['status']]+=1
                if before['status']=='blocked':blocked['legacy:'+before['reason']]+=1
                summaries.append({'project':path.parent.relative_to(ROOT).as_posix(),'record_hash':sha(str(sid).encode()),
                    'kind':'legacy-no-snapshot','state':video.get('status'),'has_task_id':True,
                    'before':before,'after':after,'unchanged':True})
    assert config_path.read_bytes()==original
    assert all(sha((ROOT/r['path']).read_bytes())==r['sha256'] for r in inputs)
    assert not attempts
    report={'ok':True,'scope':'Offline resolution of actual local project/revision snapshots; no resume/poll/download/create',
        'counts':dict(counts),'blocked_baseline_reasons':dict(blocked),'statuses':dict(statuses),
        'local_synthetic_web_edits':['upstream labels','binding labels and prices','independent defaults',
            'same-account synthetic key rotation','all-upstream archive'],
        'records':summaries,'input_files':inputs,'real_config_sha256':sha(original),
        'source_files_unchanged':True,'real_credentials_decrypted':False,'actual_provider_requests':0,
        'paid_creates':0,'existing_samples_regenerated':False,'existing_8765_touched':False,
        'limits':['Records include saved revisions and are not counts of unique paid tasks',
                  'Disabled and archived original accounts remain resolvable only where original identity exists',
                  'Existing missing/ambiguous identities remain blocked; this verifier does not repair them',
                  'Legacy records without snapshots cannot establish original endpoint/remote-model identity',
                  'Local route resolution does not prove remote task/content availability or content acceptance']}
    (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'records','input_files','real_config_sha256'}},ensure_ascii=False))


if __name__=='__main__':main()
