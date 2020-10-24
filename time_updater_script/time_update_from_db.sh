#!/usr/bin/env bash

dbname=liftaidb

time_from_db_string=$(sudo -u postgres psql -qtAX -d $dbname -c "SELECT (pg_last_committed_xact()).timestamp;")
echo "time string from db: $time_from_db_string"
date_from_db=$(date -d "$time_from_db_string" +"%s")
system_date=$(date +"%s")

echo "unix time from db: $date_from_db"
echo "unix time from system: $system_date"

if [[ $date_from_db -gt $system_date ]];
then
    sudo date +"%Y-%m-%d %H:%M:%S.%N+%Z" -s "$time_from_db_string"
else
    echo "no need to update time"
fi

exit
