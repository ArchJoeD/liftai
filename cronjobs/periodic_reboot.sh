#!/usr/bin/env bash

LOG_FILE="/home/pi/liftai_logs/last_periodic_reboot.log"
REBOOT_INFO="/home/pi/reboot_info"

echo `date` > $LOGFILE
echo `date` > $REBOOT_INFO

sudo reboot




