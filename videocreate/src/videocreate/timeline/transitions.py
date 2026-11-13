"""Explicit adjacent-segment transitions and local picture/source-audio assembly."""
import re

KINDS = {'crossfade': 'fade', 'fade-black': 'fadeblack', 'wipe-left': 'wipeleft', 'slide-left': 'slideleft'}
FIELDS = {'id', 'left_segment_id', 'right_segment_id', 'kind', 'duration', 'audio'}


def layout(timeline, durations):
    from .model import number, rational
    errors, boundaries = [], {}
    version = timeline.get('format_version', 1)
    if isinstance(version, bool) or not isinstance(version, int) or version not in {1, 2, 3, 4}:
        errors.append('timeline.format_version: unsupported edit format; use 1, 2, 3 or 4')
    records = timeline.get('transitions', [])
    if not isinstance(records, list):
        return errors + ['timeline.transitions: expected an array'], boundaries
    if not records:
        return errors, boundaries
    if version not in {2, 3, 4}:
        errors.append('timeline.transitions: format_version=2, 3 or 4 is required')
    ids = [s.get('id') if isinstance(s, dict) and isinstance(s.get('id'), str) else None
           for s in timeline['segments']]
    adjacent = set(zip(ids, ids[1:]))
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            errors.append('timeline.transitions: each transition must be an object'); continue
        identity = record.get('id')
        if (not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', identity)
                or identity in seen):
            errors.append('timeline.transitions: unique ASCII id required'); continue
        seen.add(identity)
        if set(record) != FIELDS:
            errors.append(identity + ': transition fields must be id/left_segment_id/right_segment_id/kind/duration/audio')
        left, right = record.get('left_segment_id'), record.get('right_segment_id')
        if not isinstance(left, str) or not isinstance(right, str) or (left, right) not in adjacent:
            errors.append(identity + ': transition must connect adjacent segments in their current order'); continue
        if right in boundaries:
            errors.append(identity + ': duplicate transition on the same boundary'); continue
        if (not isinstance(record.get('kind'), str) or record['kind'] not in KINDS
                or not isinstance(record.get('audio'), str) or record['audio'] not in {'crossfade', 'cut'}):
            errors.append(identity + ': unsupported picture or source-audio transition')
        duration = record.get('duration')
        if not number(duration) or duration <= 0:
            errors.append(identity + ': transition duration must be positive and finite'); continue
        if left not in durations or right not in durations:
            continue  # The segment validator reports its invalid source window.
        if duration >= min(durations[left], durations[right]) - 1e-9:
            errors.append(identity + ': overlap must be shorter than both adjacent segments')
        boundaries[right] = record
    try:
        fps = float(rational(timeline.get('fps')))
    except (ValueError, TypeError, ZeroDivisionError):
        return errors, boundaries
    for identity, duration in durations.items():
        if abs(duration * fps - round(duration * fps)) > 1e-6:
            errors.append(identity + ': transition timelines require segment playback durations on the output frame grid')
    for record in boundaries.values():
        frames = record['duration'] * fps
        if round(frames) < 1 or abs(frames - round(frames)) > 1e-6:
            errors.append(record['id'] + ': overlap must contain a whole positive number of output frames')
    for index, identity in enumerate(ids):
        incoming = boundaries.get(identity, {}).get('duration', 0)
        outgoing = boundaries.get(ids[index + 1], {}).get('duration', 0) if index + 1 < len(ids) else 0
        if incoming + outgoing > durations.get(identity, float('inf')) + 1e-9:
            errors.append(str(identity) + ': incoming and outgoing overlaps would create a three-way transition')
    return errors, boundaries


def assemble(ffmpeg, parts, plan, folder, output, run):
    """Parts already have matching canvas/fps/stereo audio and zero timestamps."""
    arguments = [ffmpeg, '-nostdin', '-v', 'error', '-y', '-filter_complex_threads', '1']
    graph = []
    for index, part in enumerate(parts):
        arguments += ['-i', str(part)]
        duration=plan['segments'][index]['duration']
        graph += [f'[{index}:v]setpts=PTS-STARTPTS,fps={plan["fps"]},settb=AVTB[v{index}]',
                  f'[{index}:a]aresample=48000,asetpts=PTS-STARTPTS,apad=whole_dur={duration},atrim=duration={duration}[a{index}]']
    transitions = {r['right_segment_id']: r for r in plan['transitions']}
    picture, sound = 'v0', 'a0'
    for index, segment in enumerate(plan['segments'][1:], 1):
        video_out, audio_out = f'picture{index}', f'sound{index}'
        transition = transitions.get(segment['id'])
        if transition:
            duration = transition['duration']
            graph.append(f'[{picture}][v{index}]xfade=transition={KINDS[transition["kind"]]}:'
                         f'duration={duration}:offset={transition["timeline_start"]}[{video_out}]')
            if transition['audio'] == 'crossfade':
                graph.append(f'[{sound}][a{index}]acrossfade=d={duration}:c1=tri:c2=tri[{audio_out}]')
            else:
                # A hard source-audio cut at the overlap midpoint, with no time
                # stretch or overlapping dialogue. Independent tracks stay fixed.
                midpoint = transition['timeline_start'] + duration / 2
                graph += [f'[{sound}]atrim=end={midpoint},asetpts=PTS-STARTPTS[left{index}]',
                          f'[a{index}]atrim=start={duration/2},asetpts=PTS-STARTPTS[right{index}]',
                          f'[left{index}][right{index}]concat=n=2:v=0:a=1[{audio_out}]']
        else:
            graph += [f'[{picture}][v{index}]concat=n=2:v=1:a=0[{video_out}]',
                      f'[{sound}][a{index}]concat=n=2:v=0:a=1[{audio_out}]']
        graph.append(f'[{video_out}]fps={plan["fps"]},settb=AVTB[normalized{index}]')
        picture, sound = f'normalized{index}', audio_out
    script = folder / 'transitions.ffgraph'
    script.write_text(';\n'.join(graph), encoding='utf-8')
    arguments += ['-filter_complex_script', str(script), '-map', f'[{picture}]', '-map', f'[{sound}]',
                  '-r', plan['fps'], '-t', str(plan['duration']), '-c:v', 'libx264', '-preset', 'veryfast',
                  '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2', str(output)]
    run(arguments)
