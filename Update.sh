#!/usr/bin/env bash
set -e
echo "### UPDATE-SKRIPT ###"
echo ">>> [1/2] System-Update..."
yay -Syu --needed hyprlock swww
echo ">>> [2/2] Audio-Restart..."
systemctl --user restart pipewire.service pipewire-pulse.service wireplumber.service
if [[ "$1" == "-r" ]]; then
    echo "!!! REBOOT in 15s !!!"
    sleep 15
    sudo reboot
fi
