"""Make ordered, locally reproducible identity references from project character cards."""
from pathlib import Path
from tempfile import TemporaryDirectory

from .asset_library import _copy_verified, digest, project_media_revision
from .config.storage import ConfigError, atomic_json, load_json
from .media_references import inspect, register
from .planning.project import load_project, within
from .runtime.state import state_lock
from .still_images import pillow_modules


def _layout(columns, cells):
    if type(columns) is not int or not isinstance(cells, list) or not 1 <= columns <= len(cells):
        raise ConfigError('A cast sheet needs ordered cells and a positive column count')
    rows = (len(cells) + columns - 1) // columns
    width, height = columns * 384, rows * 512
    if width * height > 16 * 1024 * 1024:
        raise ConfigError('Cast sheet canvas exceeds 16 megapixels')
    return width, height


def _render(root, columns, cells):
    Image, ImageOps = pillow_modules()
    if not hasattr(Image, 'Resampling'):
        raise ConfigError('Cast sheets require Pillow 9.2 or newer. Install videocreate[media].')
    canvas = Image.new('RGB', _layout(columns, cells), (250, 244, 233))
    for index, cell in enumerate(cells):
        if (not isinstance(cell, dict) or set(cell) != {'asset_id', 'path', 'sha256', 'crop_xywh', 'library_revision'}
                or not all(isinstance(cell[k], str) and cell[k] for k in ('asset_id', 'path', 'sha256'))):
            raise ConfigError('Invalid cast sheet source record')
        original = within(root, cell['path'])
        if digest(original) != cell['sha256']:
            raise ConfigError('Cast sheet source changed: ' + cell['asset_id'])
        if project_media_revision(root, cell['path'], cell['sha256']) != cell['library_revision']:
            raise ConfigError('Cast sheet library revision changed: ' + cell['asset_id'])
        with Image.open(original) as source:
            if getattr(source, 'n_frames', 1) != 1:
                raise ConfigError('Select a still image for each cast sheet cell')
            picture = ImageOps.exif_transpose(source).convert('RGBA')
        crop = cell['crop_xywh']
        if crop is not None:
            if not isinstance(crop, list) or len(crop) != 4 or any(type(v) is not int for v in crop):
                raise ConfigError('Cast sheet crop needs integer x, y, width and height')
            x, y, w, h = crop
            if min(x, y) < 0 or min(w, h) < 1 or x+w > picture.width or y+h > picture.height:
                raise ConfigError('Cast sheet crop must fit the selected image')
            picture = picture.crop((x, y, x+w, y+h))
        part = ImageOps.contain(picture, (366, 492), Image.Resampling.LANCZOS)
        row, col = divmod(index, columns)
        left = col * 384 + (384 - part.width) // 2
        bottom = (row + 1) * 512 - 10
        canvas.paste(part, (left, bottom - part.height), part)
    return canvas


def validate_sheet(root, record, reference, media):
    Image, _ = pillow_modules()
    if (set(record) != {'schema_version', 'operation', 'columns', 'cells', 'output'} or record['schema_version'] != 1
            or media['kind'] != 'image' or media['mime_type'] != 'image/png' or reference['role'] != 'identity'
            or record['output'] != media):
        raise ConfigError('Invalid cast sheet identity reference')
    picture = _render(root, record['columns'], record['cells'])
    with Image.open(within(root, reference['path'])) as actual:
        if actual.mode != 'RGB' or actual.size != picture.size or actual.tobytes() != picture.tobytes():
            raise ConfigError('Cast sheet pixels differ from the ordered character sources')


def create_sheet(root, spec):
    root = Path(root).resolve()
    if not isinstance(spec, dict) or set(spec) != {'columns', 'cells'}:
        raise ConfigError('Specify the cast sheet columns and ordered cells')
    columns = spec['columns']
    _layout(columns, spec['cells'])
    cards = {a['id']: a for a in load_project(root)['director']['assets']}
    cells = []
    for item in spec['cells']:
        if (not isinstance(item, dict) or set(item) - {'asset_id', 'media_index', 'crop_xywh'}
                or not isinstance(item.get('asset_id'), str)):
            raise ConfigError('Each cell needs an asset_id and optional media_index or crop_xywh')
        card = cards.get(item['asset_id'], {})
        paths = card.get('references', [])
        index = item.get('media_index', 1 if len(paths) == 1 else None)
        if card.get('kind') != 'character' or type(index) is not int or not 1 <= index <= len(paths):
            raise ConfigError('Select an existing character image and its one-based media index')
        path = paths[index-1]
        sha = digest(within(root, path))
        cells.append({'asset_id': card['id'], 'path': path, 'sha256': sha, 'crop_xywh': item.get('crop_xywh'),
                      'library_revision': project_media_revision(root, path, sha)})
    picture = _render(root, columns, cells)
    with TemporaryDirectory() as temp:
        output = Path(temp) / 'sheet.png'
        picture.save(output)
        ref = register(root, output, kind='image', role='identity')
        media = inspect(within(root, ref['path']), 'image')
        manifest = Path(temp) / 'derivation.json'
        atomic_json(manifest, {'schema_version': 1, 'operation': 'cast-sheet-v1', 'columns': columns,
                               'cells': cells, 'output': media})
        sha = digest(manifest)
        folder = within(root, ref['path']).parent
        target = folder / (sha + '.derivation.json')
        with state_lock(root):
            _copy_verified(manifest, target, sha)
            ref['derivation'] = {'path': target.relative_to(root).as_posix(), 'sha256': sha}
            receipt = folder / (ref['sha256'] + '-' + sha + '-identity.reference.json')
            atomic_json(receipt, ref)
    return {'ok': True, 'reference': ref, 'reference_file': str(receipt), 'cells': len(cells),
            'plan_modified': False, 'paid_creates': 0}


def image_slots(root, references):
    """Index whole images by path, and sheet crops by both path and character."""
    slots = {}
    images = (ref for ref in references if ref.get('kind') == 'image')
    for index, ref in enumerate(images, 1):
        slot = (index, 0, 0)
        slots.setdefault((ref['path'], None), set()).add(slot)
        if 'derivation' not in ref:
            continue
        pointer = ref['derivation']
        manifest = within(root, pointer['path'])
        if digest(manifest) != pointer['sha256']:
            raise ConfigError('Image source mapping changed before compilation')
        record = load_json(manifest)
        if record['operation'] == 'cast-sheet-v1':
            for offset, cell in enumerate(record['cells']):
                row, column = divmod(offset, record['columns'])
                slots.setdefault((cell['path'], cell['asset_id']), set()).add((index, row+1, column+1))
        else:
            slots.setdefault((record['source']['path'], None), set()).add(slot)
    return slots


def slots_for_asset(slots, asset):
    result = set()
    for path in asset.get('references', []):
        result.update(slots.get((path, None), ()))
        result.update(slots.get((path, asset['id']), ()))
    return sorted(result)
