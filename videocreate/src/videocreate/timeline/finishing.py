"""Versioned, bounded finishing controls; authored text never becomes FFmpeg code."""
import json
import math
import subprocess

from ..config.storage import ConfigError

FILTERS = {
    'cinematic': 'eq=contrast=1.06:saturation=0.92:gamma=0.98,vignette=PI/5',
    'warm': 'colorbalance=rs=.05:gs=.01:bs=-.04',
    'cool': 'colorbalance=rs=-.04:gs=.01:bs=.05',
    'vivid': 'eq=contrast=1.05:saturation=1.18',
    'monochrome': 'hue=s=0',
    'denoise': 'hqdn3d=1.5:1.5:6:6',
    'sharpen': 'unsharp=5:5:0.65:5:5:0',
}
STYLES = ('clean', 'cinematic', 'news')
KEYS = ('filters', 'loudness', 'subtitle_render', 'fade_seconds', 'mix_limiter')


def required_version(timeline):
    segments, tracks, boundaries = (timeline.get(k, []) for k in ('segments', 'audio_tracks', 'transitions'))
    if (any(k in timeline for k in ('fade_seconds', 'mix_limiter'))
            or any(isinstance(s, dict) and 'source_gain_db' in s for s in (segments if isinstance(segments, list) else []))
            or any(isinstance(t, dict) and 'loop' in t for t in (tracks if isinstance(tracks, list) else []))
            or any(isinstance(t, dict) and t.get('kind') == 'slide-left' for t in (boundaries if isinstance(boundaries, list) else []))):
        return 4
    return 3 if present(timeline) else 1


def present(timeline):
    segments = timeline.get('segments', [])
    return any(key in timeline for key in KEYS) or any(
        isinstance(segment, dict) and 'filters' in segment for segment in (segments if isinstance(segments, list) else []))


def validate(timeline):
    from .model import number
    errors = []
    version, actual = required_version(timeline), timeline.get('format_version', 1)
    if not isinstance(actual, int) or isinstance(actual, bool) or actual < version:
        errors.append(f'timeline finishing: format_version={version} or newer is required')
    segments = timeline.get('segments', [])
    groups = [('timeline', timeline)] + [(str(s.get('id', 'segment')), s)
        for s in (segments if isinstance(segments, list) else []) if isinstance(s, dict)]
    for label, item in groups:
        if 'source_gain_db' in item and (not number(item['source_gain_db']) or abs(item['source_gain_db']) > 60):
            errors.append(label + '.source_gain_db: use a finite gain from -60 to 60 dB')
        presets = item.get('filters', [])
        if (not isinstance(presets, list) or len(presets) > len(FILTERS)
                or any(not isinstance(p, str) or p not in FILTERS for p in presets)):
            errors.append(label + '.filters: use an ordered list of supported presets')
        elif len(set(presets)) != len(presets):
            errors.append(label + '.filters: duplicate presets are not supported')
    if 'loudness' in timeline:
        value = timeline['loudness']
        if (not isinstance(value, dict) or set(value) != {'target_lufs'}
                or not number(value.get('target_lufs')) or not -24 <= value['target_lufs'] <= -10):
            errors.append('timeline.loudness: only target_lufs from -24 to -10 is supported')
    if 'subtitle_render' in timeline:
        value = timeline['subtitle_render']
        if (not isinstance(value, dict) or set(value) != {'burn', 'style'}
                or not isinstance(value.get('burn'), bool)
                or not isinstance(value.get('style'), str) or value['style'] not in STYLES):
            errors.append('timeline.subtitle_render: burn boolean and clean/cinematic/news style required')
    if 'fade_seconds' in timeline and (not number(timeline['fade_seconds']) or timeline['fade_seconds'] < 0):
        errors.append('timeline.fade_seconds: use a finite nonnegative duration')
    if 'mix_limiter' in timeline and not isinstance(timeline['mix_limiter'], bool):
        errors.append('timeline.mix_limiter: use a boolean')
    tracks = timeline.get('audio_tracks', [])
    for track in tracks if isinstance(tracks, list) else []:
        if isinstance(track, dict) and 'loop' in track and not isinstance(track['loop'], bool):
            errors.append('timeline.audio_tracks.loop: use a boolean')
    return errors


def fade(ffmpeg, source, output, seconds, duration, run):
    run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(source), '-map', '0:v:0', '-map', '0:a?',
         '-vf', f'fade=t=in:st=0:d={seconds},fade=t=out:st={duration-seconds}:d={seconds}',
         '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-c:a', 'copy',
         '-t', str(duration), '-movflags', '+faststart', str(output)])


def filter_chain(timeline, segment):
    return ','.join(FILTERS[name] for name in timeline.get('filters', []) + segment.get('filters', []))


def captions(timeline, cues):
    """Cues must already be mapped from source time into final output time."""
    settings = timeline.get('subtitle_render', {})
    if not settings.get('burn'):
        return []
    ordered = sorted(cues, key=lambda c: (c['start'], c['end']))
    for index, cue in enumerate(ordered):
        if not cue['text'].strip() or '\x00' in cue['text']:
            raise ConfigError('Burned subtitles need nonempty text without NUL characters')
        if index and cue['start'] < ordered[index - 1]['end'] - 1e-9:
            raise ConfigError('Burned subtitles overlap; merge or retime the mapped cues explicitly')
    return [{'id': 'caption-' + str(i), 'text': cue['text'], 'start': cue['start'], 'end': cue['end'],
             'position': 'bottom', 'caption_style': settings['style']} for i, cue in enumerate(ordered)]


def measure(ffmpeg, path, target, *, duration=None):
    trim = f'atrim=duration={duration},asetpts=PTS-STARTPTS,' if duration is not None else ''
    command = [ffmpeg, '-nostdin', '-v', 'info', '-i', str(path), '-map', '0:a:0', '-vn',
               '-af', trim + f'loudnorm=I={target}:LRA=11:TP=-1.5:print_format=json', '-f', 'null', '-']
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise ConfigError('Loudness measurement failed: ' + result.stderr.decode('utf-8', errors='replace')[-1200:])
    log = result.stderr.decode('utf-8', errors='replace')
    try:
        raw = json.loads(log[log.rfind('{'):log.rfind('}') + 1])
        values = {key: float(raw[key]) for key in ('input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset')}
    except (ValueError, KeyError, TypeError):
        raise ConfigError('FFmpeg did not return valid loudness measurements') from None
    if values['input_i'] == -math.inf and values['input_tp'] == -math.inf:
        return {'silent': True, 'integrated_lufs': None, 'true_peak_dbtp': None}
    if not all(math.isfinite(v) for v in values.values()):
        raise ConfigError('Audio is too short or ungated for finite loudness measurement; leave normalization unset')
    return {'silent': False, 'integrated_lufs': values['input_i'], 'true_peak_dbtp': values['input_tp'],
            'loudness_range_lu': values['input_lra'], 'threshold_lufs': values['input_thresh'],
            'target_offset_db': values['target_offset']}


def normalize(ffmpeg, source, output, target, duration, run):
    before = measure(ffmpeg, source, target, duration=duration)
    report = {'requested_lufs': target, 'true_peak_limit_dbtp': -1.5, 'lra_target_lu': 11, 'before': before}
    if before['silent']:
        return source, {**report, 'status': 'skipped_silence', 'after': before}
    expression = (f"atrim=duration={duration},asetpts=PTS-STARTPTS,"
        f"loudnorm=I={target}:LRA=11:TP=-1.5:measured_I={before['integrated_lufs']}:"
        f"measured_TP={before['true_peak_dbtp']}:measured_LRA={before['loudness_range_lu']}:"
        f"measured_thresh={before['threshold_lufs']}:offset={before['target_offset_db']}:linear=true,"
        f"aresample=48000,apad=whole_dur={duration},atrim=duration={duration}")
    run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(source), '-map', '0:v:0', '-map', '0:a:0',
         '-c:v', 'copy', '-af', expression, '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
         '-t', str(duration), '-movflags', '+faststart', str(output)])
    after = measure(ffmpeg, output, target)  # Measure actual encoded bytes, not the filter's predicted result.
    return output, {**report, 'status': 'processed', 'after': after,
                    'within_1_lu': not after['silent'] and abs(after['integrated_lufs'] - target) <= 1,
                    'content': 'unverified'}
