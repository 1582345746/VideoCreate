"""Bind first, then launch the browser; configuration/media lifecycles stay separate."""
import argparse
import json
import secrets
import socket
import urllib.request
import webbrowser
from pathlib import Path

from .. import __version__
from ..config.storage import ConfigError, atomic_json, user_config_path


def launch(path=None, *, port=8787, browser=True, read_only=False):
    if not 1024 <= port <= 65535 or port == 8765:
        raise ConfigError('Use a dedicated configuration port from 1024 to 65535; 8765 belongs to the media service')
    try:
        import uvicorn
        from .app import config_identity, create_app
    except ModuleNotFoundError as error:
        if error.name in {'fastapi','uvicorn'}:
            raise ConfigError('Web dependencies are missing; install the videocreate[web] optional dependencies') from None
        raise ConfigError('Web runtime dependencies are incomplete; reinstall the locked Web packages with the selected Python') from None
    except ImportError:
        raise ConfigError('Web runtime could not load; check the selected Python, locked Web packages and its runtime/DLL paths') from None
    path = user_config_path(path).resolve()
    origin = 'http://127.0.0.1:' + str(port)
    marker = path.parent / 'runtime' / 'config-web' / ('instance-' + str(port) + '.json')
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        sock.bind(('127.0.0.1', port))
    except OSError:
        sock.close()
        try:
            saved = json.loads(marker.read_text(encoding='utf-8'))
            # No proxies or redirects, even for a local identity probe.
            from ..catalog.discovery import NoRedirect
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
            with opener.open(origin + '/health', timeout=2) as response:
                active = json.loads(response.read(4096))
            expected = {'product': 'VideoCreateConfigWeb', 'version': __version__,
                        'config_id': config_identity(path), 'instance_id': saved['instance_id']}
            expected['mode'] = 'read-only' if read_only else 'editable'
            if active != expected or saved != expected:
                raise ValueError()
        except (OSError, ValueError, KeyError):
            raise ConfigError('Configuration port is occupied by another instance, version or configuration; choose a different --port') from None
        if browser:
            webbrowser.open(origin)
        return 0
    identity = {'product': 'VideoCreateConfigWeb', 'version': __version__,
                'config_id': config_identity(path), 'instance_id': secrets.token_hex(24),
                'mode': 'read-only' if read_only else 'editable'}
    try:
        app = create_app(path, port=port, instance_id=identity['instance_id'], read_only=read_only)
        atomic_json(marker, identity)
        print(json.dumps({'url': origin, 'config_path': str(path), 'version': __version__}, ensure_ascii=False), flush=True)
        config = uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False,
                                log_level='critical', server_header=False, timeout_keep_alive=5)

        class Server(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if browser and self.started:
                    webbrowser.open(origin)

        try:
            Server(config).run(sockets=[sock])
        except KeyboardInterrupt:
            pass
    finally:
        sock.close()
        try:
            if json.loads(marker.read_text(encoding='utf-8')) == identity:
                marker.unlink()
        except (OSError, ValueError):
            pass
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog='videocreate config-web')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--read-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        return launch(args.config, port=args.port, browser=not args.no_browser, read_only=args.read_only)
    except (ConfigError,OSError,ValueError) as error:
        from ..cli import print_result
        from ..config.storage import safe_error
        print_result({'ok':False,'error':safe_error(error)})
        return 1
