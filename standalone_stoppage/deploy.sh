#!/usr/bin/env bash

PATH=$PATH:/usr/local/bin
parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
cd "$parent_path"

if ../misc_scripts/deploy_application.sh standalonestoppage liftai_standalonestoppage standalone_stoppage; then
  sudo -u postgres psql -d liftaidb -a -f ./post_install.sql
else
  echo "not running SQL post_install because deployment failed"
fi