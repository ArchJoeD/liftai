#!/usr/bin/env bash

PATH=$PATH:/usr/local/bin
parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
cd "$parent_path"

echo -e "\n\n*****  removing doors service (if it's installed, ignore failures here)  *****"
sudo systemctl stop doors.service
sudo systemctl disable doors.service
sudo rm -fr /etc/systemd/system/doors.service
sudo systemctl daemon-reload
sudo systemctl reset-failed doors.service
sudo rm -fr /home/pi/.virtualenvs/liftai_doors
# Leave the SQL stuff alone.
