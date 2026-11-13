"""Read-only timeline projections shared by authoring preview and native forms."""
from .timeline.model import mapping, validate_timeline


def inspect(timeline):
    from .timeline.finishing import KEYS
    errors=validate_timeline(timeline)
    if errors:return {'ok':False,'errors':errors,'content':'unverified','paid_creates':0}
    return {'ok':True,**mapping(timeline),'overlays':timeline.get('overlays',[]),
        'finishing':{key:timeline[key] for key in KEYS if key in timeline},
        'content':'unverified','paid_creates':0}
