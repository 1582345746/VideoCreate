"""Explicit offline authoring commands shared with the native manager."""
import argparse
from pathlib import Path
from . import authoring
from .cli import print_result
from .config.storage import load_json
from .planning.profiles import FLOWS, PROFILES


def command(argv):
    parser=argparse.ArgumentParser(prog='videocreate authoring')
    sub=parser.add_subparsers(dest='action',required=True)
    create=sub.add_parser('create',help='Create an editable draft without selecting or calling a model')
    create.add_argument('project',type=Path)
    create.add_argument('--profile',choices=PROFILES)
    create.add_argument('--flow',choices=FLOWS)
    create.add_argument('--title',required=True)
    for name in ('topic','audience','viewer-goal'):create.add_argument('--'+name,default='')
    create.add_argument('--seconds',type=float)
    create.add_argument('--aspect-ratio',default='16:9')
    for action in ('show','preview','save','outline'):
        child=sub.add_parser(action)
        child.add_argument('project',type=Path)
        if action!='outline':child.add_argument('--layer',choices=authoring.LAYERS,required=True)
        if action in {'preview','save'}:
            child.add_argument('--file',type=Path,required=True)
            child.add_argument('--source-token',required=True)
        if action=='save':child.add_argument('--preview-token',required=True)
    args=parser.parse_args(argv)
    if args.action=='create':
        result=authoring.create(args.project,profile=args.profile,flow=args.flow,title=args.title,topic=args.topic,
            audience=args.audience,viewer_goal=args.viewer_goal,seconds=args.seconds,aspect_ratio=args.aspect_ratio)
    elif args.action=='show':result=authoring.describe(args.project,args.layer)
    elif args.action=='outline':result=authoring.outline(args.project)
    else:
        kwargs={'source_token':args.source_token}
        if args.action=='save':kwargs['preview_token']=args.preview_token
        result=getattr(authoring,args.action)(args.project,args.layer,load_json(args.file),**kwargs)
    print_result(result)
    return int(not result['ok'])
