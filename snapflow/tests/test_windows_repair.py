"""Transactional updater checks in an isolated fake install, never on Windows user data."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from test_app import ARTIFACTS

spec=importlib.util.spec_from_file_location('windows_repair',Path(__file__).resolve().parents[2]/'tools/windows_repair.py')
repair=importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)

class RepairTests(unittest.TestCase):
    def setUp(self):
        self.project=ARTIFACTS/self._testMethodName
        self.root=self.project/repair.NAME/repair.NAME
        self.root.mkdir(parents=True)
        for name in repair.ALLOWED-{'vision_network.py'}:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('old '+name)
        (self.root/'vision_settings.py').write_text('old vision_settings.py')
        (self.root/'data').mkdir()
        (self.root/'data/vision-private.json').write_text('private fixture preserved')
        (self.root/'data/snapflow.sqlite3').write_bytes(b'user-record-fixture')
        self.payload={name:{'data':base64.b64encode(('new '+name).encode()).decode(),'sha256':hashlib.sha256(('new '+name).encode()).hexdigest()} for name in repair.ALLOWED}
    def test_exact_install_backup_hashes_and_preservation(self):
        self.assertEqual(repair.find_root(self.project),self.root)
        backup=repair.install(self.root,self.payload,stop=lambda _:None)
        receipt=json.loads((backup/'RECEIPT.json').read_text())
        self.assertEqual(receipt['status'],'complete')
        for row in receipt['entries']:
            if row['existed']:
                self.assertEqual(hashlib.sha256((backup/row['path']).read_bytes()).hexdigest(),row['sha256'])
        self.assertEqual((self.root/'data/vision-private.json').read_text(),'private fixture preserved')
        self.assertEqual((self.root/'data/snapflow.sqlite3').read_bytes(),b'user-record-fixture')
        self.assertTrue(json.loads((self.root/'data/network-settings.json').read_text())['allow_existing_ssh_bridge'])
    def test_bad_payload_does_not_stop_or_modify_app(self):
        self.payload['server.py']['sha256']='wrong'
        with patch.object(repair,'stop_target') as stop:
            with self.assertRaises(ValueError):repair.install(self.root,self.payload,stop)
            stop.assert_not_called()
        self.assertEqual((self.root/'server.py').read_text(),'old server.py')
    def test_partial_write_rolls_back_original_files(self):
        real_replace=repair.os.replace
        calls=[]
        def fail(src,dst):
            calls.append(dst)
            if len(calls)==3:raise OSError('simulated disk error')
            return real_replace(src,dst)
        with patch.object(repair.os,'replace',side_effect=fail):
            with self.assertRaises(OSError):repair.install(self.root,self.payload,stop=lambda _:None)
        for name in repair.ALLOWED-{'vision_network.py'}:
            self.assertEqual((self.root/name).read_text(),'old '+name)
        self.assertFalse((self.root/'vision_network.py').exists())
        self.assertFalse((self.root/'data/network-settings.json').exists())
        self.assertEqual((self.root/'data/vision-private.json').read_text(),'private fixture preserved')
