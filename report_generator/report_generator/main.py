import logging
import time

import report_generator.constants as constants
from report_generator.generator import RGenerator
from utilities.logging import create_rotating_log
from utilities.db_utilities import session_scope


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("report_generator")
    logger.debug("--- Starting report generator app")

    gen = RGenerator()
    try:
        while True:
            with session_scope() as session:
                gen.generate_reports(session)
            time.sleep(constants.BATCH_PROCESSING_SLEEP_INTERVAL)

    except Exception as e:
        logger.exception("General exception in report generator main()" + str(e))


if __name__ == "__main__":
    main()
