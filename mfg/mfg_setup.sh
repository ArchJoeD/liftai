#!/usr/bin/env bash

#  This script is used for setting up a single device which already has a copy of the gold master SD card
#  attached to the board.

echo "Setting up LiftAI system configuration on `date`..."
dev_id=$(cat /etc/hostname)

if [ "$#" -ne 1 ]; then
  echo "You need to specify a SIM provider, such as:  $0 hologram"
  exit 1
fi

if [ "$1" != "twilio" ] && [ "$1" != "hologram" ]; then
  echo "$1 is not a valid SIM provider.  Needs to be either twilio or hologram"
  exit 2
fi


echo "Copying cellular scripts that don't already exist..."
# These come from:  wget https://github.com/twilio/wireless-ppp-scripts/archive/master.zip
sudo cp ../files/ppp_scripts/chatscripts/* /etc/chatscripts
sudo cp ../files/ppp_scripts/peers/* /etc/ppp/peers



echo "Updating /etc/network/interfaces for $1..."
# If this section of code doesn't exist in the interfaces file, add it in...
# TODO: It would be nice to have this in the initial_setup.sh file, but that requires careful coordination.
if cat /etc/network/interfaces | grep EN-239 > /dev/null ;
then
  echo "This device has already been set up with a SIM card provider, removing old text..."
  sudo sed -i '/EN-239/,$d' /etc/network/interfaces
fi
sudo sh -c "cat >> /etc/network/interfaces <<EOL
# EN-239 Jan 22, 2019, default network can get messed up without this.
auto $1
iface $1 inet ppp
   provider $1
EOL"


echo "Creating the correct /etc/rc.local file for SIM provider $1"
sudo cp ../files/rc.local /etc/rc.local
sudo sed -i "s/liftai_sim_provider_replace_this/$1/" /etc/rc.local


echo "NOT copying hardware configuration file to /etc/liftai..."
echo "Done with manufacturing setup for device $dev_id and SIM provider $1"
