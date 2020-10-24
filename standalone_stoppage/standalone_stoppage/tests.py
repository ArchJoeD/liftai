
from datetime import datetime, timedelta
from unittest.mock import Mock
import json
import os
import unittest

from sqlalchemy import text

from standalone_stoppage.processor import StandaloneStoppageProcessor
from utilities import common_constants
from utilities.db_utilities import engine
from utilities.stoppage_processor import StoppageState
from utilities.test_utilities import TestUtilities


class TestStandaloneStoppage(unittest.TestCase):
    testutil = TestUtilities()

    def _delete_data(self):
        os.system("sudo rm -f {0}".format(common_constants.CONFIG_FILE_NAME))
        self._delete_trips_events_and_problems()

    def _delete_trips_events_and_problems(self):
        self.testutil.delete_trips()
        self._delete_events()
        with engine.connect() as con:
            con.execute("DELETE FROM problems WHERE started_at >= '{0}'".format(str(self.start_time - timedelta(minutes=241))))

    def _delete_events(self):
        with engine.connect() as con:
            con.execute("DELETE FROM events WHERE occurred_at >= '{0}'".format(str(self.start_time - timedelta(minutes=241))))

    def _get_events(self):
        query = text("SELECT * FROM events WHERE occurred_at >= :occurred_at ORDER BY occurred_at ASC")
        with engine.connect() as con:
            return con.execute(query, occurred_at = self.start_time - timedelta(minutes=240)).fetchall()

    def setUp(self):
        self.start_time = datetime.now()
        for item in os.listdir(common_constants.STORAGE_FOLDER):
            if item.endswith(".pkl"):
                os.remove(os.path.join(common_constants.STORAGE_FOLDER, item))
        with open(common_constants.CONFIG_FILE_NAME, "w") as cf:
            json.dump({"type": "elevator"}, cf)
        self._delete_data()

    def tearDown(self):
        self._delete_data()
        for item in os.listdir(common_constants.STORAGE_FOLDER):
            if item.endswith(".pkl"):
                os.remove(os.path.join(common_constants.STORAGE_FOLDER, item))

    # TODO: This code is duplicated in tests.py
    def _get_instance(self, is_accel_running=True):
        mock = Mock()
        mock.return_value = is_accel_running
        ssp = StandaloneStoppageProcessor()
        ssp._is_accelerometer_working = mock
        return ssp

    def test_corrupted_storage_files(self):
        self._get_instance()
        self.testutil.create_empty_storage_files(common_constants.STORAGE_FOLDER)
        self._get_instance()       # Should not raise an exception
        self.assertTrue(True)

    def test_can_detect_trip_during_shutdown(self):
        self.testutil.insert_trip()
        proc = self._get_instance()
        proc._update_state(StoppageState.STOPPED_C90)
        start = datetime.now() + timedelta(seconds=90)
        end = datetime.now() + timedelta(seconds=120)
        self.testutil.insert_trip(starts_at=start, ends_at=end)
        proc._set_last_trip(start)
        self.assertTrue(proc._is_trip_happening())

    def test_can_run_standalone_stoppage(self):
        self.testutil.insert_trip()
        proc = self._get_instance()
        proc.run()

    def test_basic_shutdown_detection(self):
        self.testutil.insert_weekly_trips_and_last_trip(weeks=5, trips=51, include_last_trip=True)
        proc = self._get_instance()
        proc.run()
        self.assertEqual(proc.last_state, 90, "Expected state 90, got {0}".format(proc.last_state))
        events = self._get_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        #print("event info: event_type={0}, event_subtype={1}, confidence={2}, occurred_at={3}".format(event['event_type'],event['event_subtype'],event['confidence'],event['occurred_at']))
        self.assertGreaterEqual(event['occurred_at'], self.start_time - timedelta(hours=2))
        self.assertEqual(event['event_type'], common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertEqual(event['event_subtype'], common_constants.EVENT_SUBTYPE_STANDALONE)
        self.assertEqual(event['confidence'], 90)
        self._delete_trips_events_and_problems()
        self.testutil.insert_weekly_trips_and_last_trip(weeks=5, trips=81, include_last_trip=False)
        proc.run()
        self.assertEqual(proc.last_state, 95)
        events = self._get_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        #print("event info: event_type={0}, event_subtype={1}, confidence={2}, occurred_at={3}".format(event['event_type'],event['event_subtype'],event['confidence'],event['occurred_at']))
        self.assertGreaterEqual(event['occurred_at'], self.start_time - timedelta(hours=2))
        self.assertEqual(event['event_type'], common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertEqual(event['event_subtype'], common_constants.EVENT_SUBTYPE_STANDALONE)
        self.assertEqual(event['confidence'], 95)
        self._delete_trips_events_and_problems()
        self.testutil.insert_weekly_trips_and_last_trip(weeks=5, trips=180, include_last_trip=False)
        proc.run()
        self.assertEqual(proc.last_state, 99, "Expected state of 99, got {0}".format(proc.last_state))
        events = self._get_events()
        self.assertEqual(len(events), 1)
        #print("event info: event_type={0}, event_subtype={1}, confidence={2}, occurred_at={3}".format(event['event_type'],event['event_subtype'],event['confidence'],event['occurred_at']))
        self.assertGreaterEqual(events[0]['occurred_at'], self.start_time - timedelta(hours=2))
        self.assertEqual(events[0]['event_type'], common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertEqual(events[0]['event_subtype'], common_constants.EVENT_SUBTYPE_STANDALONE)
        self.assertEqual(events[0]['confidence'], 99, "Expected confid of 99, got {0}".format(event['confidence']))
        self._delete_events()
        end_shutdown_time = datetime.now() - timedelta(seconds=6)
        self.testutil.insert_trip(starts_at=datetime.now() - timedelta(seconds=5), ends_at=datetime.now() - timedelta(seconds=1))
        proc.run()
        self.assertEqual(proc.last_state, 0)
        events = self._get_events()
        self.assertEqual(len(events), 1)
        #print("event info: event_type={0}, event_subtype={1}, confidence={2}, occurred_at={3}".format(event['event_type'],event['event_subtype'],event['confidence'],event['occurred_at']))
        self.assertGreaterEqual(events[0]['occurred_at'], end_shutdown_time)
        self.assertEqual(events[0]['event_type'], common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertEqual(events[0]['event_subtype'], common_constants.EVENT_SUBTYPE_STANDALONE)
        self.assertEqual(events[0]['confidence'], 0)

    def test_accelerometer_detect(self):
        self.testutil.insert_weekly_trips_and_last_trip(weeks=5, trips=51, include_last_trip=True)
        proc = self._get_instance(is_accel_running=False)
        proc.run()
        self.assertEqual(proc.last_state, 0, "standalone shutdown code didn't detect that accelerometer isn't working")

if __name__ == "__main__":
    unittest.main()
