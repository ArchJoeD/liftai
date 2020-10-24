import logging
import time

from low_use_stoppage import constants
from low_use_stoppage.processor import LowUseStoppageProcessor
from utilities import device_configuration
from utilities.logging import create_rotating_log


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("low_use_stoppage")
    logger.debug("--- Starting low use stoppage app")

    elevator = device_configuration.DeviceConfiguration.is_elevator(logger)

    try:
        processor = LowUseStoppageProcessor()
        counter = constants.INFREQUENT_RUN_COUNT
        while True:
            if elevator:
                processor.frequent_run()
                counter += 1
                if counter >= constants.INFREQUENT_RUN_COUNT:
                    processor.infrequent_run()
                    counter = 0
            time.sleep(constants.PROCESSING_SLEEP_INTERVAL)

    except Exception as e:
        logger.exception("Exception in low use stoppage main()" + str(e))


if __name__ == "__main__":
    main()
