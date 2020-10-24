from time import sleep
import logging

from altimeter.db_writer import AltimDbWriter
from altimeter.altim import AltimeterProcessor
from utilities.logging import create_rotating_log
from utilities.device_configuration import DeviceConfiguration


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("altimeter")
    logger.debug("--- Starting ICP-10100 altimeter app")
    try:
        if not DeviceConfiguration.has_altimeter():
            logger.debug("No usable altimeter on this device, so doing nothing")
            while True:
                sleep(2)  # Sleep a long time to avoid adding load to the system

        altim = AltimeterProcessor()
        if not altim.set_up_altimeter():  # also sets up the first reading
            raise Exception("Hardware problem in setting up altimeter")

        with AltimDbWriter() as writer:
            while True:
                altim.record_altimeter_sample(writer)

    except Exception as e:
        logger.exception("Exception: " + str(e))


if __name__ == "__main__":
    main()
