"""Opt-in root test: resize a newly allocated loop image, never a physical disk."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('usb',Path(__file__).resolve().parents[1]/'tools/install-usb.py')
usb=importlib.util.module_from_spec(spec);spec.loader.exec_module(usb)

@unittest.skipUnless(os.environ.get('TEST_USB_LOOP')=='1' and os.geteuid()==0,
                     'Needs explicit TEST_USB_LOOP=1 and root; uses only a new loop image')
class LayoutTest(unittest.TestCase):
    def test_gpt_and_ext4_expansion(self):
        with tempfile.TemporaryDirectory(prefix='imac-loop-test-') as d:
            image=Path(d)/'test.img'
            with image.open('wb') as f:f.truncate(128*1024**2)
            subprocess.run(['sgdisk','--clear','--new=1:2048:+8M','--typecode=1:ef00',
                            '--new=2:0:+48M','--typecode=2:8300',str(image)],check=True,stdout=subprocess.DEVNULL)
            loop=Path(usb.run('losetup','--find','--show','--partscan',str(image)))
            try:
                subprocess.run(['udevadm','settle'],check=True)
                root=Path(str(loop)+'p2')
                subprocess.run(['mkfs.ext4','-q','-F','-L','IMAC-ROOT',str(root)],check=True)
                before=int(usb.run('blockdev','--getsize64',str(root)))
                # USB-selection policy is separately tested. The only bypass here
                # is scoped to this freshly allocated, verified backing file.
                def inspect(device,size):
                    self.assertEqual(device,loop)
                    self.assertEqual(Path(usb.run('losetup','-n','-O','BACK-FILE',str(loop))),image)
                    node=json.loads(usb.run('lsblk','-Jbp','--tree','-o','PATH,TYPE,SIZE,MOUNTPOINTS',str(loop)))['blockdevices'][0]
                    for part in usb.walk(node):self.assertFalse(any(part.get('mountpoints') or []))
                    return node,(str(loop),'temporary-loop-test',128*1024**2)
                with patch.object(usb,'inspect_disk',side_effect=inspect):
                    usb.grow_root(loop,(str(loop),'temporary-loop-test',128*1024**2),64*1024**2)
                after=int(usb.run('blockdev','--getsize64',str(root)))
                self.assertGreater(after,before)
                self.assertGreater(after,100*1024**2)
                self.assertEqual(usb.run('blkid','-s','LABEL','-o','value',str(root)),'IMAC-ROOT')
                subprocess.run(['e2fsck','-fn',str(root)],check=True,stdout=subprocess.DEVNULL)
            finally:
                subprocess.run(['losetup','-d',str(loop)],check=True)

if __name__=='__main__':unittest.main()
