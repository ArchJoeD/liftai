import logging
import time

from floor_detector import constants
from floor_detector.floor_processor import FloorProcessor
from utilities import device_configuration
from utilities.logging import create_rotating_log


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("floor_detector")
    logger.debug("--- Starting floor detector app")

    elevator = device_configuration.DeviceConfiguration.is_elevator(logger)
    try:
        floor_processor = FloorProcessor()
        while True:
            if elevator:
                floor_processor.process_trips()
            time.sleep(constants.DELAY_BETWEEN_EXECUTIONS)
    except Exception as e:
        logger.exception("Exception: " + str(e))


if __name__ == "__main__":
    main()
