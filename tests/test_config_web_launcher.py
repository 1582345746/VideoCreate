"""Actual loopback startup/reuse: configuration and media process lifecycles differ."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.parse
import hashlib
import io
import wave
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.config.management import migrate
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.config_web.launcher import launch


class WebLauncherTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.path=self.root/'config.json';atomic_json(self.path,migrate(config()))

    def port(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

    def server(self,port,read_only=False):
        env=dict(os.environ);env['PYTHONDONTWRITEBYTECODE']='1'
        code='from videocreate.config_web.launcher import launch; launch('+repr(str(self.path))+',port='+str(port)+',browser=False,read_only='+repr(read_only)+')'
        log=(self.root/'server.log').open('w',encoding='utf-8');self.addCleanup(log.close)
        process=subprocess.Popen([sys.executable,'-B','-X','utf8','-c',code],env=env,stdout=log,stderr=subprocess.STDOUT)
        def stop():
            if process.poll() is None:process.terminate()
            process.wait(timeout=10)
        self.addCleanup(stop)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            try:
                with opener.open('http://127.0.0.1:'+str(port)+'/health',timeout=.15) as r:return process,json.load(r)
            except OSError:
                if process.poll() is not None:raise AssertionError('fixture server exited')
                time.sleep(.05)
        self.fail('fixture startup timed out')

    def test_same_config_version_instance_mode_is_reused_without_starting_another_server(self):
        port=self.port();process,health=self.server(port)
        with mock.patch('videocreate.config_web.launcher.webbrowser.open') as browser:
            self.assertEqual(launch(self.path,port=port),0)
            browser.assert_called_once_with('http://127.0.0.1:'+str(port))
        self.assertIsNone(process.poll());self.assertEqual(health['mode'],'editable')
        with mock.patch('videocreate.config_web.launcher.webbrowser.open') as browser:
            for path,readonly in ((self.root/'other.json',False),(self.path,True)):
                with self.assertRaises(ConfigError):launch(path,port=port,read_only=readonly)
            browser.assert_not_called()

    def test_wrong_version_or_nonce_and_unknown_occupied_port_never_open_browser(self):
        port=self.port();self.server(port)
        marker=self.root/'runtime/config-web'/('instance-'+str(port)+'.json')
        row=json.loads(marker.read_text());row['instance_id']='wrong';atomic_json(marker,row)
        with mock.patch('videocreate.config_web.launcher.webbrowser.open') as browser:
            with self.assertRaises(ConfigError):launch(self.path,port=port)
            browser.assert_not_called()
        other=self.port()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',other));sock.listen()
            with self.assertRaises(ConfigError):launch(self.path,port=other,browser=False)

    def test_media_port_and_invalid_ports_are_rejected_without_any_socket_bind(self):
        with mock.patch('videocreate.config_web.launcher.socket.socket',side_effect=AssertionError('no bind')):
            for port in (0,80,8765,65536):
                with self.assertRaises(ConfigError):launch(self.path,port=port,browser=False)

    def test_dependency_diagnostics_distinguish_missing_incomplete_and_runtime_loading_without_binding(self):
        original_import=__import__
        marker='private-import-error-detail'
        cases=((ModuleNotFoundError(marker,name='uvicorn'),'Web dependencies are missing'),
               (ModuleNotFoundError(marker,name='fastapi'),'Web dependencies are missing'),
               (ModuleNotFoundError(marker,name='private-transitive-module'),'Web runtime dependencies are incomplete'),
               (ImportError(marker),'Web runtime could not load'))
        before=self.path.read_bytes()
        for failure,message in cases:
            def importing(name,*args,**kwargs):
                if name=='uvicorn':raise failure
                return original_import(name,*args,**kwargs)
            with mock.patch('builtins.__import__',side_effect=importing), \
                 mock.patch('videocreate.config_web.launcher.socket.socket',side_effect=AssertionError('no bind')):
                with self.assertRaises(ConfigError) as error:launch(self.path,port=18787,browser=False)
            self.assertIn(message,str(error.exception));self.assertNotIn(marker,str(error.exception))
            self.assertNotIn('private-transitive-module',str(error.exception))
        self.assertEqual(self.path.read_bytes(),before)

    def test_console_and_parent_cli_return_structured_expected_startup_errors_without_traceback(self):
        from videocreate.cli import main as cli_main
        from videocreate.config_web.launcher import main as web_main
        before=self.path.read_bytes();packets=[]
        for command,args in ((web_main,[]),(cli_main,['config-web'])):
            output=io.StringIO()
            with redirect_stdout(output),mock.patch('videocreate.config_web.launcher.socket.socket',side_effect=AssertionError('no bind')):
                self.assertEqual(command([*args,'--config',str(self.path),'--port','8765','--no-browser']),1)
            packets.append(json.loads(output.getvalue()))
            self.assertNotIn('Traceback',output.getvalue());self.assertFalse(packets[-1]['ok'])
            self.assertIn('dedicated configuration port',packets[-1]['error'])
        self.assertEqual(packets[0],packets[1]);self.assertEqual(self.path.read_bytes(),before)

    def test_independent_media_restart_preserves_bytes_after_web_process_exits(self):
        from videocreate import media_server as media
        value=migrate(config());media_port=self.port()
        value['local_media_server']={'port':media_port,'public_base_url':'https://media.example.test'}
        atomic_json(self.path,value)
        web,_=self.server(self.port())
        source=self.root/'fixture.wav'
        with wave.open(str(source),'wb') as stream:
            stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000);stream.writeframes(b'\x12\x34'*16000)
        self.addCleanup(lambda:media.stop(self.root))
        media.start(self.path)
        publication=media.publish(self.root,source,kind='audio',public_base_url='https://media.example.test',lifetime_seconds=600)
        url='http://127.0.0.1:'+str(media_port)+urllib.parse.urlsplit(publication['url']).path
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def read():
            with opener.open(url,timeout=2) as response:return hashlib.sha256(response.read()).hexdigest()
        expected=hashlib.sha256(source.read_bytes()).hexdigest();self.assertEqual(read(),expected)
        web.terminate();web.wait(timeout=10)
        self.assertTrue(media.status(self.root)['running']);self.assertEqual(read(),expected)
        media.stop(self.root);media.start(self.path)
        self.assertEqual(read(),expected)


if __name__=='__main__':unittest.main()
