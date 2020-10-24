#!/usr/bin/env bash

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root and only during manufacturing"
    exit 1
fi

echo "DANGER: THIS WILL DESTROY ALL DATA ON THIS DEVICE $(cat /etc/hostname)!!!"
echo -n "Type the full word 'yes' if you really want to do this: "

read answer

if [ -z $answer ] || [ $answer != "yes" ]; then
    echo -e "\nNo data was deleted\n"
    exit -1
fi

echo "Stopping all services..."
sudo systemctl stop accelerometer
sudo systemctl stop altimeter
sudo systemctl stop reportgenerator
sudo systemctl stop datasender
sudo systemctl disable zerotier-one
sudo rm /var/lib/zerotier-one/identity.*

echo "Deleting trips..."
sudo -u postgres psql -qtAX -d liftaidb -c "delete from trips"
echo "Deleting acclerations..."
sudo -u postgres psql -qtAX -d liftaidb -c "delete from accelerations"
echo "Deleting acclerometer data..."
sudo -u postgres psql -qtAX -d liftaidb -c "delete from accelerometer_data"
echo "Deleting altimeter data..."
sudo -u postgres psql -qtAX -d liftaidb -c "delete from altimeter_data"
echo "Deleting bank trips..."
sudo -u postgres psql -qtAX -d liftaidb -c "delete from bank_trips"
echo "Deleting any data to send..."
sudo -u postgres psql -qtAX -d liftaidb -c "delete from data_to_send"
echo "Deleting any events..."
sudo -u postgres psql -qtAX -d liftaidb -c "delete from events"
echo "Deleting any problems..."
sudo -u postgres psql -qtAX -d liftaidb -c "delete from problems"
echo "Removing logs..."
rm -f /home/pi/liftai_logs/*.log
echo "Removing audio files..."
rm -f /home/pi/liftai_audio/*
echo "Removing state storage data..."
rm -f /home/pi/liftai_storage/*.pkl
echo "removing other logs..."
rm -f /tmp/liftai_*.log
echo "Done removing all data from device"

echo "Setting up script to set hostname on the next reboot (script is idempotent)"
sudo cp /home/pi/hostname_setup.sh /etc/runonce.d

echo ran $0 script at `date` > /home/pi/liftai_logs/manufacturing.log
# Avoid looking like an uncontrolled reboot.
echo "manufacturing cleaning done at `date`" > /home/pi/reboot_info
echo "manufacturing cleaning done at `date`" > /home/pi/liftai_logs/manufacturing.log
