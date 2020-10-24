import logging
import time
import trips.constants as constants
import trips.trip_processor as trip_processor

from utilities.logging import create_rotating_log
from utilities.db_utilities import session_scope
import utilities.device_configuration as device_configuration


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("trips")
    logger.debug("--- Starting trip detection app")

    elevator = device_configuration.DeviceConfiguration.is_elevator(logger)

    try:
        with session_scope() as session:
            tp = trip_processor.TripProcessor(session)
            while True:
                if elevator:
                    tp.look_for_trips()
                    session.commit()
                time.sleep(constants.BATCH_PROCESSING_SLEEP_INTERVAL)
    except Exception as e:
        logger.exception("General exception in trips main()" + str(e))


if __name__ == "__main__":
    main()
