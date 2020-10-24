#!/usr/bin/env bash
echo -e "\n\n***** deploy liftAi time updater script *****"
parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
cd "$parent_path"

echo "enable track_commit_timestamp in postgres configuration"
POSTGRES_CONFIG=/etc/postgresql/9.6/main/postgresql.conf
sudo sed -i 's/#track_commit_timestamp = off/track_commit_timestamp = on/g' $POSTGRES_CONFIG

sudo cp ./time_update_from_db.sh /home/pi/
sudo cp ./timeupdater.service /etc/systemd/system/
sudo systemctl enable timeupdater
sudo systemctl start timeupdater
