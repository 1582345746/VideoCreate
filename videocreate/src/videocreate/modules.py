"""Machine-readable capabilities and roadmap tracking, shipped with the skill."""
import argparse
from .config.storage import load_json


def catalog():
    from .cli import skill_root
    return load_json(skill_root() / 'assets' / 'module-catalog.json')


def command(argv):
    from .cli import print_result
    parser = argparse.ArgumentParser(prog='videocreate modules')
    parser.add_argument('action', choices=['list', 'roadmap'])
    parser.add_argument('--id')
    args = parser.parse_args(argv)
    data = catalog()
    rows = data['modules' if args.action == 'list' else 'work_packages']
    if args.id:
        rows = [r for r in rows if r['id'] == args.id]
    print_result({'ok': True, 'updated_at': data['updated_at'], 'entries': rows,
                  'status_definitions': data['status_definitions'], 'paid_creates': 0})
    return 0
