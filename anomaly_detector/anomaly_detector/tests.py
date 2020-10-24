from datetime import datetime, timedelta
import os
import unittest

from accelerometer.models import Base
from anomaly_detector.acceleration_anomalies import AccelerationAnomalyProcessor
from utilities import common_constants
from utilities.db_utilities import engine
from utilities.test_utilities import TestUtilities
import anomaly_detector.constants as constants


outlier_level = constants.RELEVELING_AMPLITUDE_MIN_THRESHOLD + 1


class TestAccelerationAnomalies(unittest.TestCase):
    testutil = TestUtilities()

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)
        return super().setUpClass()

    def _delete_data(self):
        with engine.connect() as con:
            con.execute("DELETE FROM accelerometer_data;")
            con.execute("DELETE FROM trips;")  # We need to delete ALL trips
            con.execute("DELETE FROM events;")
            con.execute("DELETE FROM problems;")
        for item in os.listdir(common_constants.STORAGE_FOLDER):
            if item.endswith(".pkl"):
                os.remove(os.path.join(common_constants.STORAGE_FOLDER, item))

    def setUp(self):
        self._delete_data()

    def tearDown(self):
        self._delete_data()

    def test_basic_setup(self):
        aap = AccelerationAnomalyProcessor()
        self.assertTrue(aap is not None)

    def test_event_creation(self):
        aap = AccelerationAnomalyProcessor()
        occurred_at = datetime.now() - timedelta(minutes=2)
        aap._log_event("testSubtype", occurred_at, 42)
        ev = self._get_last_event("testSubtype")
        self.assertTrue(ev["occurred_at"] == occurred_at)
        self.assertTrue(ev["source"] == common_constants.EVENT_SOURCE_ANOMALY_DETECTOR)
        self.assertTrue(ev["confidence"] == 42)

    def test_releveling_detect(self):
        start_of_quiet_period = self._get_latest_possible_start_of_quiet_period()
        self.testutil.insert_trip(
            starts_at=start_of_quiet_period - timedelta(seconds=20),
            ends_at=start_of_quiet_period - timedelta(seconds=1),
        )
        for _ in range(0, constants.RELEVELING_THRESHOLD + 1):
            self._add_outlier(
                datetime.now()
                - timedelta(seconds=1 + constants.QUIET_TIME_GUARD_INTERVAL),
                constants.RELEVELING_AMPLITUDE_MIN_THRESHOLD + 1,
            )
        aap = AccelerationAnomalyProcessor()
        aap.check_for_anomalies()
        ev = self._get_last_event(common_constants.EVENT_SUBTYPE_RELEVELING)
        self.assertIsNotNone(ev, "Releveling accelerometer data did not cause an event")

    def test_negative_releveling_detect_1(self):
        start_of_quiet_period = self._get_latest_possible_start_of_quiet_period()
        self.testutil.insert_trip(starts_at=start_of_quiet_period)
        for _ in range(0, constants.RELEVELING_THRESHOLD + 1):
            self._add_outlier(
                datetime.now()
                - timedelta(seconds=1 + constants.QUIET_TIME_GUARD_INTERVAL),
                constants.RELEVELING_AMPLITUDE_MIN_THRESHOLD - 1,
            )
        aap = AccelerationAnomalyProcessor()
        aap.check_for_anomalies()
        ev = self._get_last_event(common_constants.EVENT_SUBTYPE_RELEVELING)
        self.assertTrue(
            ev is None, "Below level accelerometer data caused a releveling event"
        )

    def test_negative_releveling_detect_2(self):
        start_of_quiet_period = self._get_latest_possible_start_of_quiet_period()
        self.testutil.insert_trip(starts_at=start_of_quiet_period)
        for _ in range(0, constants.RELEVELING_THRESHOLD - 1):
            self._add_outlier(
                datetime.now()
                - timedelta(seconds=1 + constants.QUIET_TIME_GUARD_INTERVAL),
                constants.RELEVELING_AMPLITUDE_MIN_THRESHOLD + 1,
            )
        aap = AccelerationAnomalyProcessor()
        aap.check_for_anomalies()
        ev = self._get_last_event(common_constants.EVENT_SUBTYPE_RELEVELING)
        self.assertTrue(
            ev is None, "Insufficient number of outliers caused a releveling event"
        )

    def test_should_we_check_for_non_releveling_with_no_problems(self):
        aap = AccelerationAnomalyProcessor()
        self.assertFalse(
            aap._should_we_check_for_not_releveling(),
            "With no problems in the system, we shouldn't check for not releveling",
        )

    def test_should_we_check_for_non_releveling_with_closed_problem(self):
        problem_closed_at = datetime.now() - timedelta(minutes=5)
        self.testutil.create_problem(
            common_constants.PROB_TYPE_ANOMALY,
            problem_subtype=common_constants.PROB_SUBTYPE_RELEVELING,
            started_at=problem_closed_at,
            ended_at=problem_closed_at,
            customer_info=None,
            confidence=99.00,
        )
        aap = AccelerationAnomalyProcessor()
        self.assertFalse(
            aap._should_we_check_for_not_releveling(),
            "With no problems in the system, we shouldn't check for not releveling",
        )

    def test_should_we_check_for_non_releveling_with_open_problem(self):
        aap = AccelerationAnomalyProcessor()
        problem_opened_at = datetime.now() - timedelta(minutes=5)
        self.testutil.create_problem(
            common_constants.PROB_TYPE_ANOMALY,
            problem_subtype=common_constants.PROB_SUBTYPE_RELEVELING,
            started_at=problem_opened_at,
            ended_at=None,
            customer_info=None,
            confidence=99.00,
        )
        self.assertTrue(
            aap._should_we_check_for_not_releveling(),
            "With an problem in the system, we should check for not releveling",
        )

    def test_check_for_not_releveling_no_events_or_relevelings(self):
        aap = AccelerationAnomalyProcessor()
        testutil = TestUtilities()
        first_trip_time = datetime.now() - timedelta(days=20)
        testutil.insert_trip(starts_at=first_trip_time, ends_at=first_trip_time)
        quiet_seconds = 60 * 60 * 24  # 24 hour quiet time
        aap._check_for_not_releveling(quiet_seconds)
        last_event = self._get_last_event(common_constants.EVENT_SUBTYPE_RELEVELING)
        self.assertFalse(
            last_event and last_event[2] > 0,
            "With no trips and no outliers and no problems in last 24 hours, we should NOT get a no-releveling event",
        )

    def test_check_for_not_releveling_with_open_problem(self):
        testutil = TestUtilities()
        aap = AccelerationAnomalyProcessor()
        problem_opened_at = datetime.now() - timedelta(minutes=5)
        self.testutil.create_problem(
            common_constants.PROB_TYPE_ANOMALY,
            problem_subtype=common_constants.PROB_SUBTYPE_RELEVELING,
            started_at=problem_opened_at,
            ended_at=None,
            customer_info=None,
            confidence=99.00,
        )
        last_trip_time = datetime.now() - timedelta(
            seconds=constants.LACK_OF_RELEVELING_WINDOW_SIZE
            + constants.QUIET_TIME_GUARD_INTERVAL * 2
            + 1
        )
        testutil.insert_trip(starts_at=last_trip_time, ends_at=last_trip_time)
        aap._check_for_not_releveling(aap._get_quiet_time_seconds())
        last_event = self._get_last_event(common_constants.EVENT_SUBTYPE_RELEVELING)
        self.assertIsNotNone(
            last_event,
            "With proper quiet time and open problem, we should get a no-releveling event",
        )
        self.assertEqual(
            last_event[2],
            0,
            "With proper quiet time and open problem, should be releveling event with 0 confidence",
        )

    def test_full_system(self):
        high_outlier = constants.RELEVELING_AMPLITUDE_MAX_THRESHOLD - 1
        testutil = TestUtilities()
        aap = AccelerationAnomalyProcessor()
        aap.check_for_anomalies()
        last_event = self._get_last_event(common_constants.EVENT_SUBTYPE_RELEVELING)
        self.assertTrue(last_event is None)
        last_trip_time = datetime.now() - timedelta(hours=8)
        testutil.insert_trip(starts_at=last_trip_time, ends_at=last_trip_time)
        for _ in range(0, constants.RELEVELING_THRESHOLD - 1):
            self._add_outlier(
                datetime.now()
                - timedelta(seconds=constants.QUIET_TIME_GUARD_INTERVAL * 1 + 5),
                high_outlier,
            )
        aap.check_for_anomalies()
        last_event = self._get_last_event(common_constants.EVENT_SUBTYPE_RELEVELING)
        self.assertTrue(last_event is None)
        self._add_outlier(
            datetime.now()
            - timedelta(seconds=constants.QUIET_TIME_GUARD_INTERVAL * 1 + 5),
            high_outlier,
        )
        self._add_outlier(
            datetime.now()
            - timedelta(seconds=constants.QUIET_TIME_GUARD_INTERVAL * 1 + 5),
            high_outlier,
        )
        aap.check_for_anomalies()
        last_event = self._get_last_event(common_constants.EVENT_SUBTYPE_RELEVELING)
        self.assertTrue(last_event[2] > 0, "Outliers didn't cause a releveling event")

        self._remove_all_outliers()

    def test_get_quiet_time(self):
        testutil = TestUtilities()
        aap = AccelerationAnomalyProcessor()
        quiet_seconds = aap._get_quiet_time_seconds()
        self.assertTrue(
            quiet_seconds is None, "Without a trip, we should not detect a quiet time"
        )
        last_trip_time = datetime.now() - timedelta(hours=1)
        testutil.insert_trip(starts_at=last_trip_time, ends_at=last_trip_time)
        quiet_seconds = aap._get_quiet_time_seconds()
        self.assertTrue(
            quiet_seconds > (60 * 60 - 5) and quiet_seconds < (60 * 60 + 5),
            "Wrong number of computed quiet seconds for a given last trip",
        )

    def test_get_outliers(self):
        aap = AccelerationAnomalyProcessor()
        self._add_outlier(
            datetime.now()
            - timedelta(seconds=constants.QUIET_TIME_GUARD_INTERVAL * 1 + 181),
            outlier_level,
        )
        self.assertTrue(
            aap._get_outliers(180)[0] == 0,
            "We should get no outliers if they are all before the window",
        )
        self._add_outlier(
            datetime.now()
            - timedelta(seconds=constants.QUIET_TIME_GUARD_INTERVAL * 1 - 5),
            outlier_level,
        )
        self.assertTrue(
            aap._get_outliers(180)[0] == 0,
            "We should get no outliers if they are after the window",
        )
        self._add_outlier(
            datetime.now()
            - timedelta(seconds=constants.QUIET_TIME_GUARD_INTERVAL * 1 + 10),
            outlier_level,
        )
        outliers = aap._get_outliers(180)
        self.assertTrue(
            outliers[0] == 1, "We should detect outliers that are in the window"
        )
        self._add_outlier(
            datetime.now()
            - timedelta(seconds=constants.QUIET_TIME_GUARD_INTERVAL * 1 + 177),
            outlier_level,
        )
        outliers = aap._get_outliers(180)
        self.assertTrue(
            outliers[0] == 2, "We should detect both outliers that are in the window"
        )
        self.assertTrue(
            outliers[1] == outlier_level * 2,
            "The sum of the outliers in the window should be correct",
        )

    def _get_last_event(self, subtype):
        with engine.connect() as con:
            return con.execute(
                "SELECT occurred_at, source, confidence FROM events "
                "WHERE event_subtype = '{0}' ORDER BY id DESC LIMIT 1".format(subtype)
            ).first()

    def _add_outlier(self, time, value):
        with engine.connect() as con:
            con.execute(
                "INSERT INTO accelerometer_data "
                "(timestamp, x_data, y_data, z_data) "
                "VALUES ('{0}', 0.0, 0.0, {1} )".format(
                    time, value
                )
            )

    def _remove_all_outliers(self):
        with engine.connect() as con:
            con.execute(
                "DELETE FROM accelerometer_data WHERE ABS(z_data) > {0};".format(
                    constants.RELEVELING_AMPLITUDE_MIN_THRESHOLD
                )
            )

    def _get_latest_possible_start_of_quiet_period(self):
        return datetime.now() - timedelta(
            seconds=2
            + constants.RELEVELING_WINDOW_SIZE
            + constants.QUIET_TIME_GUARD_INTERVAL * 2
        )

    def _create_anomaly_event(
        self,
        type=common_constants.EVENT_TYPE_ANOMALY,
        subtype=None,
        occurred_at=datetime.now(),
        detected_at=datetime.now(),
        confidence=0.00,
    ):
        fields = "event_type"
        values = "'" + type + "'"
        fields += ", detected_at"
        values += ", '" + str(detected_at) + "'"
        fields += ", occurred_at"
        values += ", '" + str(occurred_at) + "'"
        fields += ", confidence"
        values += ", " + str(confidence)
        if subtype is not None:
            fields += ", event_subtype"
            values += ", '" + subtype + "'"
        fields += ", source"
        values += ", 'testing'"
        with engine.connect() as con:
            con.execute("INSERT INTO events ({0}) VALUES ({1});".format(fields, values))


if __name__ == "__main__":
    unittest.main()
