#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Optional, run locally on the receiver with YOUR public key, never a private key.
set -euo pipefail
[[ $EUID == 0 && $(hostname) == imac-receiver ]]
KEY=${1:?Usage: sudo tools/enable-ssh.sh /path/to/YOUR_PUBLIC_KEY.pub}
[[ -f $KEY && $KEY == *.pub ]]
ssh-keygen -l -f "$KEY"
! grep -q 'PRIVATE KEY' "$KEY"
install -d -m700 -o receiver -g receiver /home/receiver/.ssh
install -m600 -o receiver -g receiver "$KEY" /home/receiver/.ssh/authorized_keys
ssh-keygen -A
systemctl enable --now ssh
echo 'Key-only SSH enabled for receiver; the selected key replaces any previous key.'
