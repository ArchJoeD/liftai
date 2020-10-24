import logging
import time

import elisha.constants as constants
import elisha.elisha_processor as elisha_processor
from utilities.logging import create_rotating_log
from utilities.db_utilities import session_scope

def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("elisha")
    logger.debug("--- Starting elisha app")

    try:
        elisha = elisha_processor.ElishaProcessor()

        with session_scope() as session:
            elisha.setup(session)

        while True:
            with session_scope() as session:
                elisha.process_data(session)
            time.sleep(constants.PROCESSING_SLEEP_INTERVAL)
    except Exception as e:
        logger.exception("Exception caught in elisha main()" + str(e))


if __name__ == "__main__":
    main()
