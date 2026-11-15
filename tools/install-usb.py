#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install a verified receiver image onto an explicitly confirmed USB disk."""
import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

CHUNK = 4 * 1024 * 1024

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def walk(node):
    yield node
    for child in node.get('children', []):
        yield from walk(child)

def validate_disk(node, required_bytes):
    if node.get('type') != 'disk' or node.get('tran') != 'usb':
        raise ValueError('Only whole USB disks are accepted, never partitions or internal disks.')
    if node.get('ro') or not node.get('serial'):
        raise ValueError('Disk is read-only or has no serial number for confirmation.')
    if int(node['size']) < required_bytes:
        raise ValueError('USB disk is too small for this image.')
    for part in walk(node):
        if any(part.get('mountpoints') or []):
            raise ValueError(f"Mounted/in-use device: {part['path']}; unmount it yourself first.")
        if part is not node and part.get('type') != 'part':
            raise ValueError('Device has active RAID/LVM/crypt/other dependent devices.')
    return (node['path'], node['serial'], int(node['size']))

def inspect_disk(device, required_bytes):
    info = json.loads(run('lsblk','--json','--tree','--bytes','--paths','--output',
                         'PATH,TYPE,TRAN,SIZE,MODEL,SERIAL,RO,MOUNTPOINTS',str(device)))
    if len(info['blockdevices']) != 1:
        raise ValueError('Ambiguous device selection.')
    node = info['blockdevices'][0]
    identity = validate_disk(node, required_bytes)
    swaps = set(run('swapon','--show','--noheadings','--raw','--output','NAME').splitlines())
    for part in walk(node):
        path = Path(part['path'])
        if str(path.resolve()) in swaps:
            raise ValueError('Device contains active swap.')
        holders = Path('/sys/class/block') / path.name / 'holders'
        if holders.exists() and any(holders.iterdir()):
            raise ValueError('Device has active kernel holders.')
    if not stat.S_ISBLK(device.stat().st_mode):
        raise ValueError('Destination is not a block device.')
    return node, identity

def validate_manifest(manifest):
    if manifest.get('project') != 'imac-display-receiver' or manifest.get('schema') != 1:
        raise ValueError('Not an iMac Receiver image manifest.')
    size = manifest.get('raw_bytes')
    if type(size) is not int or size < 1024**3 or size % 512:
        raise ValueError('Invalid raw image size.')
    for key in ('raw_sha256', 'gzip_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', manifest.get(key, '')):
            raise ValueError('Invalid checksum field: '+key)

def check_image(image, manifest):
    # Both transport and decompressed image verified BEFORE opening the destination.
    image.seek(0)
    h = hashlib.sha256()
    while chunk := image.read(CHUNK):
        h.update(chunk)
    if h.hexdigest() != manifest['gzip_sha256']:
        raise ValueError('Compressed image checksum mismatch; no disk was written.')
    image.seek(0)
    h = hashlib.sha256(); total = 0
    with gzip.GzipFile(fileobj=image, mode='rb') as compressed:
        while chunk := compressed.read(CHUNK):
            total += len(chunk)
            if total > manifest['raw_bytes']:
                raise ValueError('Decompressed image exceeds declared size.')
            h.update(chunk)
    if total != manifest['raw_bytes'] or h.hexdigest() != manifest['raw_sha256']:
        raise ValueError('Raw image checksum/size mismatch; no disk was written.')
    image.seek(0)

def write_and_verify(image, fd, manifest):
    image.seek(0)
    h = hashlib.sha256(); total = 0; last = time.monotonic()
    with gzip.GzipFile(fileobj=image, mode='rb') as compressed:
        while chunk := compressed.read(CHUNK):
            total += len(chunk)
            if total > manifest['raw_bytes']:
                raise ValueError('Image grew during write; stop.')
            h.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError('Short device write')
                view = view[written:]
            if time.monotonic()-last > 5:
                print(f'Written {total / 1024**3:.2f} GiB', flush=True)
                last = time.monotonic()
    if total != manifest['raw_bytes'] or h.hexdigest() != manifest['raw_sha256']:
        raise ValueError('Source changed during write; destination is not verified.')
    os.fsync(fd)
    os.lseek(fd, 0, os.SEEK_SET)
    h = hashlib.sha256(); remaining = total
    while remaining:
        chunk = os.read(fd, min(CHUNK, remaining))
        if not chunk:
            raise OSError('Unexpected end of device during readback')
        h.update(chunk); remaining -= len(chunk)
    if h.hexdigest() != manifest['raw_sha256']:
        raise ValueError('USB readback checksum mismatch.')

def grow_root(device, identity, size):
    subprocess.run(['partprobe',str(device)],check=True)
    subprocess.run(['udevadm','settle'],check=True)
    node, current = inspect_disk(device, size)
    if current != identity:
        raise ValueError('Device identity changed after writing.')
    children = node.get('children', [])
    if len(children) != 2:
        raise ValueError('Expected exactly two receiver partitions.')
    root = next((Path(p['path']) for p in children
                 if (Path('/sys/class/block') / Path(p['path']).name / 'partition').read_text().strip() == '2'), None)
    if root is None or run('blkid','-s','LABEL','-o','value',str(root)) != 'IMAC-ROOT':
        raise ValueError('Receiver root partition identity mismatch.')
    if run('blkid','-s','TYPE','-o','value',str(root)) != 'ext4':
        raise ValueError('Receiver root must be ext4.')
    subprocess.run(['sgdisk','-e',str(device)],check=True)
    subprocess.run(['parted','-s',str(device),'resizepart','2','100%'],check=True)
    subprocess.run(['partprobe',str(device)],check=True)
    subprocess.run(['udevadm','settle'],check=True)
    _, current = inspect_disk(device,size)
    if current != identity:
        raise ValueError('Device identity changed during partition resize.')
    result = subprocess.run(['e2fsck','-f','-p',str(root)])
    if result.returncode not in (0,1):
        raise RuntimeError('Filesystem check failed; no resize performed.')
    subprocess.run(['resize2fs',str(root)],check=True)
    subprocess.run(['sync'],check=True)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--list', action='store_true', help='List devices without writing')
    p.add_argument('--image', type=Path, help='Locally built .img.gz')
    p.add_argument('--manifest', type=Path)
    p.add_argument('--device', type=Path, help='Stable /dev/disk/by-id/usb-... link')
    args = p.parse_args()
    if args.list:
        subprocess.run(['lsblk','-o','PATH,TYPE,TRAN,SIZE,MODEL,SERIAL,MOUNTPOINTS'],check=True)
        return
    if not all((args.image,args.manifest,args.device)):
        p.error('--image, --manifest and --device are required')
    if os.geteuid() != 0:
        p.error('Run with sudo.')
    if not str(args.device).startswith('/dev/disk/by-id/usb-') or '-part' in args.device.name:
        p.error('Use the whole-disk /dev/disk/by-id/usb-... link from your own USB stick.')
    manifest = json.loads(args.manifest.read_text())
    validate_manifest(manifest)
    with args.image.open('rb') as image:
        check_image(image,manifest)
        node, identity = inspect_disk(args.device,manifest['raw_bytes'])
        print(json.dumps(node,indent=2))
        print('ALL DATA ON THIS USB DISK WILL BE ERASED. No other disk is a target.')
        expected = 'ERASE '+identity[1]
        with open('/dev/tty','r+') as tty:
            tty.write(f'Type exactly {expected!r}: '); tty.flush()
            if tty.readline().rstrip('\n') != expected:
                raise ValueError('Confirmation did not match; nothing written.')
        _, again = inspect_disk(args.device,manifest['raw_bytes'])
        if again != identity:
            raise ValueError('Device changed while confirming.')
        fd = os.open(args.device,os.O_RDWR | os.O_EXCL)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX | fcntl.LOCK_NB)
            if os.fstat(fd).st_rdev != args.device.stat().st_rdev:
                raise ValueError('Destination changed when opened.')
            write_and_verify(image,fd,manifest)
        finally:
            os.close(fd)
        grow_root(args.device,identity,manifest['raw_bytes'])
    print('USB image verified and root filesystem expanded. Boot iMac with Option → EFI Boot.')

if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'STOP: {exc}',file=sys.stderr)
        sys.exit(1)
