import os
import unittest
from datetime import datetime, timedelta
from time import sleep
from unittest.mock import Mock

from sqlalchemy import text
from freezegun import freeze_time

import anomaly_detector.constants as constants
from anomaly_detector.gap_detector import GapProcessor
from utilities import common_constants
from utilities.db_utilities import engine
from utilities.test_utilities import TestUtilities


class TestGapDetector(unittest.TestCase):
    testutil = TestUtilities()

    def _delete_data(self):
        storage_file = os.path.join(common_constants.STORAGE_FOLDER, constants.STORAGE_FILE_NAME)
        if os.path.exists(storage_file):
            os.remove(storage_file)
        with engine.connect() as con:
            con.execute("DELETE FROM accelerometer_data;")
            con.execute("DELETE FROM altimeter_data;")
            con.execute("DELETE FROM trips;")  # We need to delete ALL trips
            con.execute("DELETE FROM events;")

    def setUp(self):
        self._delete_data()

    def tearDown(self):
        self._delete_data()

    def get_event_count(self):
        with engine.connect() as con:
            return con.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def verify_event(self, type, subtype, occurred_at):
        self.assertEqual(self.testutil.verify_event(type, subtype, occurred_at), 1)

    def test_last_execution_time_stuff(self):
        start_of_test = datetime.now()
        sleep(.1)
        gd = GapProcessor()
        self.assertGreaterEqual(gd._time_of_last_execution(), start_of_test)
        after_instantiation = datetime.now()
        self.assertLessEqual(gd._time_of_last_execution(), after_instantiation)
        sleep(0.4)
        gd._set_last_execution_time()
        self.assertGreater(
            (gd._time_of_last_execution() - start_of_test).total_seconds(), 0.4
        )
        self.assertLessEqual(gd._time_of_last_execution(), datetime.now())

    def test_create_event(self):
        gd = GapProcessor()
        occurred_at = datetime.now() - timedelta(seconds=12)
        gd._create_event(
            common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP,
            common_constants.EVENT_SUBTYPE_GAP_START,
            occurred_at,
        )
        self.verify_event(
            common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP,
            common_constants.EVENT_SUBTYPE_GAP_START,
            occurred_at,
        )

    def create_sensor_data(self, table, start_time, end_time, interval):
        if table == "altimeter_data":
            field = "altitude_x16"
        else:
            field = "z_data"
        t = start_time
        with engine.connect() as con:
            trans = con.begin()
            while t <= end_time:
                # Need to use format to inject the table name without quotes.
                con.execute(
                    text(
                        "INSERT INTO {0} (timestamp, {1}) "
                        "VALUES (:timestamp, :value)".format(table, field)
                    ),
                    timestamp=t,
                    value=42,
                )
                t = t + interval
            trans.commit()

    def create_gap(self, table, start_time, end_time):
        with engine.connect() as con:
            query = text(
                "DELETE FROM {0} WHERE timestamp > :start_time AND timestamp < :end_time".format(
                    table
                )
            )
            con.execute(query, start_time=start_time, end_time=end_time)

    def test_update_gap_status_no_events(self):
        gd = GapProcessor()
        self.assertTrue(gd.is_sensor_running[constants.ACCELEROMETER_TABLE])
        self.assertTrue(gd.is_sensor_running[constants.ALTIMETER_TABLE])
        gd._update_gap_status()
        self.assertTrue(gd.is_sensor_running[constants.ACCELEROMETER_TABLE])
        self.assertTrue(gd.is_sensor_running[constants.ALTIMETER_TABLE])

    def test_update_gap_status_gap_ended(self):
        gd = GapProcessor()
        gd._create_event(
            common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP,
            common_constants.EVENT_SUBTYPE_GAP_END,
            datetime.now() - timedelta(seconds=5),
        )
        gd._update_gap_status()
        self.assertTrue(gd.is_sensor_running[constants.ACCELEROMETER_TABLE])
        self.assertTrue(gd.is_sensor_running[constants.ALTIMETER_TABLE])

    def test_update_gap_status_gap_started(self):
        gd = GapProcessor()
        gd._create_event(
            common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP,
            common_constants.EVENT_SUBTYPE_GAP_START,
            datetime.now() - timedelta(days=45),
        )
        gd._update_gap_status()
        self.assertTrue(gd.is_sensor_running[constants.ACCELEROMETER_TABLE])
        self.assertFalse(gd.is_sensor_running[constants.ALTIMETER_TABLE])

    def test_update_gap_status_multiple_gaps(self):
        gd = GapProcessor()
        gd._create_event(
            common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP,
            common_constants.EVENT_SUBTYPE_GAP_START,
            datetime.now() - timedelta(days=45),
        )
        gd._create_event(
            common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP,
            common_constants.EVENT_SUBTYPE_GAP_END,
            datetime.now() - timedelta(days=20),
        )
        gd._create_event(
            common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP,
            common_constants.EVENT_SUBTYPE_GAP_END,
            datetime.now() - timedelta(days=30),
        )
        gd._create_event(
            common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP,
            common_constants.EVENT_SUBTYPE_GAP_START,
            datetime.now() - timedelta(days=29),
        )
        gd._update_gap_status()
        self.assertFalse(gd.is_sensor_running[constants.ACCELEROMETER_TABLE])
        self.assertTrue(gd.is_sensor_running[constants.ALTIMETER_TABLE])

    def test_creating_sensor_data(self):
        tables = ("altimeter_data", "accelerometer_data")
        for table in tables:
            end_time = datetime.now()
            start_time = end_time - timedelta(seconds=60)
            self.create_sensor_data(table, start_time, end_time, timedelta(seconds=0.5))
            with engine.connect() as con:
                # Need to use format to inject the table name without quotes.
                query = "SELECT COUNT(*) as count, MIN(timestamp) as start, MAX(timestamp) AS end FROM {0}"
                row = con.execute(query.format(table)).fetchone()
            self.assertGreaterEqual(row["count"], 120, "Using table {0}".format(table))
            self.assertLessEqual(row["count"], 122, "Using table {0}".format(table))
            self.assertEqual(row["start"], start_time, "Using table {0}".format(table))
            self.assertAlmostEqual(
                row["end"], end_time, "Using table {0}".format(table)
            )

    def test_nearly_gap_altimeter(self):
        self.run_nearly_gap(constants.ALTIMETER_TABLE)

    def test_nearly_gap_accelerometer(self):
        self.run_nearly_gap(constants.ACCELEROMETER_TABLE)

    def run_nearly_gap(self, sensor_table):
        seconds_of_data = 16
        end_time = datetime.now()
        start_time = end_time - timedelta(seconds=seconds_of_data)
        self.create_sensor_data(
            sensor_table,
            start_time - timedelta(seconds=4),
            end_time,
            timedelta(seconds=0.5),
        )
        start_of_gap = start_time + timedelta(seconds=(seconds_of_data >> 1))
        self.create_gap(
            sensor_table, start_of_gap, start_of_gap + timedelta(seconds=1.4)
        )
        gd = GapProcessor()
        gd._check_for_gaps(sensor_table, start_time)
        self.assertEqual(self.get_event_count(), 0)

    def test_starting_gap_altimeter(self):
        self.run_starting_gap(constants.ALTIMETER_TABLE)

    def test_starting_gap_accelerometer(self):
        self.run_starting_gap(constants.ACCELEROMETER_TABLE)

    def run_starting_gap(self, sensor_table):
        seconds_of_data = 25
        end_time = datetime.now()
        start_time = end_time - timedelta(seconds=seconds_of_data)
        self.create_sensor_data(
            sensor_table,
            start_time + timedelta(seconds=10),
            end_time,
            timedelta(seconds=0.5),
        )
        gd = GapProcessor()
        gd._check_for_gaps(sensor_table, start_time)
        self.assertEqual(self.get_event_count(), 2)
        self.verify_event(
            GapProcessor.get_event_type(sensor_table),
            common_constants.EVENT_SUBTYPE_GAP_START,
            start_time - timedelta(seconds=2),
        )
        self.verify_event(
            GapProcessor.get_event_type(sensor_table),
            common_constants.EVENT_SUBTYPE_GAP_END,
            start_time + timedelta(seconds=10),
        )

    def test_ending_gap_altimeter(self):
        self.run_ending_gap(constants.ALTIMETER_TABLE)

    def test_ending_gap_accelerometer(self):
        self.run_ending_gap(constants.ACCELEROMETER_TABLE)

    def run_ending_gap(self, sensor_table):
        seconds_of_data = 25
        end_time = datetime.now()
        start_time = end_time - timedelta(seconds=seconds_of_data)
        self.create_sensor_data(
            sensor_table,
            start_time - timedelta(seconds=4),
            end_time - timedelta(seconds=3),
            timedelta(seconds=0.5),
        )
        gd = GapProcessor()
        gd._check_for_gaps(sensor_table, start_time)
        self.assertEqual(self.get_event_count(), 1)
        self.verify_event(
            GapProcessor.get_event_type(sensor_table),
            common_constants.EVENT_SUBTYPE_GAP_START,
            end_time - timedelta(seconds=3),
        )

    def test_long_gap_altimeter(self):
        self.run_long_gap(constants.ALTIMETER_TABLE)

    def test_long_gap_accelerometer(self):
        self.run_long_gap(constants.ACCELEROMETER_TABLE)

    def run_long_gap(self, sensor_table):
        seconds_of_data = 120
        end_time = datetime.now()
        start_time = end_time - timedelta(seconds=seconds_of_data)
        self.create_sensor_data(
            sensor_table,
            start_time - timedelta(seconds=4),
            end_time + timedelta(seconds=3),
            timedelta(seconds=0.5),
        )
        start_of_gap = start_time + timedelta(seconds=7)
        end_of_gap = end_time - timedelta(seconds=7)
        self.create_gap(sensor_table, start_of_gap, end_of_gap)
        gd = GapProcessor()
        gd._check_for_gaps(sensor_table, start_time)
        self.assertEqual(self.get_event_count(), 2)
        self.verify_event(
            GapProcessor.get_event_type(sensor_table),
            common_constants.EVENT_SUBTYPE_GAP_START,
            start_of_gap,
        )
        self.verify_event(
            GapProcessor.get_event_type(sensor_table),
            common_constants.EVENT_SUBTYPE_GAP_END,
            end_of_gap,
        )

    def test_multiple_gaps_altimeter(self):
        self.run_multiple_gaps(constants.ALTIMETER_TABLE)

    def test_multiple_gaps_accelerometer(self):
        self.run_multiple_gaps(constants.ACCELEROMETER_TABLE)

    def run_multiple_gaps(self, sensor_table):
        seconds_of_data = 180
        end_time = datetime.now()
        start_time = end_time - timedelta(seconds=seconds_of_data)
        self.create_sensor_data(
            sensor_table,
            start_time - timedelta(seconds=4),
            end_time + timedelta(seconds=3),
            timedelta(seconds=0.5),
        )
        t = start_time + timedelta(seconds=15)
        gaps = []
        n_gaps = 4
        for _ in range(n_gaps):
            gap_end = t + timedelta(seconds=3)
            gaps.append((t, gap_end))
            self.create_gap(sensor_table, t, gap_end)
            t += timedelta(seconds=10)
        gd = GapProcessor()
        gd._check_for_gaps(sensor_table, start_time)
        self.assertEqual(self.get_event_count(), 2 * n_gaps)
        for gap in range(n_gaps):
            gap_start, gap_end = gaps[gap]
            self.verify_event(
                GapProcessor.get_event_type(sensor_table),
                common_constants.EVENT_SUBTYPE_GAP_START,
                gap_start,
            )
            self.verify_event(
                GapProcessor.get_event_type(sensor_table),
                common_constants.EVENT_SUBTYPE_GAP_END,
                gap_end,
            )

    def run_multiple_windows_of_normal_data_altimeter(self):
        self.run_multiple_windows_of_normal_data(constants.ALTIMETER_TABLE)

    def run_multiple_windows_of_normal_data_accelerometer(self):
        self.run_multiple_windows_of_normal_data(constants.ACCELEROMETER_TABLE)

    def run_multiple_windows_of_normal_data(self, sensor_table):
        end_of_test_window = datetime.now()
        start_of_window = end_of_test_window - timedelta(seconds=120)
        end_of_window = start_of_window + timedelta(seconds=20)
        self.create_sensor_data(
            sensor_table,
            start_of_window - timedelta(seconds=3),
            end_of_test_window,
            timedelta(seconds=0.5),
        )
        gd = GapProcessor()
        while end_of_window <= end_of_test_window:
            mock = Mock()
            mock.return_value = start_of_window
            gd._time_of_last_execution = mock
            freezer = freeze_time(end_of_window.strftime("%Y-%m-%d %H:%M:%S"))
            freezer.start()
            gd._check_for_gaps(sensor_table, start_of_window)
            self.assertEqual(self.get_event_count(), 0)
            self.assertTrue(gd.is_sensor_running[sensor_table])
            freezer.stop()
            start_of_window += timedelta(seconds=20)
            end_of_window = start_of_window + timedelta(seconds=20)

    def test_altim_multiple_windows_of_normal_data_altimeter(self):
        self.run_multiple_windows(constants.ALTIMETER_TABLE)

    def test_altim_multiple_windows_of_normal_data_accelerometer(self):
        self.run_multiple_windows(constants.ACCELEROMETER_TABLE)

    def test_altim_multiple_windows_of_no_data_altimeter(self):
        self.run_multiple_windows(constants.ALTIMETER_TABLE, with_data=False)

    def test_altim_multiple_windows_of_no_data_accelerometer(self):
        self.run_multiple_windows(constants.ACCELEROMETER_TABLE, with_data=False)

    def run_multiple_windows(self, sensor_table, with_data=True):
        end_of_test_window = datetime.now()
        start_of_window = end_of_test_window - timedelta(seconds=120)
        end_of_window = start_of_window + timedelta(seconds=20)
        if with_data:
            self.create_sensor_data(
                sensor_table,
                start_of_window - timedelta(seconds=3),
                end_of_test_window,
                timedelta(seconds=0.5),
            )
            test_type = "normal data"
            expected_events = 0
        else:
            test_type = "no data"
            expected_events = 1
        gd = GapProcessor()
        while end_of_window <= end_of_test_window:
            mock = Mock()
            mock.return_value = start_of_window
            gd._time_of_last_execution = mock
            freezer = freeze_time(end_of_window.strftime("%Y-%m-%d %H:%M:%S"))
            freezer.start()
            gd._check_for_gaps(sensor_table, start_of_window)
            self.assertEqual(self.get_event_count(), expected_events, test_type)
            if sensor_table == constants.ALTIMETER_TABLE:
                self.assertEqual(
                    gd.is_sensor_running[sensor_table], with_data, test_type
                )
            elif sensor_table == constants.ACCELEROMETER_TABLE:
                self.assertEqual(
                    gd.is_sensor_running[sensor_table], with_data, test_type
                )
            else:
                raise Exception("Unsupported sensor table: {0}".format(sensor_table))
            freezer.stop()
            start_of_window += timedelta(seconds=20)
            end_of_window = start_of_window + timedelta(seconds=20)

    def test_multiple_windows_gap_at_start_altimeter(self):
        self.run_multiple_windows_gap_at_start(constants.ALTIMETER_TABLE)

    def test_multiple_windows_gap_at_start_accelerometer(self):
        self.run_multiple_windows_gap_at_start(constants.ACCELEROMETER_TABLE)

    def run_multiple_windows_gap_at_start(self, sensor_table):
        end_of_test_window = datetime.now()
        start_of_window = end_of_test_window - timedelta(seconds=120)
        end_of_window = start_of_window + timedelta(seconds=20)
        start_of_gap = datetime.now() - timedelta(minutes=10)
        end_of_gap = start_of_window + timedelta(seconds=42)
        self.create_sensor_data(
            sensor_table, end_of_gap, end_of_test_window, timedelta(seconds=0.5)
        )
        # Start out with an existing gap start event
        gd = GapProcessor()
        gd._create_event(
            GapProcessor.get_event_type(sensor_table),
            common_constants.EVENT_SUBTYPE_GAP_START,
            start_of_gap,
        )
        gd._update_gap_status()
        self.assertFalse(gd.is_sensor_running[sensor_table], "Problem in test setup")
        while end_of_window <= end_of_test_window:
            mock = Mock()
            mock.return_value = start_of_window
            gd._time_of_last_execution = mock
            freezer = freeze_time(end_of_window.strftime("%Y-%m-%d %H:%M:%S"))
            freezer.start()
            gd._check_for_gaps(sensor_table, start_of_window)
            if start_of_window < end_of_gap < end_of_window:
                # We should have detected the end of the gap here
                self.verify_event(
                    GapProcessor.get_event_type(sensor_table),
                    common_constants.EVENT_SUBTYPE_GAP_END,
                    end_of_gap,
                )
            elif end_of_window < end_of_gap:
                self.assertEqual(
                    self.get_event_count(),
                    1,
                    "We should only have the gap start event at this early point",
                )
            else:
                self.assertEqual(
                    self.get_event_count(),
                    2,
                    "We should only have the gap start and end events at this point",
                )
            freezer.stop()
            start_of_window += timedelta(seconds=20)
            end_of_window = start_of_window + timedelta(seconds=20)

    def test_multiple_windows_gap_at_end_altimeter(self):
        self.run_multiple_windows_gap_at_end(constants.ALTIMETER_TABLE)

    def test_multiple_windows_gap_at_end_accelerometer(self):
        self.run_multiple_windows_gap_at_end(constants.ACCELEROMETER_TABLE)

    def run_multiple_windows_gap_at_end(self, sensor_table):
        end_of_test_window = datetime.now()
        start_of_window = end_of_test_window - timedelta(seconds=120)
        end_of_window = start_of_window + timedelta(seconds=20)
        start_of_gap = end_of_test_window - timedelta(seconds=8)
        end_of_gap = end_of_test_window + timedelta(
            seconds=2
        )  # Make sure to leave no data at the end.
        self.create_sensor_data(
            sensor_table,
            start_of_window - timedelta(seconds=3),
            start_of_gap,
            timedelta(seconds=0.5),
        )
        # Start out with an existing gap end event that happened minutes ago.
        gd = GapProcessor()
        gd._create_event(
            GapProcessor.get_event_type(sensor_table),
            common_constants.EVENT_SUBTYPE_GAP_END,
            start_of_window - timedelta(minutes=5),
        )
        # Add a gap start event on the other sensor table to make sure we don't get them mixed up.
        other_sensor_table = (
            constants.ACCELEROMETER_TABLE
            if sensor_table == constants.ALTIMETER_TABLE
            else constants.ALTIMETER_TABLE
        )
        gd._create_event(
            GapProcessor.get_event_type(other_sensor_table),
            common_constants.EVENT_SUBTYPE_GAP_START,
            start_of_window - timedelta(minutes=5),
        )
        gd._update_gap_status()
        self.assertTrue(gd.is_sensor_running[sensor_table], "Problem in test setup")
        while end_of_window <= end_of_test_window:
            mock = Mock()
            mock.return_value = start_of_window
            gd._time_of_last_execution = mock
            freezer = freeze_time(end_of_window.strftime("%Y-%m-%d %H:%M:%S"))
            freezer.start()
            gd._check_for_gaps(sensor_table, start_of_window)
            if start_of_window < end_of_gap < end_of_window:
                # We should have detected the start of the gap here
                self.verify_event(
                    GapProcessor.get_event_type(sensor_table),
                    common_constants.EVENT_SUBTYPE_GAP_START,
                    start_of_gap,
                )
            elif end_of_window < start_of_gap:
                self.assertEqual(
                    self.get_event_count(),
                    2,
                    "We should only have the two events at this early point",
                )
            freezer.stop()
            start_of_window += timedelta(seconds=20)
            end_of_window = start_of_window + timedelta(seconds=20)

    def test_sanity_counter(self):
        sensor_table = constants.ALTIMETER_TABLE
        end_of_test_window = datetime.now()
        start_of_window = end_of_test_window - timedelta(seconds=120)
        # Space the sensor samples out to create a large number of consecutive gaps.
        self.create_sensor_data(
            sensor_table,
            start_of_window - timedelta(seconds=3),
            end_of_test_window,
            timedelta(seconds=constants.MIN_GAP_SIZE + 0.1),
        )
        gd = GapProcessor()
        mock = Mock()
        mock.return_value = start_of_window
        gd._time_of_last_execution = mock
        with self.assertRaisesRegex(Exception, "Too many gaps*"):
            gd._check_for_gaps(sensor_table, start_of_window)
            self.assertGreater(self.get_event_count(), 10)


if __name__ == "__main__":
    unittest.main()
