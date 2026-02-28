#!/bin/bash
# Run this script with: sudo bash /mnt/c/dev/mistralhack/setup-sudo.sh
echo "titan ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/titan
chmod 440 /etc/sudoers.d/titan
echo "Done! Passwordless sudo configured for titan."
