#!/bin/bash

echo -e "\n===============" `cat /etc/hostname`

result="Pass!" # See below for actual result
declare -a services=(
"accelerometer"
"altimeter"
"anomalydetector"
"audiorecorder"
"bankstoppage"
"datasender"
"elevation"
"elisha"
"escalatorstoppage"
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

echo -e "\nHow long each service has run:"
for s in "${services[@]}"; do
  y=`sudo systemctl status $s | grep "Active:" | sed -n 's/^.*\(GMT\|UTC\);\s\(.*\)$/\2/p'`
  echo -e "    $y\t$s"
  x=`sudo systemctl status $s | grep "Active:" | grep -v "active (running)"`
  if [ ! -z "$x" ]; then
    if [ "$result" == "Pass!" ]; then
      result="Fail, not working: $s"
    else
      result="$result, $s"
    fi
  fi
done

echo -e "\nDate of install for all egg files:"
ls -l /home/pi/.virtualenvs/liftai_*/lib/python3.5/site-packages/liftai*.egg | \
   sed -n 's/^.*\([JFMASOND][aepuco][nbrylgptvc]\s\{1,\}[0-9]\{1,2\}\).*liftai_\(.*\)\/lib.*packages\/\(.*.egg\).*$/    \1   \2\t\3/p'

echo -e "\nAll services running test: $result"
declare -a logfiles=("accelerometer"
                "altimeter"
                "audio_recorder"
                "anomaly_detector"
                "bank_stoppage"
                "data_sender"
                "datasent"
                "elevation"
                "elisha"
                "escalator_stoppage"
                "floor_detector"
                "gpio"
                "low_use_stoppage"
                "ping_cloud"
                "report_generator"
                "roawatch"
                "standalone_stoppage"
                "trips"
                "vibration"
                )

three_days_ago=`date -d "72 hours ago" +%Y-%m-%d`
two_days_ago=`date -d "48 hours ago" +%Y-%m-%d`
yesterday=`date -d "24 hours ago" +%Y-%m-%d`
today=`date +%Y-%m-%d`

echo -e "\n\nImportant log file details:"
for logfile in "${logfiles[@]}"
do
        echo -e "\n$logfile recent significant log entries"
        cat /home/pi/liftai_logs/$logfile.log \
          | grep -e "$today" -e "$yesterday" -e "$two_days_ago" -e "$three_days_ago" \
          | grep -e "INFO" -e "WARNING" -e "ERROR" -e "CRITICAL" -e "EXCEPTION" \
          | grep -v psycopg2.OperationalError \
          | tail -n 20
done

echo -e "\nuptime:"
uptime

SERVICE_OVERRIDE=/etc/systemd/system/datasender.service.d/override.conf
if [ -f $SERVICE_OVERRIDE ] && grep 'devicetest' $SERVICE_OVERRIDE > /dev/null; then
  echo -e "\nWARNING: Using the test cloud URL!!!"
else
  echo -e "\nUsing default cloud URL"
fi

starting_id=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM accelerometer_data ORDER BY id DESC LIMIT 1")
sleep 2s
ending_id=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM accelerometer_data ORDER BY id DESC LIMIT 1")
if [ "$starting_id" -eq "$ending_id" ]; then
    echo -e "\nFAIL: Accelerometer is not working!!"
else
    echo -e "\nAccelerometer is working"
fi

HW_CONFIG_FILE=/etc/liftai/hwconfig.json
if [ -f  $HW_CONFIG_FILE ] && grep "ICP-10100" $HW_CONFIG_FILE > /dev/null; then
    starting_id=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM altimeter_data ORDER BY id DESC LIMIT 1")
  sleep 2s
  ending_id=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM altimeter_data ORDER BY id DESC LIMIT 1")
  if [ "$starting_id" -eq "$ending_id" ]; then
      echo -e "\nFAIL: Altimeter is not working. Check wiring."
  else
      echo -e "\nAltimeter is working"
  fi
else
    echo "Older altimeter in this device"
fi

t=$(/opt/vc/bin/vcgencmd measure_temp | grep -oP '=\K([0-9]+)')
if (( $t > 66 )) ; then
    echo -e "\nTemperature is too hot at $t degrees C"
else
    echo -e "\nTemperature is a cool $t degrees C"
fi

if grep -q -F "\"rtc\":true" /etc/liftai/hwconfig.json && grep -q -F 'dtoverlay=i2c-rtc,mcp7940x' /boot/config.txt \
          && sudo i2cdetect -y 1 | grep -q UU; then
    echo -e "\nReal time clock is working"
else
    if grep -q -F "\"rtc\":true" /etc/liftai/hwconfig.json; then
        echo -e "\nReal time clock is not working"
    else
        echo -e "\nThis device doesn't have a real time clock (older HW)"
    fi
fi

echo -e "\nConfiguration:"
CONFIG_FILE=/etc/liftai/config.json
cat $CONFIG_FILE

echo -e "\nHardware configuration:"
cat $HW_CONFIG_FILE

echo -e "\ngit status result"
git status

for unfinished_file in `find /home/pi/.virtualenvs -maxdepth 2 -name 'unfinished' | grep -Po '^(.*)\/\K(.*)(?=\/unfinished)'`
do
        echo -e "\n$unfinished_file failed to install"
done
