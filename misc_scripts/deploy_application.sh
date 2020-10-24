#!/usr/bin/env bash

#  Required arguments:
#       $1 is the name of the service (don't include the .service suffix)
#       $2 is the name of the virtualenv (include the liftai_ prefix)
#       $3 is the name of the git directory for the application
#       It's very unfortunate that all three of these are different in unsystematic ways. :-(
#
#  This does NOT call any .sql files
#  If you need directories created, put them in deploy_clean_raspbian.sh
#
#  This needs to run with the current directory as the application's directory.

# Make logfiles and directories:
LOGDIR="/home/pi/liftai_logs/installation_logs"
LOGFILE="$LOGDIR/$1_installation.log"
mkdir -p $LOGDIR

# Redirects output of this script to $LOGFILE. More
# info here: https://serverfault.com/a/103569
exec 3>&1 4>&2
trap 'exec 2>&4 1>&3' 0 1 2 3
exec 1>$LOGFILE 2>&1

status="pass"

echo -e "\n\n*****  deploying $1 app  *****"
echo "Starting installation at `date`."
PATH=$PATH:/usr/local/bin
VIRTUAL_ENV_DIR=".virtualenvs"
VIRTUAL_ENV_SAVED_DIR=".saved_virtualenvs"
VIRTUAL_ENV_FULL_PATH="/home/pi/$VIRTUAL_ENV_DIR/$2"
VIRTUAL_ENV_SAVED_FULL_PATH="/home/pi/$VIRTUAL_ENV_SAVED_DIR/$2"

echo "stopping any existing $1 service from running..."
sudo systemctl stop $1.service

echo "deleting intermediate build files..."
rm -fr ./build
rm -fr ./dist
rm -fr ./$2.egg-info


delete_flag="do_not_delete_virtualenv"
if [ -f $VIRTUAL_ENV_FULL_PATH/unfinished ]; then
  echo "A flag indicating unfinished install exists, deleting it..."
  # If we're trying again, remove the entire old virtualenv.
  delete_flag="delete"
  rm $VIRTUAL_ENV_FULL_PATH/unfinished
  if [ -z "$(ls -A $VIRTUAL_ENV_FULL_PATH)" ]; then
    echo "The existing code directory is empty, deleting it..."
    rm -fr $VIRTUAL_ENV_FULL_PATH
  fi
fi

if [ -d "$VIRTUAL_ENV_FULL_PATH" ]; then
  echo "copying virtualenv to the saved location..."
  #  To be safe, make sure the saved virtualenv is gone.
  rm -fr $VIRTUAL_ENV_SAVED_FULL_PATH
  cp -r $VIRTUAL_ENV_FULL_PATH $VIRTUAL_ENV_SAVED_FULL_PATH
  #  Delete any older versions in the old virtualenv that we will re-use.
  rm -f $VIRTUAL_ENV_FULL_PATH/lib/python*/site-packages/liftai*.egg
fi

if [ $delete_flag == "delete" ]; then
  echo "since this is a retry, deleting the old virtualenv"
  sudo rm -fr $VIRTUAL_ENV_FULL_PATH
fi

if [ ! -d "$VIRTUAL_ENV_FULL_PATH" ]; then
  echo "virtualenv does not exist, installing a new one: $VIRTUAL_ENV_FULL_PATH"
  virtualenv -p python3 $VIRTUAL_ENV_FULL_PATH
fi

echo "calling activate for virtualenv $1"
source $VIRTUAL_ENV_FULL_PATH/bin/activate

# Install common LiftAI library code into venv
pushd ../utilities/; python3 ./setup.py install; popd
pushd ../notifications/; python3 ./setup.py install; popd
if [ $1 = "trips" ]; then
  pushd ../vibration/; python3 ./setup.py install; popd
fi

echo "installing requirements for $1"
pip3 install -r ./requirements.txt
echo "running setup.py for $1"
python ./setup.py install

echo "copying service file to the OS"
sudo cp ./$1.service /etc/systemd/system/
sudo systemctl daemon-reload

echo "restarting service for $1"
sudo systemctl restart $1.service
echo "waiting several seconds for it to possibly crash"
sleep 6

x=`sudo systemctl status $1.service | grep "Active: active (running)"`

pattern='([4-9])s ago'
[[ $x =~ $pattern ]]
seconds_running="${BASH_REMATCH[1]}"

if [[ ! -z $seconds_running ]]; then
  echo "$1.service ran for $seconds_running seconds successfully, using this deployment"
  sudo systemctl start $1.service
  sudo systemctl enable $1.service

else

  if [ -d "$VIRTUAL_ENV_SAVED_FULL_PATH" ]; then
    status="fail"
    echo "$1.service is not working, falling back to previous version for now"
    rm -fr $VIRTUAL_ENV_FULL_PATH
    mv $VIRTUAL_ENV_SAVED_FULL_PATH $VIRTUAL_ENV_FULL_PATH
    sudo systemctl start $1.service
    sudo systemctl enable $1.service
    echo "Adding a flag to the virtualenv directory to try again later"
    # Later on, a process can scan for these unfinished flags and run the deploy.sh program for each.
    echo "$3" > $VIRTUAL_ENV_FULL_PATH/unfinished

  else
    echo "service failed, but no previous version to fall back to, so keeping the existing failing one, will try again"
    echo "$3" > $VIRTUAL_ENV_FULL_PATH/unfinished
    sudo systemctl start $1.service
    sudo systemctl enable $1.service
  fi

fi

echo "Removing saved virtualenv"
rm -fr $VIRTUAL_ENV_SAVED_FULL_PATH

deactivate

if [ $status = "fail" ]; then
  # If this script returns a non-zero, the caller should NOT do any SQL or other installations/updates.
  # If there was no previous version, it's a "don't care" and we just go ahead with the SQL changes.
  echo "Failed to successfully install at `date`."
  exit 1
fi
echo "Done with $1 app with result $status at `date`."
