import argparse
import logging
from time import sleep

import sounddevice as sd

from audio_recorder.audio_rec import AudioRecorder
from utilities.db_utilities import session_scope
from utilities.logging import create_rotating_log
from utilities.device_configuration import DeviceConfiguration


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "-l",
    "--list-devices",
    action="store_true",
    help="show list of audio devices and exit",
)
args = parser.parse_args()


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("audio_recorder")

    if args.list_devices:
        print(sd.query_devices())
        exit(0)

    try:
        with AudioRecorder() as audio_rec, session_scope() as session:
            if DeviceConfiguration.has_hardware_audio_filter():
                logger.debug("--- Starting audio recorder app, start recording")
                audio_rec.start_record_audio()
                while True:
                    audio_rec.process_data(session)
                    session.commit()
            else:
                logger.debug("--- Starting audio recorder app, not recording")
                while True:
                    sleep(5)

    except Exception as e:
        logger.exception("Exception in audio_recorder main(), {0}".format(str(e)))


if __name__ == "__main__":
    main()
