import logging
import time

from bank_stoppage import constants
from bank_stoppage.processor import BankStoppageProcessor
from utilities import device_configuration
from utilities.logging import create_rotating_log


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("bank_stoppage")
    logger.debug("--- Starting bank stoppage app")

    elevator = device_configuration.DeviceConfiguration.is_elevator(logger)

    try:
        processor = BankStoppageProcessor()
        while True:
            if elevator:
                processor.run()
            time.sleep(constants.PROCESSING_SLEEP_INTERVAL)

    except Exception as e:
        logger.exception("Exception in bank stoppage, {0}".format(str(e)))

if __name__ == "__main__":
    main()
