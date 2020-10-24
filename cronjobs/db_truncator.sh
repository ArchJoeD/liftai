#!/usr/bin/env bash

dbname=liftaidb
accel_table=accelerometer_data
altim_table=altimeter_data
audio_table=audio
accelerations_table=accelerations
data_to_send_table=data_to_send
trips_table=trips
bank_trips_table=bank_trips
events_table=events
problems_table=problems
floor_maps_table=floor_maps
roa_watch_table=roa_watch_requests
escalator_table=escalator_vibration
interval_to_del_accel='1 hour'
interval_to_del_altime='4 hours'
interval_to_del_audio='2 hours'
interval_to_del_accelerations='1 year'
interval_to_del_data_to_send='12 hours'
interval_to_del_trips='1 year'
interval_to_del_bank_trips='3 months'
interval_to_del_escalator='3 months'

print_number_of_rows () {
    records_in_table=$(sudo -u postgres psql -qtAX -d $dbname -c "SELECT COUNT(*) FROM $1")
    echo "$(date) - $records_in_table records in table $1"
}

delete_outdated_rows () {
    print_number_of_rows $1
    echo "$(date) exec sql: DELETE FROM $1 WHERE $3 < NOW() - INTERVAL '$2';"
    sudo -u postgres psql -qtAX -d $dbname -c "DELETE FROM $1 WHERE $3 < NOW() - INTERVAL '$2';"
    print_number_of_rows $1
}

keep_10000_rows () {
    print_number_of_rows $1
    sudo -u postgres psql -qtAX -d $dbname -c "DELETE FROM $1 WHERE id < GREATEST((SELECT MAX(id) FROM $1) - 10000,1);"
}

delete_outdated_rows $accel_table "${interval_to_del_accel}" "timestamp"
delete_outdated_rows $altim_table "${interval_to_del_altime}" "timestamp"
delete_outdated_rows $audio_table "${interval_to_del_audio}" "timestamp"
delete_outdated_rows $data_to_send_table "${interval_to_del_data_to_send}" "timestamp"
delete_outdated_rows $trips_table "${interval_to_del_trips}" "start_time"
delete_outdated_rows $accelerations_table "${interval_to_del_accelerations}" "start_time"
delete_outdated_rows $bank_trips_table "${interval_to_del_bank_trips}" "timestamp"
delete_outdated_rows $escalator_table "${interval_to_del_escalator}" "timestamp"
keep_10000_rows $events_table
keep_10000_rows $problems_table
# roa_watch_table doesn't have an id column, so this fails.  Doesn't really need truncation
# keep_10000_rows $roa_watch_table
keep_10000_rows $floor_maps_table

