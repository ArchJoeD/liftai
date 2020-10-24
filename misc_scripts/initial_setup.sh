#!/bin/bash

#  This script is used for creating a gold master SD card which can be used for duplicating to manufactured devices.

echo "====  creating a gold master image from a (hopefully) clean Raspbian installation  ===="
cd /home/pi

echo "setting up keyboard..."
sudo sed -i -e 's/gb/us/' /etc/default/keyboard
sudo setupcon


echo "creating ssh stuff..."
if ! ls /home/pi/id_rsa* 1> /dev/null 2>&1; then
  echo "/home/pi/id_rsa* file doesn't exist!  You need to add the key files.  quitting..."
  exit -1
fi
if ! ls /home/pi/*.pub 1>/dev/null 2>&1; then
  echo "/home/pi/*.pub file doesn't exist!  You need to add ALL the key files.  quitting..."
  exit -1
fi
mkdir -p .ssh
chmod 700 .ssh
mv /home/pi/id_rsa* /home/pi/.ssh
mv /home/pi/*.pub /home/pi/.ssh
cat /home/pi/.ssh/*.pub > /home/pi/.ssh/authorized_keys
chmod 644 /home/pi/.ssh/*.pub /home/pi/.ssh/authorized_keys
chmod 600 /home/pi/.ssh/id_rsa
echo > /home/pi/.ssh/known_hosts
chmod 644 /home/pi/.ssh/known_hosts
sudo sed -i -e 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
# Don't know if we actually need both of these.
sudo sed -i 's/PasswordAuthentication/#PasswordAuthentication/g' /etc/ssh/sshd_config
sudo sh -c 'echo "PasswordAuthentication no" >> /etc/ssh/sshd_config'
sudo service ssh restart
sudo systemctl enable ssh


echo "setting up software..."
sudo apt-get -y update
sudo apt-get -y install python3-pip
sudo apt-get -y install git


echo "getting LiftAI proprietary software...  (patent and copyright protected)"
ssh-keyscan github.com >> /home/pi/.ssh/known_hosts
cd /home/pi
git clone git@github.com:LiftAI/python-development.git


echo "setting up cellular modem stuff..."
sudo apt-get -y install ppp
# Do lsusb to see if modem is detected and USB is opering in the correct mode
lsusb   # If you see "Modem/Networkcard" in the response, it's good.  Otherwise, lots of steps involved.
# Install ppp scripts
# These come from:  wget https://github.com/twilio/wireless-ppp-scripts/archive/master.zip
sudo cp /home/pi/python-development/files/ppp_scripts/chatscripts/* /etc/chatscripts
sudo cp /home/pi/python-development/files/ppp_scripts/peers/* /etc/ppp/peers


echo "setting up network timing synchronization..."
sudo timedatectl set-ntp true


echo "running LiftAI software installation..."
cd /home/pi/python-development
./deploy_clean_raspbian.sh


echo "starting to create gold master image..."
dbname=liftaidb


echo "stopping all services..."
sudo systemctl stop accelerometer.service
sudo systemctl stop altimeter.service
sudo systemctl stop audiorecorder.service
sudo systemctl stop bankstoppage.service
sudo systemctl stop datasender.service
sudo systemctl stop elevation.service
sudo systemctl stop reportgenerator.service
sudo systemctl stop roawatch.service
sudo systemctl stop trips.service


# Need to run the actual hostname setup when this reboots next on the final machine.
echo "setting up the runonce stuff..."
tempcron=/home/pi/tempcron
sudo mkdir -p /etc/runonce.d/ran
sudo crontab -l > $tempcron
echo "@reboot /home/pi/runonce.sh" >> $tempcron
sudo crontab $tempcron
rm $tempcron
sudo cp /home/pi/python-development/cronjobs/hostname_setup.sh /etc/runonce.d

delete_all_rows () {
    echo "$(date) exec sql: DELETE FROM $1;"
    sudo -u postgres psql -qtAX -d $dbname -c "DELETE FROM $1;"
}

# Get rid of old data that occured during setup.
echo "deleting all database data..."
delete_all_rows "accelerometer_data"
delete_all_rows "altimeter_data"
delete_all_rows "accelerations"
delete_all_rows "data_to_send"
delete_all_rows "trips"
delete_all_rows "bank_trips"


echo "deleting log files..."
sudo rm /home/pi/liftai_logs/*.log


echo "deleting zero-tier identity..."
sudo rm /var/lib/zerotier-one/identity.*


echo "done"
