#!/usr/bin/env bash

PATH=$PATH:/usr/local/bin
parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
cd "$parent_path"

../misc_scripts/deploy_application.sh altimeter liftai_altimeter altimeter

