#!/bin/bash
SCRIPT_RUN_NAME="integration_test_$(date '+%Y-%m-%d_%H:%M:%S')"
SCRIPT_RUN_LOG_FILE="/tmp/$SCRIPT_RUN_NAME.log"
DATA_PATH="/home/pi/";
FATAL_ERROR_LOG_FILE="$DATA_PATH/liftai_logs/script_fatal_errors.log"
GIT_PATH="python-development/";
LATEST_HASH_FILE=$DATA_PATH".integ_latest_hash";

FULL_PATH=$DATA_PATH$GIT_PATH
LATEST_GIT_HASH=$(cd $FULL_PATH; git log --pretty=%H | head -n1)

write_hash() {
    echo "[integ] Writing $LATEST_GIT_HASH to $LATEST_HASH_FILE"
    echo $LATEST_GIT_HASH > $LATEST_HASH_FILE
}

run_system_check() {
    echo "[integ] Starting system check."
    SYSTEM_CHECK_RESULT=$($DATA_PATH"system_check.sh" 2>&1 >> $SCRIPT_RUN_LOG_FILE)
    echo "[integ] System check returned: $?."
    echo "[integ] Check the logs for details: $SCRIPT_RUN_LOG_FILE"
}

run_tests() {
    if [[ ! $(ps -aux | grep deplo[y]) ]]; then
        echo "[integ] Running tests."
        # Write the hash first so we don't have other integration tests running at the same time.
        write_hash
        run_system_check
    else
        echo "[integ] Still deploying. Doing nothing."
        exit 0
    fi
}

update_cronjob() {
    CRON_FILE=/var/spool/cron/crontabs/pi
    # /home/pi/update_integration.sh is a symlink to the regular update file.
    # We do this so the other cron job script doesn't wipe out our cron job.
    UPDATE_LINK_FILE=$DATA_PATH"update_integration.sh"
    if [[ ! -e $UPDATE_LINK_FILE ]]; then
        echo "[integ] Symlinking update.sh to update_integration.sh"
        ln -s $DATA_PATH"update.sh" $UPDATE_LINK_FILE
    fi

    echo "[integ] Writing cron job to run update more frequently."
    sudo sed -i '/update_integration.sh/d' $CRON_FILE
    sudo sh -c "echo '*/5 * * * * /home/pi/update_integration.sh > /tmp/liftai_update.log 2>&1' >> $CRON_FILE"

    echo "[integ] Adding cron job to run this script."
    sudo cp $FULL_PATH"misc_scripts/integration_testing.sh" $DATA_PATH
    sudo sed -i '/integration_testing.sh/d' $CRON_FILE
    sudo sh -c "echo '*/6 * * * * /home/pi/integration_testing.sh > /tmp/liftai_integration_testing.log 2>&1' >> $CRON_FILE"

    echo "[integ] Fixing crontab permissions."
    sudo chown pi:crontab $CRON_FILE
    sudo chmod 600 $CRON_FILE

    echo "[integ] Restarting cron."
    sudo /etc/init.d/cron restart
}

main() {
    echo -e "\n\n***** setup integ. testing script *****"

    pushd $FULL_PATH;
    echo "Operating in: "$FULL_PATH;

    update_cronjob

    if [[ -f $LATEST_HASH_FILE ]]; then
        LAST_CHECK_GIT_HASH=$(cat $LATEST_HASH_FILE)
        if [[ $LATEST_GIT_HASH != $LAST_CHECK_GIT_HASH ]]; then
            echo "[integ] Latest hash is not the last one we saw."
            run_tests
        else
            echo "[integ] Latest hash is the same as the last one we saw."
            echo "[integ] Doing nothing."
        fi
    else
        touch $LATEST_HASH_FILE
        echo "[integ] Latest hash file does not exist."
        run_tests
    fi

    echo "[integ] -fin-"
}

main
