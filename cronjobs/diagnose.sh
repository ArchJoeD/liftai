#!/usr/bin/env bash

#  This script can be run roughly every few hours in order to look for common problems and fix them.

liftai_diagnose_file="/tmp/liftai_diagnose"

ERR_NO_ERROR="the_data_stack_is_working"
ERR_NETWORK="err_network_down"
ERR_PGBOUNCER_NOTRUNNING="err_pgbouncer_not_running"
ERR_DATASENDER_NOTRUNNING="err_datasender_not_running"
ERR_NOTHING_SENT="err_nothing_was_sent"
ERR_REPORT_GENERATOR="err_report_generator"
ERR_PING_DJANGO="err_django_down"

if [ -z ${LIFTAI_URL+"https://prod.liftai.com"} ];
then
    LIFTAI_URL="https://prod.liftai.com"; echo "using default URL $LIFTAI_URL";
else
    echo "using override URL $LIFTAI_URL"; fi

DJANGO_ALIVE_ENDPOINT="$LIFTAI_URL/api/v1/alive"

latest_err=""

isServiceRunning()
{
	service=$1
	if (( $(ps -ef | grep -v grep | grep $service | wc -l) > 0 ))
	then
		echo "Service $service is running."
		return 1
	else
		echo "Service $service is not running."
		return 0
	fi
}

write_latest_error()
{
	err=$1
	echo $1
	echo $err > $liftai_diagnose_file
}

read_latest_error()
{
	if [ ! -f $liftai_diagnose_file ]; then
		echo "nofile"
    	return
	fi

	latest_err=`cat $liftai_diagnose_file`
}

ensure_copied () {
    # Just copies a file to a destination if the target is empty
    # or doesn't exist.
    SYSTEM_FILE=$1
    LOCAL_FILE=$2

    if [ ! -f $1 ] || [ ! -s $1 ]; then
        cp $2 $1
    fi
}

read_latest_error
echo "Previous error was: $latest_err"


# step 1 - check network
echo "Pinging 8.8.8.8"
if ping -q -c 1 -W 1 8.8.8.8 >/dev/null; then
	echo "The network is up"
else
	echo "Restarting networking"
  	sudo systemctl restart networking
  	sleep 2s
  	sudo poff hologram        # TODO: This is assuming we're using Hologram!
  	sleep 5s
  	sudo pon hologram
	write_latest_error $ERR_NETWORK
	exit -1
fi


# The network is up
# step 2 - Check if Django is working
echo "Sending ping messages to Django"
c=1
while [ $c -le 3 ]
do
	sleep 1s

	response=$(curl -i --write-out %{http_code} --silent --output /dev/null "$DJANGO_ALIVE_ENDPOINT")
	echo $response

	if [ $response = 200 ]; then
		echo "Ping $c was successful"
		break
	fi

	echo "Ping $c to Django failed, restarting netorking."
	sudo systemctl restart networking
	(( c++ ))
done

if [ $c -eq 4 ]; then
	echo "Too many attempts failed"
	write_latest_error $ERR_PING_DJANGO
	exit -1
else
	echo "Django responded correctly to our ping message"
fi


# The network is up and Django is working.
# step 3 - check if pgbouncer is running
echo "Checking pgbouncer service"
service="pgbouncer"
isServiceRunning $service
return_code=$?
if [ $return_code -eq 0 ]; then
	echo "Restarting service pgbouncer."
	sudo systemctl restart pgbouncer
	write_latest_error $ERR_PGBOUNCER_NOTRUNNING
	exit -1;
fi


# The network is up, Django is working, and pgbouncer is running.
# step 4 - check if the datasender service is running
echo "Checking data sender service"
service="datasender"
isServiceRunning $service
return_code=$?

if [ $return_code -eq 0 ]; then
	echo "Restarting datasender."
	sudo systemctl restart datasender
	write_latest_error $ERR_DATASENDER_NOTRUNNING
	exit -1;
fi


# The network is up, Django is working, pgbouncer and datasender are running.
# step 5 - check report generator service status
echo "Checking report generator service"
service="reportgenerator"
isServiceRunning $service
return_code=$?

if [ $return_code -eq 0 ]; then
	echo "Restarting service reportgenerator."
	sudo systemctl restart reportgenerator
	write_latest_error $ERR_REPORT_GENERATOR
	exit -1;
fi


# The whole data communications stack is working.
# step 6 - watch if any data is getting sent successfully to Django
last_id1=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM data_to_send WHERE flag=TRUE ORDER BY id DESC LIMIT 1;")
echo "Waiting for 3 minutes to see if any data gets sent"
sleep 182s
last_id2=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM data_to_send WHERE flag=TRUE ORDER BY id DESC LIMIT 1;")

if [ $last_id1 -eq $last_id2 ]; then
	echo "No data was sent during the last 3 minutes even though the whole stack is working?!"
	sudo systemctl restart reportgenerator
	sudo systemctl restart datasender
	sudo systemctl restart pgbouncer
	write_latest_error $ERR_NOTHING_SENT
	exit -1;
else
	write_latest_error $ERR_NO_ERROR
fi

# Check for hologram and PPP stuff
DEV_BASE=/home/pi/python-development/files
CHATSCRIPTS_FILE=/etc/chatscripts/hologram
ensure_copied $CHATSCRIPTS_FILE $DEV_BASE/chatscripts/hologram
chown root:dip $CHATSCRIPTS_FILE
chmod 0644 $CHATSCRIPTS_FILE

PEERS_FILE=/etc/ppp/peers/hologram
ensure_copied $PEERS_FILE $DEV_BASE/ppp_scripts/peers/hologram
chown root:dip $PEERS_FILE
chmod 0644 $PEERS_FILE

echo "diagnostic testing was successful"
exit 0
