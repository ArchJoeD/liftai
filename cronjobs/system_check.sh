#!/bin/bash

echo -e "\nRunning $0 at `date`"

# This function sends a system notification to Django via the existing python based system on the device.
# First argument is text of notification, 2nd argument is priority.
notify () {
  id=$(cat /etc/hostname)
  when=$(date --iso-8601=seconds)
  priority=$2
  payload="'{\"id\": \"$id\", \"type\": \"system_notification\", \"text\": \"$1\", \"priority\": $priority, \"date\": \"$when\"}'"
  sudo -u postgres psql -qtAX -d liftaidb -c "INSERT INTO data_to_send (timestamp, endpoint, payload, flag, resend) VALUES ('$when', 'devices/track', $payload, False, True)"
}

today=`date +%Y-%m-%d`
result=0

declare -a services=(
"accelerometer"
"altimeter"
"anomalydetector"
"audiorecorder"
"bankstoppage"
"datasender"
"elevation"
"elisha"
"floordetector"
"gpio"
"lowusestoppage"
"reportgenerator"
"pingcloud"
"roawatch"
"standalonestoppage"
"trips"
"vibration"
)

for s in ${services[@]}; do
  x=`sudo systemctl status $s | grep "Active:" | grep -v "active (running)"`
  if [ ! -z "$x" ]; then
    echo "Service $s is not running"
    notify "Service $s is not running" "7"
    result=1
  fi
done

echo -e "Log file issues"
for logfile in /home/pi/liftai_logs/*.log
do
        count=$(cat $logfile \
          | grep -e "$today" \
          | grep -e "WARNING" -e "ERROR" -e "CRITICAL" -e "EXCEPTION" \
          | grep -v psycopg2.OperationalError \
          | wc -l)
        if [ $count -gt 0 ]
        then
            echo "  Sending notification for $count problem(s) in $logfile"
            notify "$logfile has $count problems today" "5"
            result=1
        else
            echo "  $logfile is ok today, $today"
        fi
done

for unfinished_file in `find /home/pi/.virtualenvs -maxdepth 2 -name 'unfinished' | grep -Po '^(.*)\/\K(.*)(?=\/unfinished)'`
do
        echo "  Sending notification for unfinished install of $unfinished_file"
        notify "$unfinished_file failed installation" "4"
        result=1
done


#  TODO: Can't check system loading because the "bc" package won't install on some/most devices.
#
#echo "Checking system loading"
#if [ `uptime | sed -r 's/.*average:\s([0-9]*.[0-9]*),\s([0-9]*.[0-9]*),\s([0-9]*.[0-9]*)/\3 > 3.0/g' | bc` -eq 1 ]
#then
#    echo "Too much loading in the system"
#    uptext=`uptime | sed -r 's/.*users,\s*(load average*)/\1/g'`
#    notify "The CPU is overloaded, $uptext" "5"
#else
#    echo "Load level is good"
#fi


SERVICE_OVERRIDE=/etc/systemd/system/datasender.service.d/override.conf
if [ -f $SERVICE_OVERRIDE ] && grep 'devicetest' $SERVICE_OVERRIDE > /dev/null; then
  echo -e "\nWARNING: Using the test cloud URL!!!"
  notify "This device is using the test cloud URL" "5"
  result=1
else
  echo -e "\nUsing default cloud URL"
fi

starting_id=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM accelerometer_data ORDER BY id DESC LIMIT 1")
sleep 2s
ending_id=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM accelerometer_data ORDER BY id DESC LIMIT 1")
if [ $starting_id -eq $ending_id ]; then
    echo -e "\nFAIL: Accelerometer is not working!!"
    notify "The accelerometer is not working on this device, hardware error" "7"
    result=1
else
    echo -e "\nAccelerometer is working"
fi

HW_CONFIG_FILE=/etc/liftai/hwconfig.json
if [ -f  $HW_CONFIG_FILE ] && grep "ICP-10100" $HW_CONFIG_FILE > /dev/null; then
  starting_id=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM altimeter_data ORDER BY id DESC LIMIT 1")
  sleep 2s
  ending_id=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM altimeter_data ORDER BY id DESC LIMIT 1")
  if [ $starting_id -eq $ending_id ]; then
      echo -e "\nFAIL: Altimeter is not working."
      notify "The altimeter is not working on this device, hardware error" "5"
      result=1
  else
      echo -e "\nAltimeter is working"
  fi
else
    echo "Older altimeter in this device"
fi

t=$(/opt/vc/bin/vcgencmd measure_temp | grep -oP '=\K([0-9]+)')
if (( $t > 70 )) ; then
    echo -e "\nTemperature is too hot at $t degrees C"
    notify "The CPU is running too hot at $t degrees C" "5"
    result=1
else
    echo -e "\nTemperature is a cool $t degrees C"
fi

if grep -q -F "\"rtc\":true" /etc/liftai/hwconfig.json && grep -q -F 'dtoverlay=i2c-rtc,mcp7940x' /boot/config.txt \
          && sudo i2cdetect -y 1 | grep -q UU; then
    echo "RTC is working"
else
    if grep -q -F "\"rtc\":true" /etc/liftai/hwconfig.json; then
        echo -e "\nReal time clock is not working"
        notify "The real time clock is not working" "4"
    else
        echo -e "\nThis device doesn't have a real time clock (older HW)"
    fi
fi


pushd /home/pi/python-development
if git status | grep master; then
  echo "on master branch"
else
  echo "not on master branch"
  notify "This device is not running on the master branch of git" "7"
  result=1
fi
popd

echo "Done running $0"
exit $result
