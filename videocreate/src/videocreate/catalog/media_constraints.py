"""Explicit executable bounds for typed reference requests, independent of notes."""
import math

ROLES = {'image': {'opening-frame', 'identity', 'prop', 'scene', 'style'},
         'video': {'motion', 'scene', 'style'}, 'audio': {'sound'}}


def limits_errors(limits):
    errors = []
    for kind in ROLES:
        entry = limits[kind]
        if set(entry['roles']) - ROLES[kind]:
            errors.append(kind + ': role is not implemented by the URL-array contract')
        if entry['maximum_count']:
            if not entry['roles'] or not entry['mime_types']:
                errors.append(kind + ': active references require roles and MIME types')
            if any(not mime.startswith(kind + '/') for mime in entry['mime_types']):
                errors.append(kind + ': MIME type does not match kind')
            if kind != 'image' and not all(k in entry for k in ('maximum_duration_seconds', 'maximum_total_duration_seconds')):
                errors.append(kind + ': active temporal references require explicit duration limits')
        if entry['maximum_bytes'] > entry['maximum_total_bytes']:
            errors.append(kind + ': single file limit exceeds total byte limit')
    return errors


def count_errors(binding, operation, counts, *, generate_audio=False):
    """Shared count/combination bounds for catalog queries and actual references."""
    errors = []
    if binding.adapter not in {'xingapi-video-v2', 'newapi-json-v2'}:
        return ['This adapter does not transmit typed image/video/audio references']
    limits = binding.capabilities.get('media_reference_limits')
    if not limits:
        return ['Typed media reference limits are unknown; configure the selected binding first']
    active = {k for k, count in counts.items() if count}
    if active not in [set(combo) for combo in limits['allowed_combinations']]:
        errors.append('This media reference combination is not enabled on the binding')
    if sum(counts.values()) > limits['maximum_total_count']:
        errors.append('Too many combined media references')
    for kind,count in counts.items():
        if count > limits[kind]['maximum_count']:
            errors.append(kind + ': reference count exceeds binding limit')
    if counts.get('audio') and generate_audio and not limits['audio_reference_with_generated_audio']:
        errors.append('Audio reference with generated audio is not enabled for this binding')
    return errors


def request_errors(binding, request):
    references = request.get('media_references', [])
    if not references:return ['Reference-to-video needs actual typed media references']
    groups = {k: [] for k in ROLES}
    errors = []
    for ref in references:
        if ref.get('kind') not in groups:
            errors.append('Reference has an unknown media kind')
        else:
            groups[ref['kind']].append(ref)
    errors.extend(count_errors(binding,request['operation'],{k:len(v) for k,v in groups.items()},
        generate_audio=request.get('generate_audio',False)))
    limits=binding.capabilities.get('media_reference_limits')
    if binding.adapter not in {'xingapi-video-v2', 'newapi-json-v2'} or not limits:return errors
    total_bytes = 0
    for kind, items in groups.items():
        bound = limits[kind]
        sizes, durations = [], []
        for ref in items:
            if ref.get('role') not in bound['roles'] or ref.get('role') not in ROLES[kind]:
                errors.append(kind + ': unsupported reference role')
            if ref.get('mime_type') not in bound['mime_types']:
                errors.append(kind + ': unsupported reference MIME type')
            size = ref.get('bytes')
            if type(size) is not int or not 0 < size <= bound['maximum_bytes']:
                errors.append(kind + ': missing or oversized reference bytes')
            else:
                sizes.append(size)
            for field in ('width', 'height', 'sample_rate', 'channels'):
                maximum = bound.get('maximum_' + field)
                value = ref.get(field)
                if maximum is not None and (not isinstance(value, (float, int)) or isinstance(value, bool) or not 0 < value <= maximum):
                    errors.append(kind + ': missing or excessive ' + field)
            if kind != 'image':
                duration = ref.get('duration_seconds')
                if (not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration)
                        or not 0 < duration <= bound.get('maximum_duration_seconds', 0)):
                    errors.append(kind + ': missing or excessive reference duration')
                else:
                    durations.append(duration)
        if sum(sizes) > bound['maximum_total_bytes']:
            errors.append(kind + ': combined bytes exceed binding limit')
        if kind != 'image' and sum(durations) > bound.get('maximum_total_duration_seconds', 0):
            errors.append(kind + ': combined duration exceeds binding limit')
        total_bytes += sum(sizes)
    if total_bytes > limits['maximum_total_bytes']:
        errors.append('Combined reference bytes exceed binding limit')
    if request['operation'] == 'image-to-video':
        primary = [r for r in references if r.get('kind') == 'image' and r.get('role') == 'opening-frame']
        if len(primary) != 1:
            errors.append('Image-to-video requires exactly one opening-frame image')
        elif groups['image'][0].get('role') != 'opening-frame':
            errors.append('The opening frame must be the first image; reorder the plan explicitly')
    return errors
