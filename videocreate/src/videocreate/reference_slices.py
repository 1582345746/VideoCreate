"""Decoded temporal references with hash-bound, locally verifiable provenance."""
from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config.storage import ConfigError, atomic_json, load_json
from .media_references import digest, inspect, register
from .planning.project import within
from .runtime.state import state_lock

REFERENCE_FIELDS = ('kind', 'path', 'sha256', 'role', 'derivation')
MAX_DEPTH = 8


def _interval(start, end, duration):
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)
           for v in (start, end)) or not 0 <= start < end <= duration:
        raise ConfigError('Reference slice requires finite seconds: 0 <= start < end <= source duration')


def validate_derivation(root, reference, media, *, seen=None):
    """Validate every source in a bounded chain; this is provenance, not approval."""
    pointer = reference.get('derivation')
    if pointer is None:
        return
    if (not isinstance(pointer, dict) or set(pointer) != {'path', 'sha256'}
            or not isinstance(pointer['path'], str) or not isinstance(pointer['sha256'], str)):
        raise ConfigError('Reference derivation requires a manifest path and SHA-256')
    seen = set() if seen is None else set(seen)
    path = within(Path(root), pointer['path'])
    if path in seen or len(seen) >= MAX_DEPTH:
        raise ConfigError('Reference derivation is cyclic or exceeds eight levels')
    seen.add(path)
    if path.stat().st_size > 128 * 1024 or digest(path) != pointer['sha256']:
        raise ConfigError('Reference derivation manifest hash changed or exceeds size limit')
    record = load_json(path)
    if (set(record) != {'schema_version', 'operation', 'source', 'source_metadata', 'interval', 'output', 'method'}
            or record['schema_version'] != 1 or record['operation'] != 'temporal-slice'
            or not isinstance(record['source'], dict) or not isinstance(record['interval'], dict)
            or set(record['interval']) != {'start_seconds', 'end_seconds'}
            or not isinstance(record['method'], dict)
            or record['method'].get('name') != 'ffmpeg-decoded-trim-v1'
            or not isinstance(record['method'].get('version'), str)):
        raise ConfigError('Unsupported reference derivation manifest')
    source = record['source']
    if (not {'kind', 'path', 'sha256', 'role'} <= set(source) <= set(REFERENCE_FIELDS)
            or any(not isinstance(source[key], str) for key in ('kind', 'path', 'sha256', 'role'))
            or source['kind'] not in {'video', 'audio'} or source['kind'] != media['kind']):
        raise ConfigError('Reference slice must preserve its temporal media kind')
    from .catalog.media_constraints import ROLES
    if source['role'] not in ROLES[source['kind']]:
        raise ConfigError('Reference derivation has an invalid source role')
    actual = inspect(within(Path(root), source['path']), source['kind'])
    if actual['sha256'] != source['sha256'] or actual != record['source_metadata']:
        raise ConfigError('Reference derivation source hash or metadata changed')
    validate_derivation(root, source, actual, seen=seen)
    _interval(record['interval']['start_seconds'], record['interval']['end_seconds'], actual['duration_seconds'])
    if record['output'] != media:
        raise ConfigError('Reference derivation output does not match the actual reference bytes')


def slice_reference(root, reference, *, start, end):
    """Create real cropped bytes. Never modify a plan, publish, or call a provider."""
    root = Path(root).resolve()
    if reference.get('kind') not in {'video', 'audio'}:
        raise ConfigError('Only explicitly typed video or audio references can be sliced')
    from .media_references import prepare_references
    source = {key: reference[key] for key in REFERENCE_FIELDS if key in reference}
    media = prepare_references(root, [source])[0]
    source_metadata = inspect(within(root, source['path']), source['kind'])
    _interval(start, end, media['duration_seconds'])
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ConfigError('FFmpeg is required to slice reference media')
    version = subprocess.run([ffmpeg, '-version'], capture_output=True, timeout=15, check=True).stdout.decode(
        'utf-8', errors='replace').splitlines()[0]
    folder = root / 'assets' / 'media-references'
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='slice-', dir=folder) as temporary:
        temp = Path(temporary)
        # Trim a verified copy so concurrent source edits cannot alter the output.
        snapshot = temp / ('input' + media['suffix'])
        shutil.copyfile(within(root, source['path']), snapshot)
        if digest(snapshot) != source['sha256']:
            raise ConfigError('Reference source changed before slicing')
        video = source['kind'] == 'video'
        output = temp / ('slice.mp4' if video else 'slice.wav')
        args = [ffmpeg, '-v', 'error', '-nostdin', '-i', str(snapshot), '-ss', format(float(start), '.17g'),
                '-t', format(float(end - start), '.17g'), '-map_metadata', '-1', '-map_chapters', '-1']
        if video:
            args += ['-map', '0:v:0', '-map', '0:a:0?', '-c:v', 'libx264', '-preset', 'medium',
                     '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart']
        else:
            args += ['-map', '0:a:0', '-vn', '-c:a', 'pcm_s16le']
        try:
            result = subprocess.run([*args, str(output)], capture_output=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired):
            raise ConfigError('Local reference slicing could not finish; no provider request was made') from None
        if result.returncode:
            raise ConfigError('FFmpeg could not decode the requested reference interval')
        derived = register(root, output, kind=source['kind'], role=source['role'])
        actual_output = inspect(within(root, derived['path']), derived['kind'])
        # Audio is sample-quantized; video is frame-quantized. Record actual output
        # duration independently from the requested half-open source interval.
        record = {'schema_version': 1, 'operation': 'temporal-slice', 'source': source,
            'source_metadata': source_metadata,
            'interval': {'start_seconds': float(start), 'end_seconds': float(end)},
            'output': actual_output,
            'method': {'name': 'ffmpeg-decoded-trim-v1', 'version': version}}
        manifest = temp / 'derivation.json'
        atomic_json(manifest, record)
        manifest_hash = digest(manifest)
        target = folder / (manifest_hash + '.derivation.json')
        with state_lock(root):
            if target.exists() and digest(target) != manifest_hash:
                raise ConfigError('Existing reference derivation was modified; preserve and repair it explicitly')
            if not target.exists():
                manifest.replace(target)
        derived['derivation'] = {'path': target.relative_to(root).as_posix(), 'sha256': manifest_hash}
        validate_derivation(root, derived, actual_output)
        reference_file = folder / (derived['sha256'] + '-' + manifest_hash + '-' + derived['role'] + '.reference.json')
        with state_lock(root):
            if reference_file.exists() and load_json(reference_file) != derived:
                raise ConfigError('Existing derived reference record was modified')
            if not reference_file.exists():
                atomic_json(reference_file, derived)
    return {'ok': True, 'reference': derived, 'reference_file': str(reference_file),
        'requested_interval': record['interval'], 'actual_duration_seconds': actual_output['duration_seconds'],
        'quantization': 'decoded frames' if video else 'decoded PCM samples',
        'plan_modified': False, 'paid_creates': 0}
