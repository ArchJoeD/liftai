#!/usr/bin/env bash

result="Pass"
reasons="Reasons: "

echo "Starting LiftAI manufacturing test on `date`, this will take about 1 minute"
sleep 60
declare -a services=(
"accelerometer"
"altimeter"
"audiorecorder"
"bankstoppage"
"datasender"
"elevation"
"elisha"
"escalatorstoppage"
"lowusestoppage"
"reportgenerator"
"pingcloud"
"roawatch"
"standalonestoppage"
"trips"
"vibration"
)

# Test GPIO separately so we can use the LEDs below
gpio_status=`sudo systemctl status gpio | grep "Active:" | grep -v "active (running)"`
if [ ! -z "$gpio_status" ]; then
  result="Fail"
  reasons="service gpio not running, "
fi
# We need to override the normal device GPIO output to show the results of the manufacturing test.
sudo systemctl stop gpio.service

# 16 == red LED, 20 == green LED, 21 == blue LED
sudo sh -c 'echo "16" > /sys/class/gpio/export'
sudo sh -c 'echo "out" > /sys/class/gpio/gpio16/direction'
sudo sh -c 'echo "20" > /sys/class/gpio/export'
sudo sh -c 'echo "out" > /sys/class/gpio/gpio20/direction'
sudo sh -c 'echo "21" > /sys/class/gpio/export'
sudo sh -c 'echo "out" > /sys/class/gpio/gpio21/direction'

# Repeat this several times to make sure we catch problems
for i in $(seq 1 10); do
  echo "Service check $i"
  for s in "${services[@]}"; do
    x=`sudo systemctl status $s | grep "Active:" | grep -v "active (running)"`
    if [ ! -z "$x" ]; then
      result="Fail"
      reasons="$reasons service $s not running on iteration $i, "
    fi
  done
  sudo sh -c 'echo "1" > /sys/class/gpio/gpio21/value'
  sleep 1
  sudo sh -c 'echo "0" > /sys/class/gpio/gpio21/value'
  sleep 1
done

starting_id=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM accelerometer_data ORDER BY id DESC LIMIT 1")
sudo sh -c 'echo "1" > /sys/class/gpio/gpio21/value'
sleep 1s
sudo sh -c 'echo "0" > /sys/class/gpio/gpio21/value'
sleep 1s
ending_id=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM accelerometer_data ORDER BY id DESC LIMIT 1")
if [ $starting_id -eq $ending_id ]; then
    result="Fail"
    reasons="$reasons Accelerometer is not working, "
fi

starting_id=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM altimeter_data ORDER BY id DESC LIMIT 1")
sudo sh -c 'echo "1" > /sys/class/gpio/gpio21/value'
sleep 1s
sudo sh -c 'echo "0" > /sys/class/gpio/gpio21/value'
sleep 1s
ending_id=$(sudo -u postgres psql -qtAX -d liftaidb -c "SELECT id FROM altimeter_data ORDER BY id DESC LIMIT 1")
if [ $starting_id -eq $ending_id ]; then
  result="Fail"
  reasons="$reasons Altimeter is not working"
fi

echo $result

if [ $result == "Pass" ];
then
  echo "Pass!"
  sudo sh -c 'echo "1" > /sys/class/gpio/gpio20/value'
else
  echo $reasons
  sudo sh -c 'echo "1" > /sys/class/gpio/gpio16/value'
fi

sleep 30
/home/pi/periodic_reboot.sh