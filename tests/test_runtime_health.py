import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.catalog.bindings import configured_binding
from videocreate.config.storage import load_json
from videocreate.runtime import health


class BindingHealthTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.binding=configured_binding(config(),'grok-on-sub2api')

    def test_observer_waits_until_concurrent_cooldown_reader_closes_file(self):
        health.observe(self.root,self.binding,failed=True,seconds=60)
        opened=threading.Event();release=threading.Event();observing=threading.Event()
        def read_open(path):
            with path.open(encoding='utf-8') as handle:
                opened.set()
                if not release.wait(5):raise RuntimeError('Fixture reader timed out')
                return json.load(handle)
        def observe():
            observing.set();health.observe(self.root,self.binding,failed=False)
        with ThreadPoolExecutor(max_workers=2) as pool, mock.patch.object(health,'load_json',side_effect=read_open):
            reader=pool.submit(health.cooling_down,self.root,self.binding)
            try:
                self.assertTrue(opened.wait(5))
                writer=pool.submit(observe);self.assertTrue(observing.wait(5))
                with self.assertRaises(TimeoutError):writer.result(timeout=.1)
            finally:release.set()
            self.assertTrue(reader.result(timeout=5));writer.result(timeout=5)
        self.assertFalse(health.cooling_down(self.root,self.binding))
        self.assertEqual(load_json(health._path(self.root,self.binding))['retry_after_epoch'],0)
        self.assertEqual(list((self.root/'runtime/binding-health').glob('*.tmp')),[])

    def test_missing_or_malformed_optional_health_keeps_route_available(self):
        self.assertFalse(health.cooling_down(self.root,self.binding))
        self.assertEqual(list(self.root.iterdir()),[])
        path=health._path(self.root,self.binding);path.parent.mkdir(parents=True)
        path.write_text('{invalid',encoding='utf-8')
        self.assertFalse(health.cooling_down(self.root,self.binding))
        health.observe(self.root,self.binding,failed=True,seconds=1)
        self.assertTrue(health.cooling_down(self.root,self.binding))
        with mock.patch.object(health.time,'time',return_value=time.time()+2):
            self.assertFalse(health.cooling_down(self.root,self.binding))


if __name__=='__main__':unittest.main()
