#!/usr/bin/env bash

PATH=$PATH:/usr/local/bin
parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
cd "$parent_path"

if ../misc_scripts/deploy_application.sh accelerometer liftai_accelerometer accelerometer; then
  sudo -u postgres psql -d liftaidb -a -f ./install.sql
else
  echo "not running SQL install because deployment failed"
fi