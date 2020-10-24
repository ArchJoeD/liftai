import logging
import time
from ping_cloud.ping import PingCloud
from utilities.logging import create_rotating_log


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("ping_cloud")
    logger.debug("--- Starting ping cloud app")

    try:
        pc = PingCloud()
        time.sleep(pc.get_random_seconds())     # Randomize the timing of pings from large numbers of devices.
        while True:
            pc.send_ping()
            time.sleep(pc.get_sleep_seconds())
    except Exception as e:
        logger.exception("Exception in ping_cloud: {0}".format(str(e)))
if __name__ == "__main__":
    main()
