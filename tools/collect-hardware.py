#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only inventory: no enrollment, mounting, resets, or modesetting."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
p=Path(sys.argv[1] if len(sys.argv)>1 else '/var/log/imac-receiver/hardware')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');p.mkdir(parents=True)
commands=[['uname','-a'],['lspci','-nnk'],['lsusb'],['lsblk','-o','NAME,SIZE,MODEL,SERIAL,FSTYPE,LABEL,MOUNTPOINTS'],['boltctl','list'],['ip','-br','address'],['v4l2-ctl','--list-devices'],['modetest','-M','amdgpu','-c','-p'],['arecord','-l'],['journalctl','-b','--no-pager'],['modinfo','gc555']]
results=[]
for i,cmd in enumerate(commands):
    fn=f'{i:02d}-{cmd[0]}.log'
    with (p/fn).open('w') as f:
        try:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=30);code=r.returncode
        except (OSError,subprocess.TimeoutExpired) as e:f.write(str(e));code=str(e)
    results.append(dict(command=cmd,exit_code=code,file=fn))
for node in Path('/sys/class/video4linux').glob('video*'):
    for option in ['--all','--list-formats-ext','--query-dv-timings']:
        cmd=['v4l2-ctl','-d','/dev/'+node.name,option];fn=node.name+option+'.log'
        with (p/fn).open('w') as f:
            try:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=15);code=r.returncode
            except (OSError,subprocess.TimeoutExpired) as e:f.write(str(e));code=str(e)
        results.append(dict(command=cmd,exit_code=code,file=fn))
readings={}
for pattern in ['/sys/class/dmi/id/product_*','/sys/class/drm/card*-*/status','/sys/class/drm/card*-*/modes','/sys/class/drm/card*-*/connector_id','/sys/bus/thunderbolt/devices/*/authorized','/sys/bus/thunderbolt/devices/*/device_name']:
    import glob
    for name in glob.glob(pattern):
        try:readings[name]=Path(name).read_text()
        except OSError as e:readings[name]=str(e)
(p/'sysfs.json').write_text(json.dumps(readings,indent=2)+'\n');(p/'commands.json').write_text(json.dumps(results,indent=2)+'\n');print(p)
