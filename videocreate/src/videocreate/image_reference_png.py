"""A project-local PNG copy for bindings that accept PNG but not WebP."""
import tempfile
from pathlib import Path

from .asset_library import _copy_verified, digest, project_media_revision
from .config.storage import ConfigError, atomic_json
from .media_references import inspect
from .planning.project import within
from .still_images import pillow_modules


def _pixels(path):
    Image, ImageOps = pillow_modules()
    with Image.open(path) as image:
        if getattr(image, 'n_frames', 1) != 1:
            raise ConfigError('PNG reference conversion requires a single still image')
        return ImageOps.exif_transpose(image).convert('RGBA'), image.info.get('icc_profile')


def validate_png(root, record, reference, output):
    if (set(record) != {'schema_version', 'operation', 'source', 'output'}
            or record['schema_version'] != 1 or output['mime_type'] != 'image/png'
            or record['output'] != output or not isinstance(record['source'], dict)):
        raise ConfigError('Invalid PNG derivation')
    source = record['source']
    if (set(source) != {'path', 'kind', 'sha256', 'role'} or source['kind'] != 'image'
            or source['role'] != reference['role'] or not isinstance(source['path'], str)):
        raise ConfigError('PNG conversion must preserve the source image and its role')
    original = within(root, source['path'])
    if digest(original) != source['sha256']:
        raise ConfigError('Original image changed after PNG conversion')
    project_media_revision(root, source['path'], source['sha256'])
    expected, original_profile = _pixels(original)
    actual, profile = _pixels(within(root, reference['path']))
    if expected.size != actual.size or expected.tobytes() != actual.tobytes() or original_profile != profile:
        raise ConfigError('PNG dimensions, pixels or color profile differ from the original')


def convert_under_lock(root, reference):
    """Caller holds the project lock while installing the immutable files."""
    if reference['kind'] != 'image' or 'derivation' in reference:
        raise ConfigError('PNG conversion requires the original visual asset')
    source = within(root, reference['path'])
    if digest(source) != reference['sha256']:
        raise ConfigError('Original image changed before conversion')
    folder = within(root, 'assets/media-references', exists=False)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        output = Path(temp) / 'output.png'
        pixels, profile = _pixels(source)
        pixels.save(output, format='PNG', icc_profile=profile)
        media = inspect(output, 'image')
        target = within(root, 'assets/media-references/' + media['sha256'] + '.png', exists=False)
        _copy_verified(output, target, media['sha256'])
        result = {'path': target.relative_to(root).as_posix(), 'kind': 'image',
                  'role': reference['role'], 'sha256': media['sha256']}
        record = {'schema_version': 1, 'operation': 'lossless-png', 'source': reference, 'output': media}
        validate_png(root, record, result, media)
        manifest = Path(temp) / 'derivation.json'
        atomic_json(manifest, record)
        sha = digest(manifest)
        destination = within(root, 'assets/media-references/' + sha + '.derivation.json', exists=False)
        _copy_verified(manifest, destination, sha)
        result['derivation'] = {'path': destination.relative_to(root).as_posix(), 'sha256': sha}
        return result
