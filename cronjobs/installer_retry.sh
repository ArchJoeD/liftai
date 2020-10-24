#!/usr/bin/env bash

find /home/pi/.virtualenvs -maxdepth 2 -name "unfinished" | while read line; do eval "/home/pi/python-development/$(cat $line)/deploy.sh"; done
