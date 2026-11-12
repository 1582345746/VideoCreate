"""Offline playable review page; exports observations for the existing validator."""
import json
import os
from pathlib import Path

from ..config.storage import ConfigError
from ..planning.project import load_project, within
from .receipts import template


def export(root, *, output_name='preview.mp4'):
    root = Path(root).resolve()
    packet = template(root, load_project(root), output_name=output_name)
    destination = root / 'reviews' / 'viewer.html'
    destination.parent.mkdir(parents=True, exist_ok=True)
    from urllib.parse import quote
    media = {aid: quote(os.path.relpath(within(root, asset['path']), destination.parent).replace('\\', '/'), safe='/')
             for aid, asset in packet['assets'].items()}
    data = json.dumps({'receipt': packet, 'media': media}, ensure_ascii=False).replace('<', '\\u003c')
    from ..cli import skill_root
    html = (skill_root() / 'assets' / 'review-viewer.html').read_text(encoding='utf-8').replace('__REVIEW_DATA__', data)
    destination.write_text(html, encoding='utf-8')
    return {'ok': True, 'page': str(destination), 'assets': len(packet['assets']), 'paid_creates': 0,
        'note': 'Play and listen, record observations, export the receipt, then use review apply. Opening this page approves nothing.'}
