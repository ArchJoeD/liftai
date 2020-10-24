import logging
import time

from anomaly_detector import constants
from anomaly_detector.acceleration_anomalies import AccelerationAnomalyProcessor
from anomaly_detector.vibration_anomalies import VibrationAnomalyProcessor
from anomaly_detector.misc_anomalies import MiscAnomalyProcessor
from anomaly_detector.gap_detector import GapProcessor
from utilities import device_configuration
from utilities.logging import create_rotating_log


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("anomaly_detector")
    logger.debug("--- Starting anomaly detector app")

    elevator = device_configuration.DeviceConfiguration.is_elevator(logger)

    try:
        accel_processor = AccelerationAnomalyProcessor()
        vib_processor = VibrationAnomalyProcessor()
        misc_processor = MiscAnomalyProcessor()
        gap_detector = GapProcessor()

        while True:
            if elevator:
                accel_processor.check_for_anomalies()
                gap_detector.detect_gaps()          # Quick and cheap so do often
                time.sleep(constants.PROCESSING_SLEEP_INTERVAL)
                vib_processor.check_for_anomalies()
                gap_detector.detect_gaps()
                time.sleep(constants.PROCESSING_SLEEP_INTERVAL)
                misc_processor.check_for_anomalies()
                gap_detector.detect_gaps()
                time.sleep(constants.PROCESSING_SLEEP_INTERVAL)

    except Exception as e:
        logger.exception("Exception: " + str(e))


if __name__ == "__main__":
    main()
