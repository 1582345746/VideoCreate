"""Decode an actual static image; normalize orientation and alpha for local holds."""
from pathlib import Path

from .config.storage import ConfigError


def pillow_modules():
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ConfigError('Image processing requires Pillow. Install videocreate[media] in this Python environment.') from None
    return Image, ImageOps


def inspect(path, *, normalized=None):
    Image, ImageOps = pillow_modules()
    try:
        with Image.open(path) as image:
            if image.format not in {'PNG', 'JPEG', 'WEBP'} or getattr(image, 'n_frames', 1) != 1:
                raise ConfigError('Use a single static PNG/JPEG/WebP; animated images need their own video/GIF workflow')
            image.load()
            oriented = ImageOps.exif_transpose(image)
            result = {'width': oriented.width, 'height': oriented.height,
                'has_audio': False, 'format': image.format, 'frame_count': '1'}
            if normalized is not None:
                rgba = oriented.convert('RGBA')
                canvas = Image.new('RGB', rgba.size, (0, 0, 0))
                canvas.paste(rgba, mask=rgba.getchannel('A'))
                canvas.save(Path(normalized), format='PNG')
            return result
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ConfigError('Static image could not be fully decoded: ' + type(exc).__name__) from None
