#! /bin/bash

# Get rid of the first leading '1' (if any) and then any leading zeros after it.
hname=$(cat /proc/cpuinfo | grep Serial | sed -r 's/Serial\s+:\s//' | sed -z 's/\\n//' | sed 's/^1//' | sed 's/^0*//')
sudo echo $hname > /etc/hostname
sudo cat /etc/hosts | sed "s/raspberrypi/$hname/" > /tmp/$hname
sudo cat /tmp/$hname > /etc/hosts
sudo hostnamectl set-hostname $hname
sudo systemctl restart avahi-daemon
