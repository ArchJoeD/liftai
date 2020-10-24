import logging
import time

import utilities.device_configuration as device_configuration
import vibration.constants as constants
import vibration.vibration_processor as vibration_processor
from utilities.logging import create_rotating_log


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("vibration")
    logger.debug("--- Starting vibration detection app")

    elevator = device_configuration.DeviceConfiguration.is_elevator(logger)

    try:
        vp = vibration_processor.VibrationProcessor()
        while True:
            if elevator:
                vp.process_data()
            time.sleep(constants.BATCH_PROCESSING_SLEEP_INTERVAL)

    except Exception as e:
        logger.exception("Exception in vibration: {0}".format(str(e)))


if __name__ == "__main__":
    main()
