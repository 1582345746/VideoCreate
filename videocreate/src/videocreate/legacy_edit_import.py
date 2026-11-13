"""Preview and copy a native legacy edit into an independent v3 project."""
import copy
import hashlib
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config.storage import ConfigError, atomic_json, load_json
from .planning.project import content_hash, save_bundle, validate_plan, within
from .planning.profiles import create
from .timeline.finishing import FILTERS, STYLES
from .timeline.model import mapping, number
from .timeline.render import probe


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def fields(value, allowed, label):
    if not isinstance(value,dict) or set(value)-set(allowed):
        raise ConfigError(label+': unsupported fields; migration never silently drops settings')


def presets(value, label):
    if (not isinstance(value,list) or any(not isinstance(v,str) or v not in FILTERS for v in value)
            or len(set(value))!=len(value)):
        raise ConfigError(label+': use unique supported filter presets')
    return value


def srt(path):
    try:text=path.read_text(encoding='utf-8-sig').replace('\r\n','\n').replace('\r','\n')
    except UnicodeError:raise ConfigError('Legacy subtitles must be UTF-8 SRT; convert explicitly first') from None
    cues=[]
    def seconds(stamp):
        hours,minutes,seconds,millis=map(int,re.split('[:,]',stamp))
        if minutes>59 or seconds>59:raise ConfigError('SRT timestamp is invalid')
        return hours*3600+minutes*60+seconds+millis/1000
    for block in re.split(r'\n[ \t]*\n',text.strip()):
        lines=block.split('\n')
        if len(lines)<3 or not lines[0].strip().isdigit():raise ConfigError('Use numbered UTF-8 SRT subtitle blocks')
        match=re.fullmatch(r'(\d{2,}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2,}:\d{2}:\d{2},\d{3})',lines[1].strip())
        if not match:raise ConfigError('SRT positioning/markup timing extensions need explicit conversion')
        body='\n'.join(lines[2:])
        if re.search(r'<[^>]+>|\{\\',body):raise ConfigError('Styled SRT markup needs explicit conversion to literal v3 captions')
        cues.append({'start':seconds(match[1]),'end':seconds(match[2]),'text':body})
    return cues


def preview(source, destination):
    source,destination=Path(source).resolve(),Path(destination).resolve()
    if not source.is_dir():raise ConfigError('Select the legacy project directory containing edit-plan.json')
    if destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ConfigError('Choose a new, separate destination outside the legacy project')
    if not destination.parent.is_dir():raise ConfigError('Destination parent directory must already exist')
    plan_path=within(source,'edit-plan.json');plan=load_json(plan_path)
    fields(plan,('version','backend','timeline','filters','overlays','audio_mix','subtitles','finishing',
                 'preview_evidence','deliveries','migration'),'edit-plan')
    if isinstance(plan.get('version'),bool) or plan.get('version') not in (1,2):raise ConfigError('Only legacy edit-plan versions 1 and 2 are supported')
    backend=plan.get('backend',{})
    fields(backend,('requested','selected','selection_reason'),'backend')
    if backend.get('selected')!='native':raise ConfigError('Only a native edit plan has a verified local migration contract')
    timeline=plan.get('timeline',{});fields(timeline,('target_size','fps','inputs','transitions'),'timeline')
    if timeline.get('fps',30)!=30:raise ConfigError('Legacy native rendering uses 30 fps; resolve the conflicting fps field explicitly')
    inputs=timeline.get('inputs')
    if not isinstance(inputs,list) or not inputs:raise ConfigError('Legacy plan needs ordered video inputs')
    if plan.get('overlays',[])!=[]:raise ConfigError('Legacy overlays are not a verified native contract; convert them explicitly')
    files={'edit-plan.json':{'sha256':digest(plan_path),'kind':'plan'}}
    local_sources=[];segments=[];clips=[];shots=[];rows=[];ids=set()
    def media_file(relative,kind):
        if not isinstance(relative,str) or not relative.strip() or Path(relative).is_absolute():raise ConfigError('Migration paths must be relative files inside the source project')
        path=within(source,relative);sha=digest(path)
        record={'sha256':sha,'kind':kind}
        if kind=='video':
            if path.suffix.lower() not in {'.mp4','.mov','.mkv','.webm'}:raise ConfigError('Legacy inputs must be video files')
            try:record['media']=probe(path)
            except (subprocess.CalledProcessError,ValueError,KeyError):raise ConfigError('Legacy video could not be probed') from None
            if not number(record['media']['duration']) or record['media']['duration']<=0:raise ConfigError('Legacy video duration is invalid')
        elif kind=='audio':
            command=[shutil.which('ffprobe') or 'ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]
            import json
            try:
                body=json.loads(subprocess.run(command,capture_output=True,check=True).stdout)
                duration=float(body['format']['duration'])
                if not any(s.get('codec_type')=='audio' for s in body['streams']) or not math.isfinite(duration) or duration<=0:raise ValueError()
            except (subprocess.CalledProcessError,KeyError,ValueError):raise ConfigError('Legacy audio could not be probed') from None
            record['duration']=duration
        if relative in files and files[relative]!=record:raise ConfigError('One source path cannot describe conflicting media kinds')
        files[relative]=record
        return path,record
    for index,item in enumerate(inputs,1):
        fields(item,('id','path','edit_in','edit_out','generation_seconds','speed','filters','tail_trim'),'input')
        identity=item.get('id')
        if not isinstance(identity,str) or not identity.strip() or identity in ids:raise ConfigError('Legacy input IDs must be unique nonempty strings')
        ids.add(identity);path,record=media_file(item.get('path'),'video');media=record['media']
        start,end,rate=item.get('edit_in',0),item.get('edit_out'),item.get('speed',1)
        end=media['duration'] if end in (None,'') else end
        if not all(number(v) for v in (start,end,rate)) or not 0<=start<end<=media['duration'] or not .25<=rate<=4:
            raise ConfigError(identity+': source window/rate must be finite and inside actual media')
        selected=presets(item.get('filters',[]),identity+'.filters')
        sid=f'legacy-{index:03}';shot='shot-'+sid;clip='clip-'+sid;seg='seg-'+sid
        copied='assets/local-sources/'+record['sha256']+path.suffix.lower()
        local_sources.append({'id':sid,'kind':'video','path':copied,'sha256':record['sha256'],'shot_ids':[shot],'media':media})
        clips.append({'id':clip,'job_id':sid,'path':copied})
        segments.append({'id':seg,'shot_id':shot,'clip_id':clip,'source_in':start,'source_out':end,'rate':rate,
            'source_audio':'retime' if media['has_audio'] else 'mute','filters':selected,'cut_reason':'Imported explicit legacy retained window: '+identity})
        shots.append({'id':shot,'scene_id':'local-edit','role':'source','information_goal':'Imported legacy edit input '+identity,
            'framing':'Existing source framing; actual content unverified','actions':[{'kind':'hold','description':'Retain existing footage without generation'}],
            'planned_seconds':media['duration'],'cut_motivation':'Preserve authored legacy cut','asset_ids':[],
            'audio':{'mode':'ambience' if media['has_audio'] else 'mute'}})
        rows.append({'legacy_input_id':identity,'source_path':item['path'],'local_source_id':sid,'segment_id':seg,
                     'copied_path':copied,'source_in':start,'source_out':end,'rate':rate})
    size=timeline.get('target_size','auto')
    if size=='auto':width,height=local_sources[0]['media']['width'],local_sources[0]['media']['height']
    elif isinstance(size,str) and re.fullmatch(r'\d+x\d+',size):width,height=map(int,size.split('x'))
    else:raise ConfigError('Legacy target_size must be auto or WIDTHxHEIGHT')
    bundle=create('edit-only',title=source.name+' · 迁移剪辑')
    bundle['director'].update(scenes=[{'id':'local-edit','map':'Imported source footage; geography unverified','axis':'Inspect original camera axes'}],shots=shots)
    bundle['generation-plan']['local_sources']=local_sources
    value=bundle['timeline'];value.update(format_version=4,fps='30/1',width=width,height=height,clips=clips,segments=segments,
                                         audio_tracks=[],subtitles=[],filters=[],mix_limiter=False)
    boundaries=timeline.get('transitions',[])
    if not isinstance(boundaries,list) or len(boundaries)!=len(inputs)-1:raise ConfigError('Legacy transitions need exactly one entry per boundary')
    converted=[]
    for index,entry in enumerate(boundaries):
        fields(entry,('after','type','duration','reason'),'transition')
        kind=entry.get('type');seconds=entry.get('duration',0)
        if entry.get('after')!=inputs[index]['id'] or kind not in {'cut','dissolve','fade-black','wipe-left','slide-left'} or not number(seconds):
            raise ConfigError('Legacy transition must match its original adjacent input and known type')
        if kind=='cut':
            if seconds!=0:raise ConfigError('Legacy cut duration must be zero')
            continue
        if not 0<seconds<=2:raise ConfigError('Legacy transition duration must be greater than zero and at most two seconds')
        converted.append({'id':f'legacy-transition-{index+1:03}','left_segment_id':segments[index]['id'],
            'right_segment_id':segments[index+1]['id'],'kind':'crossfade' if kind=='dissolve' else kind,
            'duration':seconds,'audio':'crossfade'})
    if converted:value['transitions']=converted
    filters=plan.get('filters',[])
    if not isinstance(filters,list):raise ConfigError('Legacy global filters must be a list')
    for entry in filters:
        fields(entry,('preset','scope'),'global filter')
        if entry.get('scope','all')!='all':raise ConfigError('Legacy global filter scope must be all')
        value['filters'].append(entry.get('preset'))
    presets(value['filters'],'global filters')
    duration=mapping(value)['duration']
    audio=plan.get('audio_mix',{});fields(audio,('preserve_source','music','voice','normalize_lufs'),'audio_mix')
    if audio.get('preserve_source',True) is not True:raise ConfigError('Legacy preserve_source=false is not consumed by its renderer; resolve the intended sound explicitly')
    music,voice=audio.get('music',''),audio.get('voice','')
    if not isinstance(music,str) or not isinstance(voice,str):raise ConfigError('Legacy music/voice paths must be strings')
    source_gain=20*math.log10(.35 if voice else .75) if music or voice else 0
    for segment in segments:segment['source_gain_db']=source_gain
    for name,relative in [('music',music),('voice',voice)]:
        if not relative:continue
        path,record=media_file(relative,'audio');copied='assets/legacy-audio/'+record['sha256']+path.suffix.lower()
        value['audio_tracks'].append({'id':'legacy-'+name,'kind':'music' if name=='music' else 'dialogue',
            'path':copied,'source_in':0,'source_out':duration if name=='music' else min(duration,record['duration']),
            'timeline_start':0,'gain_db':20*math.log10(.2) if name=='music' else 0,'loop':name=='music'})
        rows.append({'legacy_audio':name,'source_path':relative,'copied_path':copied})
    if audio.get('normalize_lufs') is not None:value['loudness']={'target_lufs':audio['normalize_lufs']}
    subtitle=plan.get('subtitles',{});fields(subtitle,('path','style','burn'),'subtitles')
    if (not isinstance(subtitle.get('burn',False),bool) or not isinstance(subtitle.get('style','clean'),str)
            or subtitle.get('style','clean') not in STYLES):raise ConfigError('Legacy subtitles need a burn boolean and supported style')
    relative=subtitle.get('path','')
    if not isinstance(relative,str):raise ConfigError('Legacy subtitle path must be a string')
    if relative:
        path,_=media_file(relative,'subtitle');value['subtitles']=srt(path)
        value['subtitle_render']={'burn':subtitle.get('burn',False),'style':subtitle.get('style','clean')}
    elif subtitle.get('burn'):raise ConfigError('Legacy burn=true requires a subtitle file')
    finishing=plan.get('finishing',{});fields(finishing,('fade_seconds',),'finishing')
    value['fade_seconds']=finishing.get('fade_seconds',0)
    mapped=mapping(value)
    report={'ok':True,'operation':'legacy-native-edit-to-v3','source':str(source),'destination':str(destination),
        'legacy_version':plan['version'],'source_files':files,'input_mapping':rows,'bundle':bundle,'duration':mapped['duration'],
        'notes':['Original plan/state/deliverables are retained at the source; tasks, ledger and approvals are not imported.',
            'Legacy native audio is retained/retimed, with original .35/.75 source and .20 music gains; music loops and voice ends/pads with the silent base.',
            'Two-pass loudness, literal Pillow captions, encoding and mix arithmetic differ from the old renderer; compare actual output before approving.',
            'Legacy preview/delivery/backend metadata are preserved in the plan snapshot but do not control v3 output; output uses deliverables/preview.mp4.',
            'Transition segments/durations must satisfy the v3 output-frame grid; adjust the source plan explicitly if rejected.'],
        'paid_creates':0,'content':'unverified'}
    report['preview_token']=content_hash(report)
    return report


def execute(source,destination,*,expected_token):
    report=preview(source,destination)
    if not expected_token or report['preview_token']!=expected_token:raise ConfigError('Migration inputs changed; preview again before copying')
    source,destination=Path(report['source']),Path(report['destination'])
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise ConfigError('FFmpeg is required to decode imported media')
    with tempfile.TemporaryDirectory(prefix='.videocreate-migration-',dir=destination.parent) as temporary:
        staged=Path(temporary)/'project';staged.mkdir()
        targets={row['source_path']:row['copied_path'] for row in report['input_mapping']}
        for relative,record in report['source_files'].items():
            target=staged/(targets.get(relative) or ('migration/source-files/'+record['sha256']+Path(relative).suffix.lower()))
            # Plans and captions remain provenance snapshots, not executable task state.
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(within(source,relative),target)
            if digest(target)!=record['sha256']:raise ConfigError('A source changed while copying; destination was not published')
            if record['kind'] in {'audio','video'}:
                result=subprocess.run([ffmpeg,'-nostdin','-v','error','-xerror','-i',str(target),'-f','null','-'],capture_output=True)
                if result.returncode:raise ConfigError('An imported media file did not fully decode; destination was not published')
        # Recheck every source and all plan semantics after the potentially long copy/decode.
        if preview(source,destination)['preview_token']!=expected_token:raise ConfigError('Source changed during migration; destination was not published')
        bundle=copy.deepcopy(report['bundle']);checked=validate_plan(bundle,staged)
        if not checked['ok']:raise ConfigError('; '.join(checked['errors']))
        manifest={k:v for k,v in report.items() if k!='bundle'}
        manifest.update(status='imported_unreviewed',full_decode_verified=True,source_unchanged=True,
            generation_jobs_imported=0,ledger_entries_imported=0,review_approvals_imported=0)
        atomic_json(staged/'migration/legacy-edit.manifest.json',manifest)
        save_bundle(staged,bundle)
        # Windows rename refuses an already-created destination. Never merge into a project.
        if destination.exists():raise ConfigError('Destination appeared during migration; choose a new directory')
        staged.rename(destination)
    return {'ok':True,'project':str(destination),'manifest':str(destination/'migration/legacy-edit.manifest.json'),
        'status':'review_pending','source_unchanged':True,'full_decode_verified':True,'paid_creates':0}
