"""Exercise destructive-action guards and full write/readback using temporary files."""
import copy
import gzip
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('usb',Path(__file__).resolve().parents[1]/'tools/install-usb.py')
usb=importlib.util.module_from_spec(spec); spec.loader.exec_module(usb)

class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.disk={'path':'/dev/sdz','type':'disk','tran':'usb','size':16*1024**3,
                   'serial':'TEST-ONLY','ro':False,'mountpoints':[None],
                   'children':[{'path':'/dev/sdz1','type':'part','mountpoints':[None]}]}

    def test_safe_usb_and_rejected_destinations(self):
        self.assertEqual(usb.validate_disk(self.disk,8*1024**3)[1],'TEST-ONLY')
        for key,value in [('type','part'),('tran','nvme'),('ro',True),('serial',''),('size',1)]:
            d=copy.deepcopy(self.disk);d[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):usb.validate_disk(d,8*1024**3)
        for mount in ('/','/home','/media/usb','[SWAP]'):
            d=copy.deepcopy(self.disk);d['children'][0]['mountpoints']=[mount]
            with self.subTest(mount=mount),self.assertRaises(ValueError):usb.validate_disk(d,8*1024**3)
        d=copy.deepcopy(self.disk);d['children'][0]['children']=[{'type':'crypt','path':'/dev/mapper/test'}]
        with self.assertRaises(ValueError):usb.validate_disk(d,8*1024**3)

    def test_bad_manifest(self):
        with self.assertRaises(ValueError):usb.validate_manifest({'project':'unrelated'})

    def test_full_write_readback_and_invalid_input(self):
        raw=bytes(range(256))*4096; compressed=gzip.compress(raw)
        m={'raw_bytes':len(raw),'raw_sha256':hashlib.sha256(raw).hexdigest(),
           'gzip_sha256':hashlib.sha256(compressed).hexdigest()}
        with tempfile.TemporaryFile() as target:
            image=io.BytesIO(compressed)
            usb.check_image(image,m)
            usb.write_and_verify(image,target.fileno(),m)
            target.seek(0);self.assertEqual(target.read(),raw)
        broken=dict(m,gzip_sha256='0'*64)
        with self.assertRaises(ValueError):usb.check_image(io.BytesIO(compressed),broken)
        broken=dict(m,raw_sha256='0'*64)
        with self.assertRaises(ValueError):usb.check_image(io.BytesIO(compressed),broken)
        with self.assertRaises(ValueError):usb.check_image(io.BytesIO(compressed),dict(m,raw_bytes=len(raw)-1))

if __name__ == '__main__':unittest.main()
