"""Offline task-oriented catalog queries; counts never stand in for real media."""
import copy
import math

from .bindings import configured_binding, validate_parameters
from .media_constraints import count_errors
from .presentation import OPERATIONS, rows, estimate_text
from ..config.storage import ConfigError
from ..runtime.budget import estimate_details, image_parameters


def scenario(value):
    if not isinstance(value,dict) or set(value)-{'operation','seconds','resolution','aspect_ratio','reference_counts','generate_audio'}:
        raise ConfigError('Task filter requires an object with operation, seconds, resolution, aspect_ratio, reference_counts or generate_audio')
    if not isinstance(value.get('operation'),str) or value['operation'] not in OPERATIONS:
        raise ConfigError('Choose a supported task operation')
    result=copy.deepcopy(value)
    for key in ('resolution','aspect_ratio'):
        if key in value and (not isinstance(value[key],str) or not value[key].strip()):
            raise ConfigError('Task filter '+key+' must be a nonempty string')
    if 'seconds' in value:
        n=value['seconds']
        if type(n) not in {int,float} or not math.isfinite(n) or n<=0:
            raise ConfigError('Task filter seconds must be finite and positive')
    if 'generate_audio' in value and type(value['generate_audio']) is not bool:
        raise ConfigError('Task filter generate_audio must be boolean')
    if 'reference_counts' in value:
        counts=value['reference_counts']
        if (not isinstance(counts,dict) or set(counts)-{'image','video','audio'}
                or any(type(n) is not int or n<0 for n in counts.values())):
            raise ConfigError('Reference counts require nonnegative image/video/audio integers')
        result['reference_counts']={k:counts.get(k,0) for k in ('image','video','audio')}
    if value['operation'] in {'text-to-image','image-edit'}:
        if set(value)&{'seconds','resolution','aspect_ratio','generate_audio'}:
            raise ConfigError('Video duration, resolution, aspect ratio and audio filters do not apply to image tasks')
        if any(result.get('reference_counts',{}).get(k,0) for k in ('video','audio')):
            raise ConfigError('Image tasks accept image references only')
    return result


def assess(config,row,request):
    item=config['bindings'][row['id']]
    reasons=[];unknown=[];warnings=[]
    if not row['enabled'] or row['archived']:reasons.append('Binding is disabled or archived')
    if row['setup_status']=='draft' or row['adapter']=='unconfigured':unknown.append('Protocol is not configured')
    if row['id'] not in config['routes'].get(row['model'],{}).get('candidates',[]):
        reasons.append('Binding is not registered in the model route')
    operation=request['operation'];kind='image' if operation in {'text-to-image','image-edit'} else 'video'
    if row['kind']!=kind:reasons.append('Operation has a different media kind')
    binding=None
    if not unknown and row['kind']==kind:
        binding=configured_binding(config,row['id']);caps=binding.capabilities
        scalar={k:v for k,v in request.items() if k!='reference_counts'}
        if 'generate_audio' in scalar and caps.get('audio_control')=='unknown':
            unknown.append('Audio control capability is unknown');scalar.pop('generate_audio')
        checked=validate_parameters(binding,scalar);reasons.extend(checked['errors']);warnings.extend(checked['warnings'])
        counts=request.get('reference_counts')
        if counts is not None:
            total=sum(counts.values());images=counts['image']
            if operation in {'text-to-video','text-to-image'} and total:
                reasons.append('Text-only operation must omit reference media')
            elif operation in {'image-to-video','image-edit'} and not images:
                reasons.append('This operation needs at least one reference image')
            elif operation=='reference-to-video' and not total:
                reasons.append('Reference-to-video needs reference media')
            elif total:
                typed=kind=='video' and (binding.adapter in {'xingapi-video-v2', 'newapi-json-v2'} or operation=='reference-to-video'
                    or counts['video'] or counts['audio'])
                if typed:
                    if binding.adapter in {'xingapi-video-v2', 'newapi-json-v2'} and not caps.get('media_reference_limits'):
                        unknown.append('Typed media reference limits are unknown')
                    else:reasons.extend(count_errors(binding,operation,counts,generate_audio=request.get('generate_audio',False)))
                    if operation=='image-to-video' and caps.get('media_reference_limits'):
                        if 'opening-frame' not in caps['media_reference_limits']['image']['roles']:
                            reasons.append('Opening-frame image role is not enabled')
                else:
                    if images>caps.get('max_reference_images',0):reasons.append('Too many reference images for this binding')
                    if kind=='video' and max(0,images-1)>caps.get('max_additional_reference_images',0):
                        reasons.append('Too many additional reference images for this binding')
        if operation=='reference-to-video' and counts is None:
            unknown.append('Reference types and counts have not been specified')
    currency=(item.get('pricing') or {}).get('currency')
    details={'amount':None,'reason':'protocol_unconfigured' if not binding else 'duration_missing'}
    if binding and (kind=='image' or 'seconds' in request):
        parameters=image_parameters(binding,operation) if kind=='image' else request
        details=estimate_details(binding,request.get('seconds',0),currency,parameters=parameters)
    status='excluded' if reasons else 'unverified' if unknown else 'parameters-match'
    return {'status':status,'matches':status=='parameters-match','reasons':list(dict.fromkeys(reasons)),
        'unknowns':list(dict.fromkeys(unknown)),'warnings':list(dict.fromkeys(warnings)),
        'quote':{'currency':currency,'amount':details['amount'],'actual_payment':'unknown',
                 'calculation':details,'explanation':estimate_text(details)},
        'ready_to_create':False}


def query(config,value,**filters):
    request=scenario(value)
    visible=rows(config,**filters)
    assessed=[{**row,'task_fit':assess(config,row,request)} for row in visible]
    counts={status:sum(row['task_fit']['status']==status for row in assessed)
        for status in ('parameters-match','excluded','unverified')}
    return {'ok':True,'scenario':request,'bindings':assessed,'counts':counts,
        'scope':'Configured parameters and reference counts only',
        'unchecked':['actual prompt','reference roles, order, hashes, sizes, durations and URLs',
            'credentials and upstream availability','complete request and budget','content quality and actual payment'],
        'paid_creates':0,'network_requests':0,'selection_changed':False}
