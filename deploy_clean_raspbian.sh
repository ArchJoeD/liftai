#!/usr/bin/env bash
# Make logfiles and directories:
LOGDIR="/home/pi/liftai_logs/installation_logs"
LOGFILE="$LOGDIR/deploy_clean_raspbian.log"
mkdir -p $LOGDIR

# Redirects output of this script to $LOGFILE. More
# info here: https://serverfault.com/a/103569
exec 3>&1 4>&2
trap 'exec 2>&4 1>&3' 0 1 2 3
exec 1>$LOGFILE 2>&1

#  This script runs automatically whenever there is a software update on the device (something new in github).

parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
config_dir="/etc/liftai"
cd "$parent_path"

dbusername=usr
dbuserpass=pass
dbname=liftaidb
READONLY_USER=readonly

postgres_config_file="/etc/postgresql/9.6/main/postgresql.conf"


echo "=======  LiftAI Software Update Script  ======="
echo "Starting deploy_clean_raspbian at `date`."

echo "ensuring readonly user"
if id "$READONLY_USER" >/dev/null 2>&1; then
    echo "readonly user already exists"
else
    sudo useradd --create-home --shell /bin/bash $READONLY_USER
fi

echo "increasing the TCP timeout for the rest of the day to minimize installation failures..."
sudo bash -c 'echo 12 > /proc/sys/net/ipv4/tcp_syn_retries'

echo "creating any initial directories etc. that need to be created..."
mkdir -p /home/pi/.virtualenvs
mkdir -p /home/pi/.saved_virtualenvs
mkdir -p /home/pi/apps
mkdir -p /home/pi/liftai_logs
mkdir -p /home/pi/liftai_audio
mkdir -p /home/pi/liftai_storage
mkdir -p -m 777 /home/pi/test

echo "making sure we're using UTC time"
sudo timedatectl set-timezone UTC
sudo sed -i -e "s/timezone = 'GB'/timezone = 'UTC'/g" $postgres_config_file

echo "fixing update source list file..."
sudo sed -i 's/archive.raspberrypi.org/raspbian.raspberrypi.org/g' /etc/apt/sources.list

echo "installing main packages..."
sudo pip3 install virtualenv
sudo apt-get install postgresql libpq-dev postgresql-client postgresql-client-common -y

echo "setting up database stuff..."
sudo -u postgres psql -c"create user $dbusername WITH PASSWORD '$dbuserpass'"
sudo -u postgres createdb "$dbname"
sudo -u postgres psql -c"grant all privileges on database $dbname to $dbusername"
sudo -u postgres psql -d liftaidb -a -f ./global_install.sql
sudo -u postgres psql -d liftaidb -a -f ./files/configure-read-access.sql

echo "creating configuration directory and default configuration files if they don't exist..."
# We've seen cases where the config_dir already exists as a file.
if test -f $config_dir; then
    echo "Removing file $config_dir to create directory of the same name"
    sudo rm $config_dir
fi
sudo mkdir -p $config_dir
sudo cp ./files/wpa_supplicant.conf $config_dir/wpa_supplicant.conf
sudo chown root:root $config_dir/wpa_supplicant.conf
sudo chmod 0600 $config_dir/wpa_supplicant.conf
if [ -e $config_dir/config.json ]
then
        echo "config file already exists, doing nothing here"
else
        echo "creating default config file..."
        sudo cp ./files/config.json.default $config_dir/config.json
fi

# Check for router table problem in configuration (needs to be here for legacy devices coming out of inventory)
echo "checking for a one-time routing table issue..."
if grep -q "ifconfig wwan0 down" "/etc/rc.local"; then
	echo "rc.local is already configured to take down wwan0, no changes being made"
else
	sudo sed -i -e 's/exit 0//g' /etc/rc.local
	echo "changing /etc/rc.local to take down wwan0"
	sudo sh -c "echo 'ifconfig wwan0 down' >> /etc/rc.local"
	sudo sh -c "echo 'exit 0' >> /etc/rc.local"
fi

echo "restoring original sshd_config file"
sudo rm /etc/ssh/sshd_config
sudo cp /usr/share/openssh/sshd_config /etc/ssh/sshd_config

echo "ensuring authorized_keys for user pi"
sudo cp ./files/authorized_keys_root /home/pi/.ssh/authorized_keys
sudo chmod 644 /home/pi/.ssh/authorized_keys

echo "ensuring authorized_keys for user readonly"
sudo mkdir -p /home/$READONLY_USER/.ssh
sudo cp ./files/authorized_keys_readonly /home/$READONLY_USER/.ssh/authorized_keys
sudo chown -R $READONLY_USER:$READONLY_USER /home/$READONLY_USER/.ssh
sudo chmod 700 /home/$READONLY_USER/.ssh
sudo chmod 644 /home/$READONLY_USER/.ssh/authorized_keys

echo "installing and upgrading all required packages..."
sudo apt-get update -y --fix-missing
sudo apt-get update -y && sudo apt-get upgrade -y
# install third party dependencies
sudo apt-get install libatlas-base-dev libsndfile-dev python-dev python-pip python3-dev python3-pip portaudio19-dev libffi-dev -y
sudo apt autoremove -y
# jq is needed to parse json configuration and system files
sudo apt-get install jq -y
# For some reason, we can't install bc, which is needed by ./cronjobs/system_check.sh to check system loading.
#sudo apt install bc -y
sudo pip3 install RPi.GPIO

# Ensure we do not have the local python packages folder
rm -rf /home/pi/.local

echo "modifying sshd_config file"
sudo sed -i -e 's/^#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
sudo sed -i 's/^PasswordAuthentication/#PasswordAuthentication/g' /etc/ssh/sshd_config
sudo sh -c 'echo "PasswordAuthentication no" >> /etc/ssh/sshd_config'

echo "stopping as many services as possible to avoid exceptions from pgbouncer setup"
sudo systemctl stop elisha.service
sudo systemctl stop accelerometer.service
sudo systemctl stop altimeter.service
sudo systemctl stop audiorecorder.service
sudo systemctl stop bankstoppage.service
sudo systemctl stop lowusestoppage.service
sudo systemctl stop reportgenerator.service
sudo systemctl stop standalonestoppage.service
sudo systemctl stop trips.service
sudo systemctl stop vibration.service
sudo systemctl stop elevation.service
sudo systemctl stop doors.service
sudo systemctl stop roawatch.service
sudo systemctl stop datasender.service
sudo systemctl stop escalatorstoppage.service
sudo systemctl stop problemdetection.service

echo "setting up pgbouncer which could cause exceptions in our services running"
sudo apt-get install pgbouncer -y
sudo -u postgres psql -c"COPY ( SELECT '\"' || rolname || '\" \"' || rolpassword || '\"' FROM pg_authid WHERE rolname = '$dbusername' ) TO '/etc/pgbouncer/userlist.txt';"
sudo cp -rf ./pgbouncer/pgbouncer.ini /etc/pgbouncer/
sudo systemctl restart pgbouncer
sudo systemctl enable pgbouncer

echo "setting up I2C stuff..."
sudo apt-get install i2c-tools -y
#try to uncomment dtparams first
sudo sed -i 's/#dtparam=i2c1=on/dtparam=i2c1=on/g' /boot/config.txt
sudo sed -i 's/#dtparam=i2c_arm=on/dtparam=i2c_arm=on/g' /boot/config.txt
#add lines if necessary
sudo grep -q -F 'dtparam=i2c1=on' /boot/config.txt || sudo sh -c "echo 'dtparam=i2c1=on' >> /boot/config.txt"
sudo grep -q -F 'dtparam=i2c_arm=on' /boot/config.txt || sudo sh -c "echo 'dtparam=i2c_arm=on' >> /boot/config.txt"
# Set up the real time clock
if grep -q -F "\"rtc\":true" /etc/liftai/hwconfig.json; then
  echo "Setting up real time clock"
  #  https://pimylifeup.com/raspberry-pi-rtc/
  # Step 1 here.  This tells the kernel which driver to use for the hardware clock.
  # The device add-on board has an MCP7940N.
  sudo grep -q -F 'dtoverlay=i2c-rtc,mcp7940x' /boot/config.txt \
            || sudo sh -c "echo 'dtoverlay=i2c-rtc,mcp7940x' >> /boot/config.txt"
  # The fake HW clock is used when a board doesn't have one.  This can interfere with the actual HW clock.
  sudo apt-get -y remove fake-hwclock
  sudo update-rc.d -f fake-hwclock remove
  sudo systemctl stop fake-hwclock.service
  sudo systemctl disable fake-hwclock.service
  sudo apt-get -y purge fake-hwclock
  # Step 6 and 7 from the web page.  Remove more fake HW clock stuff.  Commenting out 3 lines of the script.
  cat /lib/udev/hwclock-set | tr '\n' '\r' | sed -e \
    's/if[[:space:]]*\[[[:space:]]\+-e[[:space:]]\+\/run\/systemd\/system[[:space:]]\+\][[:space:]]*;[[:space:]]*then\r[[:space:]]*exit[[:space:]]\+0\rfi/#if \[ -e \/run\/systemd\/system \] ; then\r#    exit 0\r#fi/' \
| tr '\r' '\n' > /tmp/hwclock-set
  # https://www.raspberrypi.org/forums/viewtopic.php?t=209700
  # This adds a rule beyond the previous steps 6 and 7 to ensure that this works after a system upgrade.
  # If the change hasn't already been done, then append the change to the file.
  sudo grep -q -F "KERNEL==\"rtc0\"" /etc/udev/rules.d/99-com.rules || sudo sh -c "echo 'KERNEL==\"rtc0\", RUN+=\"/sbin/hwclock --rtc=\$root/\$name --hctosys\"' >> /etc/udev/rules.d/99-com.rules"
  sudo mv /tmp/hwclock-set /lib/udev/hwclock-set
  sudo chown root:root /lib/udev/hwclock-set
  sudo chmod 755 /lib/udev/hwclock-set
fi
sudo grep -q -F 'i2c-dev' /etc/modules || sudo sh -c "echo 'i2c-dev' >> /etc/modules"

echo "running deploy.sh for all the LiftAI applications..."
find . -name 'deploy.sh' -exec {} \;

echo "install ZeroTier and set up network"
# modify this variable and set correct network_id
ZEROTIER_NETWORK_ID=c7c8172af124cf72

curl -s 'https://pgp.mit.edu/pks/lookup?op=get&search=0x1657198823E52A61' | gpg --import && \
  if z=$(curl -s 'https://install.zerotier.com/' | gpg);
  then
    echo "$z" | sudo bash;
  fi

sudo systemctl start zerotier-one
sudo zerotier-cli join $ZEROTIER_NETWORK_ID
sudo systemctl stop zerotier-one
sudo touch /var/lib/zerotier-one/networks.d/$ZEROTIER_NETWORK_ID.conf
sudo systemctl disable zerotier-one.service

echo "Done with deploy_clean_raspbian at `date`."
echo "=====  done with LiftAI software installation  ====="
