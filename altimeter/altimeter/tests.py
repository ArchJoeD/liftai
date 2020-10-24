import unittest
from datetime import datetime, timedelta
from io import BytesIO
from time import sleep
from unittest.mock import patch, Mock

import altimeter.constants as constants
from altimeter.altim import AltimeterProcessor
from altimeter.db_writer import AltimDbWriter
from utilities import common_constants
from utilities.logging import create_rotating_log
from utilities.device_configuration import DeviceConfiguration
from utilities.db_utilities import AltimeterData, engine, session_scope


class MockAltimWriter:
    @staticmethod
    def write_record(record):
        with session_scope() as session:
            session.add(record)


class AltimeterTesting(unittest.TestCase):
    logger = create_rotating_log("test_gpio")

    def setUp(self):
        self._delete_stuff()

    def tearDown(self):
        self._delete_stuff()

    def _delete_stuff(self):
        with engine.connect() as con:
            con.execute("DELETE FROM altimeter_data")

    def _get_altitude_from_altim_bytes(self, altim_bytes):
        raw_pressure = altim_bytes[1] + (altim_bytes[0] << 8) + (altim_bytes[4] << 16)
        return constants.ALTIMETER_READABILITY_VALUE - (raw_pressure * common_constants.ALTIMETER_SCALE_FACTOR)

    @patch("utilities.floor_detection.DeviceConfiguration.get_hardware_config")
    def test_hw_configuration(self, get_hw_config):
        altim = common_constants.HW_CONFIG_ALTIMETER
        altim2 = common_constants.HW_CONFIG_ALTIMETER2
        hw = common_constants.HW_ALTIMETER_NAME
        self.assertFalse(DeviceConfiguration.has_altimeter(),
                         "No config file should mean no usable altimeter")
        get_hw_config.return_value = {altim2: hw}
        self.assertTrue(DeviceConfiguration.has_altimeter(),
                        "Altimeter we want is typically labelled as altimeter2")
        get_hw_config.return_value = {altim2: "some other altimeter"}
        self.assertFalse(DeviceConfiguration.has_altimeter(),
                         "We only want {0} altimeters".format(common_constants.HW_ALTIMETER_NAME))
        get_hw_config.return_value = {altim2: hw, altim: "some other altimeter"}
        self.assertTrue(DeviceConfiguration.has_altimeter(),
                         "Version 3.2 boards have two altimeters, the one we want is altimeter2")
        get_hw_config.return_value = {altim: hw}
        self.assertTrue(DeviceConfiguration.has_altimeter(),
                         "We should recognize if the altimeter we want is altimeter and not altimeter2")

    def test_data_path(self):
        ap = AltimeterProcessor()
        ap.fw = Mock()
        altim_bytes = b"\x9B\xA3\x09\xBB\x4F\xF3\x0E\xA4\x8C"
        self._run_altimeter_check(ap, altim_bytes)
        sleep(constants.ICP_DELAY_WRITE_TO_READ/1000)
        altim_bytes = b"\x01\xB7\x99\xBC\x4E\x90\xCC\x18\x74"
        self._run_altimeter_check(ap, altim_bytes)
        sleep(constants.ICP_DELAY_WRITE_TO_READ / 1000)

    def _run_altimeter_check(self, ap, altim_bytes):
        altitude = self._get_altitude_from_altim_bytes(altim_bytes)
        # Replace the HW input with a file-like string.
        ap.fr = BytesIO(altim_bytes)
        sample_timestamp = datetime.now()
        ap.sample_timestamp = sample_timestamp
        ap.take_altimeter_reading(MockAltimWriter)
        with engine.connect() as con:
            db_altitude = con.execute("SELECT altitude_x16 FROM altimeter_data ORDER BY id DESC LIMIT 1").first()[0]
        self.assertEqual(altitude, db_altitude)

    @patch("altimeter.altim.AltimeterProcessor.take_altimeter_reading")
    def test_sample_time(self, take_altimeter_reading):
        """
        This tests out the case where everything works normally and sampling is on time.
        """
        ap = AltimeterProcessor()
        # For the first pass, give it some random next_sample_time
        earliest_return_time = datetime.now() + timedelta(milliseconds = constants.ICP_DELAY_WRITE_TO_READ + 100)
        ap.next_sample_time = earliest_return_time
        ap.record_altimeter_sample(MockAltimWriter)
        self.assertGreaterEqual(datetime.now(), earliest_return_time, "We returned too soon, didn't sleep long enough")
        self.assertEqual(ap.next_sample_time, earliest_return_time + timedelta(milliseconds = constants.ALTIMETER_SAMPLE_PERIOD), "Next sample time wasn't exact number of msec after prev time")

    @patch("altimeter.altim.AltimeterProcessor.take_altimeter_reading")
    @patch("altimeter.altim.logging")
    def test_short_sample_time(self, take_altimeter_reading, logging):
        """
        This tests out the case where we fell behind and had to wait beyond the sample time to get
        the sample, which causes clock jitter in the data.  The algorithm should set the next sample time
        to ALTIMETER_SAMPLE_PERIOD after some point during the processing.  It can't be earlier than
        the earliest return time plus ALTIMETER_SAMPLE_PERIOD (we know it got delayed by some amount).
        It can't be later than ALTIMETER_SAMPLE_PERIOD after we returned.
        """
        ap = AltimeterProcessor()
        # For the first pass, give it some random next_sample_time
        earliest_return_time = datetime.now() + timedelta(milliseconds = constants.ICP_DELAY_WRITE_TO_READ)
        ap.next_sample_time = earliest_return_time - timedelta(milliseconds = 80)
        ap.record_altimeter_sample(MockAltimWriter)
        return_time = datetime.now()
        self.assertGreaterEqual(datetime.now(), earliest_return_time, "We returned too soon, didn't sleep long enough")
        self.assertGreaterEqual(ap.next_sample_time,
                         earliest_return_time + timedelta(milliseconds = constants.ALTIMETER_SAMPLE_PERIOD), "Next sample time is too soon")
        self.assertLessEqual(ap.next_sample_time, return_time + timedelta(milliseconds = constants.ALTIMETER_SAMPLE_PERIOD), "Next sample time is too far into the future")

    # We can't effectively test the code that interfaces directly with the hardware.

class AltimeterDbWriterTest(unittest.TestCase):
    def test_write_records_works(self):
        data = {
            "timestamp": datetime.now(),
            "altitude_x16": 1,
            "temperature": 2,
        }

        with AltimDbWriter() as writer:
            record = AltimeterData(**data)
            writer.write_record(record)

        with engine.connect() as con:
            row = con.execute("SELECT * FROM altimeter_data ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(row["timestamp"], data["timestamp"])
            self.assertEqual(row["altitude_x16"], data["altitude_x16"])
            self.assertEqual(row["temperature"], data["temperature"])

if __name__ == "__main__":
    unittest.main()