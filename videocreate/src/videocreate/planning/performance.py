"""Versioned separation of audible output from visible mouth performance."""


def validation_errors(bundle):
    errors = []
    version = bundle['project'].get('prompt_semantics', 1)
    for shot in bundle['director']['shots']:
        mouth = shot.get('mouth_performance')
        audio = shot.get('audio', {})
        if version == 1 and (mouth is not None or 'music' in audio):
            errors.append(shot['id'] + ': mouth/music controls require project.prompt_semantics=2; preserve existing task snapshots')
            continue
        if mouth is None:
            continue
        mode = mouth['mode']
        visible_lines = [line for line in audio.get('lines', []) if line['on_screen']]
        if mode == 'closed' and visible_lines:
            errors.append(shot['id'] + ': closed mouth conflicts with on-screen dialogue')
        if mode == 'speech' and not visible_lines:
            errors.append(shot['id'] + ': speech mouth performance requires timed on-screen lines; use silent-performance for untranscribed reference acting')
        if mode == 'silent-performance' and visible_lines and audio.get('mode') == 'native-dialogue':
            errors.append(shot['id'] + ': silent mouth performance conflicts with native on-screen dialogue')
    return errors


def directions(bundle, shot):
    """Historical projects keep byte-identical directives until explicitly edited."""
    audio = shot.get('audio', {'mode': 'ambience'})
    if bundle['project'].get('prompt_semantics', 1) == 1:
        if not audio.get('lines') or audio.get('mode') in {'mute', 'ambience'}:
            return ['No speech; visible mouths stay closed. ' + str(audio.get('ambience', ''))]
        return []
    result = []
    audible = audio.get('mode')
    if audible == 'mute':
        result.append('No audible soundtrack; silence does not restrict facial expression.')
    elif audible == 'ambience':
        result.append('Location ambience only; no audible dialogue. ' + str(audio.get('ambience', '')))
    if audio.get('music') == 'none' or audible == 'mute':
        result.append('No background music.')
    mouth = shot.get('mouth_performance', {})
    default = 'speech' if any(line['on_screen'] for line in audio.get('lines', [])) else 'natural'
    result.append({
        'natural': 'Natural facial expression; do not force the mouth shut.',
        'closed': 'Keep visible mouths closed as explicitly directed.',
        'silent-performance': 'Preserve visible speaking/singing mouth gestures silently; exact lip-sync is unverified.',
        'speech': 'Visible speakers articulate their timed lines; listening characters do not speak.',
    }[mouth.get('mode', default)])
    if mouth.get('direction'):
        result.append('Mouth performance: ' + mouth['direction'])
    return result
