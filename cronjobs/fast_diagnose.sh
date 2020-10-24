#!/usr/bin/env bash

# This script can be run very frequently (once every 2 minutes or so) to diagnose problems.
# DO NOT put anything in here that uses network bandwidth or a lot of system resources!!!

status="ok"
# step 1 - check for a router table problem
if netstat -nr | grep '^0.0.0.0' | grep zt5u4thzmd; then
    echo "Detected ZeroTier in default route, fixing the issue"
    sudo route add default dev ppp0
    status="not_ok"
fi

# step 2 - if modem reconnects, it brings up wwan0 which becomes default path, use ppp0
if netstat -nr | grep '^0.0.0.0' | grep wwan0; then
    echo "Detected wwan0 as default route, fixing the issue"
    sudo ifconfig wwan0 down
    sudo poff hologram
    sudo pon hologram
    status="not_ok"
fi

if [ $status == "ok" ]; then
    echo "routing table is ok"
fi


