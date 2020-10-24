import logging
import time

import escalator_stoppage.constants as constants
from escalator_stoppage.processor import EscalatorStoppageProcessor
import utilities.device_configuration as device_configuration
from utilities.logging import create_rotating_log


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("escalator_stoppage")
    logger.debug("--- Starting escalator stoppage app")

    escalator = device_configuration.DeviceConfiguration.is_escalator(logger)

    try:
        processor = EscalatorStoppageProcessor()
        while True:
            if escalator:
                processor.run()
            time.sleep(constants.PROCESSING_SLEEP_SECONDS)

    except Exception as e:
        logger.exception("General exception in escalator stoppage main()" + str(e))


if __name__ == "__main__":
    main()
