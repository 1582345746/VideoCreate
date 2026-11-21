"""Explicit NewAPI data-URI transport; bytes stay out of saved task records."""
import base64
import hashlib
from pathlib import Path

from ..config.storage import ConfigError
from ..media_references import prepare_references
from ..planning.project import within

# Local memory/wire bound before the provider's independent limits.
MAX_INLINE_BYTES = 32 * 1024 * 1024


def prepare_inline(root, references):
    media = prepare_references(root, references)
    if sum(item['bytes'] for item in media) > MAX_INLINE_BYTES:
        raise ConfigError('Inline reference payload exceeds 32 MiB local limit')
    return [{**item, 'inline_path': str(within(Path(root), reference['path']))}
            for item, reference in zip(media, references)]


def data_uri(reference):
    """Recheck exact registered bytes immediately before constructing the wire body."""
    path = reference.get('inline_path')
    if not isinstance(path, str) or not path:
        raise ConfigError('Inline reference needs an actual registered local file')
    try:
        with Path(path).open('rb') as stream:
            data = stream.read(MAX_INLINE_BYTES + 1)
    except OSError:
        raise ConfigError('Inline reference file is not readable') from None
    if (not data or len(data) > MAX_INLINE_BYTES or len(data) != reference.get('bytes')
            or hashlib.sha256(data).hexdigest() != reference.get('sha256')):
        raise ConfigError('Inline reference bytes changed or exceed the local limit')
    mime = reference.get('mime_type')
    allowed = {'image': {'image/png', 'image/jpeg', 'image/webp'},
               'video': {'video/mp4'}, 'audio': {'audio/mpeg', 'audio/wav'}}
    if mime not in allowed.get(reference.get('kind'), set()):
        raise ConfigError('Inline reference MIME type is unsupported')
    return 'data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii')
