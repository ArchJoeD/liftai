from time import sleep
import logging

import elevation.processor as elev
from utilities import device_configuration as device_configuration
from utilities.logging import create_rotating_log
import elevation.constants as constants


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("elevation")

    elevator = device_configuration.DeviceConfiguration.is_elevator(logger)

    try:
        logger.debug("--- Starting elevation app")
        e = elev.ElevationProcessor()
        while True:
            if elevator:
                e.handle_any_gaps()
            sleep(constants.PROCESSING_SLEEP_INTERVAL)
    except Exception as ex:
        logger.error("Exception in elevation: %s" % str(ex))


if __name__ == "__main__":
    main()
