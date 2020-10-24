import logging
import time

from standalone_stoppage import constants
from standalone_stoppage.processor import StandaloneStoppageProcessor
from utilities import device_configuration
from utilities.logging import create_rotating_log


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("standalone_stoppage")
    logger.debug("--- Starting standalone stoppage app")

    elevator = device_configuration.DeviceConfiguration.is_elevator(logger)

    try:
        processor = StandaloneStoppageProcessor()
        while True:
            if elevator:
                processor.run()
            time.sleep(constants.PROCESSING_SLEEP_INTERVAL)

    except Exception as e:
        logger.exception("Exception in standalone stoppage: {0}".format(str(e)))


if __name__ == "__main__":
    main()
