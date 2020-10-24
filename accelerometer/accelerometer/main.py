import logging

from accelerometer import SMBusAccelerometer
from accelerometer.db_writer import AccelDbWriter
from accelerometer.models import Base
import accelerometer.constants as constants
from utilities.logging import create_rotating_log
from utilities.db_utilities import engine


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("accelerometer")
    logger.debug("--- Starting accelerometer app")

    try:
        Base.metadata.create_all(engine)
    except Exception:
        logger.exception("Failed to create a new DB table")

    try:
        with SMBusAccelerometer(1) as accelerometer, AccelDbWriter(
            accelerometer
        ) as writer:
            accelerometer.accelerometer_bus_setup()
            accelerometer.detect_and_setup_vertical_axis()

            while True:
                # Process lots of samples before saving them into the database to save cycles.
                xyz_data = []
                for _ in range(constants.MAIN_LOOP_COUNT):
                    hw_data = accelerometer.read_data_from_hw()
                    xyz_data.extend(accelerometer.fifo_data_processor(hw_data))

                writer.write_records(xyz_data)
    except Exception as e:
        logger.exception("General exception in main(), {0}".format(str(e)))


if __name__ == "__main__":
    main()
