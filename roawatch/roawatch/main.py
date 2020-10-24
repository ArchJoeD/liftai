from time import sleep
import logging

from roawatch.watcher import Watcher
import roawatch.constants as roa_constants

from utilities.logging import create_rotating_log
from utilities.db_utilities import session_scope


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("roawatch")
    logger.debug("Starting ROA Watch app")

    try:
        watcher = Watcher()
        roa_was_off = True

        while True:
            with session_scope() as session:
                result = session.execute(
                    "SELECT count(*) FROM roa_watch_requests WHERE"
                    + " request_time > now() - INTERVAL '{0} MINUTES' AND enabled = TRUE".format(
                        roa_constants.MINUTES_BEFORE_AUTO_SHUTOFF
                    )
                ).first()

                if result is not None and result[0] > 0:
                    if roa_was_off:
                        watcher.reset(session)
                        roa_was_off = False
                    watcher.check_for_trips(session)
                else:
                    roa_was_off = True

            sleep(roa_constants.SECONDS_BETWEEN_TRIP_CHECKS)

    except Exception as ex:
        logger.error("Exception: %s" % str(ex))


if __name__ == "__main__":
    main()
