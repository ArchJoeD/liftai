import logging
import os
import signal
import time

import data_sender.constants as constants
from data_sender.datasender import LiftAIDataSender
from notifications.notifications import Notification, NotificationTopic
import utilities.common_constants as common_constants
from utilities.logging import create_rotating_log


def check_uncontrolled_restart():
    if os.path.exists(constants.REBOOT_INFO):
        os.remove(constants.REBOOT_INFO)
        return

    n = Notification()
    n.send(
        NotificationTopic.RESTART_FROM_POWER_LOSS,
        include_last_trip=True,
    )

    logger = logging.getLogger("data_sender")
    logger.info("Detected an uncontrolled restart of the device. Power failure?")


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("data_sender")
    logger.debug("--- Starting data sender app")

    try:
        create_rotating_log("datasent")
        create_rotating_log("datareceived")
        check_uncontrolled_restart()
        datasender = LiftAIDataSender(common_constants.DSN)

        signal.signal(signal.SIGINT, datasender.stop)
        signal.signal(signal.SIGTERM, datasender.stop)

        datasender.run_forever()

    except Exception as e:
        # When stopping, always make it clear this was not an uncontrolled reboot (power failure in elevator).
        reboot_info_file = open(constants.REBOOT_INFO, "w")
        reboot_info_file.write("exception in data_sender main")
        reboot_info_file.close()
        logger.exception("Exception in data_sender, {0}".format(str(e)))
        time.sleep(constants.FAILURE_EXTRA_SLEEP_SECONDS)
        raise


if __name__ == "__main__":
    main()
