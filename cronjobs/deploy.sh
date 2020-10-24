#!/usr/bin/env bash
echo -e "\n\n***** deploy cronjob script *****"

parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
cd "$parent_path"

cron_file=/var/spool/cron/crontabs/pi

sudo cp ./*.sh /home/pi/

# Database truncator
echo "writing database truncator cron job"
sudo sed -i '/db_truncator.sh/d' $cron_file
sudo sh -c "echo '*/5 * * * * /home/pi/db_truncator.sh > /tmp/liftai_db_truncator.log 2>&1' >> $cron_file"

# Daily reboot
echo "writing periodic reboot cron job"
sudo sed -i '/periodic_reboot.sh/d' $cron_file
sudo sh -c "echo '7 6 * * * /home/pi/periodic_reboot.sh > /tmp/periodic_reboot.log 2>&1' >> $cron_file"

echo "writing update code cron job"
sudo sed -i '/update.sh/d' $cron_file
sudo sh -c "echo '31 6 * * * /home/pi/update.sh > /tmp/liftai_update.log 2>&1' >> $cron_file"

echo "writing diagnose code cron job"
sudo sed -i '/diagnose.sh/d' $cron_file
sudo sh -c "echo '43 */2 * * * /home/pi/diagnose.sh > /tmp/liftai_diagnose.log 2>&1' >> $cron_file"

echo "writing fast diagnose code cron job"
sudo sed -i '/fast_diagnose.sh/d' $cron_file
sudo sh -c "echo '*/6 * * * * /home/pi/fast_diagnose.sh > /tmp/liftai_fast_diagnose.log 2>&1' >> $cron_file"

echo "remove manufacturing test from crontab"
sudo sed -i '/mfg_test.sh/d' $cron_file

echo "adding installer retry cron job"
sudo sed -i '/installer_retry.sh/d' $cron_file
sudo sh -c "echo '7 20 * * * /home/pi/installer_retry.sh > /tmp/liftai_installer_retry.log 2>&1' >> $cron_file"

echo "adding system notifications cron job"
sudo sed -i '/system_check.sh/d' $cron_file
sudo sh -c "echo '45 23 * * * /home/pi/system_check.sh > /tmp/liftai_system_check.log 2>&1' >> $cron_file"

# Remove any binary characters that might have gotten into the cron file
echo "removing any binary characters from cron file"
temp_cron_file=$(mktemp /tmp/crontab.XXXXXXXXXX)
cp $cron_file $temp_cron_file
tr -cd '\11\12\15\40-\176' < $temp_cron_file > $cron_file

# Fix the cron file
echo "fixing file permissions"
sudo chown pi:crontab $cron_file
sudo chmod 600 $cron_file

# Need to restart the cron service to pick up the changes to the cron file
echo "restarting cron service"
sudo /etc/init.d/cron restart
