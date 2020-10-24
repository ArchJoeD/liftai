import os
import unittest
from datetime import datetime, timedelta
from time import sleep
from unittest.mock import Mock

from elisha.elisha_processor import ElishaProcessor
from elisha.shutdown import Shutdown
import utilities.common_constants as common_constants
from utilities.test_utilities import TestUtilities
from utilities.db_utilities import Session, Event


UNIT_TEST_SOURCE = 'unit test source'
SYSTEM_KEY = 'system'


class TestShutdownOverall(unittest.TestCase):

    tu = TestUtilities()

    @classmethod
    def setUpClass(cls):
        print("Setting up for testing (NOTE: THESE ARE DESTRUCTIVE TESTS!!!)...")
        os.system("sudo systemctl stop elisha.service")

    def setUp(self):
        os.system("sudo rm -f {0}/elisha*.pkl".format(common_constants.STORAGE_FOLDER))
        self.session = Session()
        self.tu = TestUtilities(self.session)
        self.tu.remove_test_events_and_problems()
        self.ep = self._get_ep_instance(self.session)

    def tearDown(self):
        try:
            os.system("sudo rm -f {0}/elisha*.pkl".format(common_constants.STORAGE_FOLDER))
            self.tu.remove_test_events_and_problems()
        finally:
            self.session.rollback()
            self.session.close()

    def _db_now(self,):
        return self.session.execute('SELECT NOW() as now').first().now.replace(tzinfo=None)

    def _process_all_events(self, elisha_processor):
        elisha_processor.test_tool_no_more_events = False
        while not elisha_processor.test_tool_no_more_events:
            elisha_processor.process_data(self.session)

    def _get_ep_instance(self, is_accel_running=True, reuse_this_instance=None):
        mock = Mock()
        mock.return_value = is_accel_running
        if reuse_this_instance is None:
            ep = ElishaProcessor()
            ep.setup(self.session)
            shutdown = Shutdown()
            shutdown._is_accelerometer_working = mock
            ep.shutdown = shutdown
            # Fix for a problem where the switch dictionary points to the old instances of the shutdown object.
            ep._setup_switch_dictionary()
        else:
            ep = reuse_this_instance
            ep.shutdown._is_accelerometer_working = mock
        return ep

    def test_file_load(self):
        id = 1234
        state_info = {'foo': 'bar', 'other stuff': 4321}
        self.ep._save_last_event_id(id)
        self.ep._save_state_info(state_info)
        self.ep.last_event_id = 0
        self.ep.state_info = {'wrong': 'stuff'}
        self.ep._restore_last_event_id(self.session)
        self.ep._restore_state_info()
        self.assertTrue(self.ep.last_event_id == id)
        self.assertTrue(self.ep.state_info == state_info)

    def test_file_load_defaults(self):
        self.assertTrue(self.ep.last_event_id == -1)
        self.assertTrue(common_constants.PROB_TYPE_SHUTDOWN in self.ep.state_info)
        self.assertTrue(common_constants.PROB_TYPE_VIBRATION in self.ep.state_info)
        self.assertTrue(common_constants.PROB_TYPE_ANOMALY in self.ep.state_info)

    def test_corrupted_file_load(self):
        os.system("sudo rm {0}".format(self.ep.storage_last_event))
        os.system("sudo rm {0}".format(self.ep.storage_state_info))
        os.system("touch {0}".format(self.ep.storage_last_event))
        os.system("touch {0}".format(self.ep.storage_state_info))
        self.ep._restore_last_event_id(self.session)        # Should not raise an exception
        self.ep._restore_state_info()           # Should not raise an exception
        os.system("sudo rm {0}".format(self.ep.storage_last_event))
        os.system("sudo rm {0}".format(self.ep.storage_state_info))
        self.ep._restore_last_event_id(self.session)        # Should not raise an exception
        self.ep._restore_state_info()           # Should not raise an exception
        self.assertTrue(True)

    def test_create_event(self):
        # TODO: Move this to a common test area (create_event was originally part of this file
        detected_at = datetime.now()
        occurred_at = detected_at - timedelta(days=90)
        confidence = 12.34
        event_type = 'not a valid event type'
        self.tu.create_event(
            event_type = event_type,
            subtype = 'unit testing',
            detected_at = detected_at,
            occurred_at = occurred_at,
            source = 'unit test source',
            confidence = 12.34,
            details = {"root cause":"scrambled eggs", "other stuff":"unit testing"},
            chart_info = {"label":"unit test chart", "x-axis label":"unit test X", "y-axis label":"unit test Y"}
        )
        event = self.session.execute('SELECT * FROM events ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual( event['event_type'], event_type)
        self.assertEqual( event['event_subtype'], 'unit testing')
        self.assertEqual( event['occurred_at'], occurred_at)
        self.assertEqual( event['detected_at'], detected_at)
        self.assertEqual( event['source'], 'unit test source')
        self.assertLess(abs(float(event['confidence']) - confidence), 0.01,
                                'event ended up with wrong confidence {0} instead of {1}'.format(event['confidence'],confidence))
        self.assertIn('root cause', event['details'], 'details didn\'t get into the test event')
        self.assertIn('label', event['chart_info'], 'chart_info didn\'t get into the test event')
        self.session.execute("DELETE FROM events WHERE event_type = '{0}'".format(event_type))

    def test_combined_confidence(self):
        self.assertTrue(self.ep.shutdown._compute_combined_confidence(0,90) == 90)
        self.assertTrue(self.ep.shutdown._compute_combined_confidence(90, 0) == 90)
        self.assertTrue(self.ep.shutdown._compute_combined_confidence(80, 80) == 90)
        self.assertTrue(self.ep.shutdown._compute_combined_confidence(79.5, 80) == 90)
        self.assertTrue(self.ep.shutdown._compute_combined_confidence(80, 79.5) == 90)
        self.assertTrue(self.ep.shutdown._compute_combined_confidence(50, 90) == 91.25)
        self.assertTrue(self.ep.shutdown._compute_combined_confidence(90, 50) == 91.25)
        self.assertTrue(self.ep.shutdown._compute_combined_confidence(67, 70) == 85)
        self.assertTrue(self.ep.shutdown._compute_combined_confidence(70, 67) == 85)

    def test_startup_condition_with_empty_pickle_file(self):
        storage_file = self.ep.storage_state_info
        del self.ep
        os.system("sudo rm {0}; touch {0}".format(storage_file))
        ep2 = self._get_ep_instance()
        shutdown_state_info = ep2.state_info[common_constants.PROB_TYPE_SHUTDOWN]
        vibration_state_info = ep2.state_info[common_constants.PROB_TYPE_VIBRATION]
        self.assertTrue(common_constants.PROB_SHUTDOWN_STATUS in shutdown_state_info,
                        'ElishaProcessor should create a default shutdown state info value')
        self.assertTrue(common_constants.PROB_VIBRATION_STATUS in vibration_state_info,
                        'ElishaProcessor should create a default vibration state value')

    def test_shutdown_start_and_end(self):
        ep1 = self._get_ep_instance()
        self.tu.create_event(
            event_type = common_constants.EVENT_TYPE_SHUTDOWN,
            subtype = common_constants.EVENT_SUBTYPE_BANK,
            occurred_at = datetime.now(),
            source = UNIT_TEST_SOURCE,
            confidence = 90.00,
        )
        event1 = self.tu.get_last_event_or_problem('events')
        self.assertLess(ep1.last_event_id, 0, 'last_event_id should start at a negative number so we pick up the 1st event')
        # Processing the data should generate one problem: a shutdown with 90% confidence and starting at the event time.
        self._process_all_events(ep1)
        problem1 = self.tu.get_last_event_or_problem('problems')
        self.assertLess(abs(float(problem1['confidence']) - 90.00), 0.01)
        shutdown_start_diff = problem1['started_at'] - event1['occurred_at']
        self.assertLess(shutdown_start_diff.total_seconds(), 1.0)
        self.assertIsNone(problem1['ended_at'])
        self.assertEqual(problem1['problem_type'], common_constants.PROB_TYPE_SHUTDOWN)
        self.assertIn(event1['id'], problem1['events'])
        self.assertEqual(problem1['details'][SYSTEM_KEY], UNIT_TEST_SOURCE)       # Make sure we can clean up later
        self.assertEqual(ep1.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_STATUS],
                        common_constants.PROB_SHUTDOWN_WATCH)
        self.assertEqual(ep1.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_CONFIDENCE],
                        problem1['confidence'])
        self.tu.create_event(
            event_type = common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_BANK,
            occurred_at = datetime.now(),
            source = UNIT_TEST_SOURCE,
            confidence = 95.00,
        )
        event2 = self.tu.get_last_event_or_problem('events')
        # Processing the data should increase the confidence in the existing open problem and tie another event to it.
        self._process_all_events(ep1)
        problem2 = self.tu.get_last_event_or_problem('problems')
        self.assertEqual(problem2['confidence'], 95, "same shutdown subtype should override earlier confidence")
        self.assertIsNone(problem1['ended_at'])
        self.assertIn(event1['id'], problem2['events'], 'Problem should still have the first event in the list')
        self.assertIn(event2['id'], problem2['events'], 'Problem should also have the 2nd event in the list')
        self.assertEqual(ep1.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_STATUS],
                        common_constants.PROB_SHUTDOWN_WATCH)
        self.assertEqual(ep1.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_CONFIDENCE],
                        problem2['confidence'])

        # Delete this instance and create a new one (which happens after reboot or a crash)
        del ep1
        ep2 = self._get_ep_instance()
        self.assertEqual(ep2.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_STATUS],
                        common_constants.PROB_SHUTDOWN_WATCH, 'The state_info should be persistent')
        self.assertEqual(ep2.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_CONFIDENCE],
                        problem2['confidence'], 'The state_info should all be persistent')

        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_BANK,
            occurred_at = datetime.now(),
            source = UNIT_TEST_SOURCE,
            confidence = 00.00,
        )
        event3 =  self.tu.get_last_event_or_problem('events')
        # Processing the data should end the problem (and end the shutdown condition).
        self._process_all_events(ep2)
        self.assertEqual(ep2.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_STATUS],
                        common_constants.PROB_SHUTDOWN_RUNNING,
                        'shutdown state should be running but it\'s {0}'\
                        .format(ep2.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_STATUS]))
        self.assertEqual(ep2.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_CONFIDENCE],
                        0)
        self.assertEqual(ep2.last_event_id, event3['id'], "Last event id was not correctly saved")

    def test_multiple_shutdown_alerts_together(self):
        ep = self._get_ep_instance()
        #  Create three events and let Elisha process all of them at once
        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_BANK,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=90.00,
        )
        event1 = self.tu.get_last_event_or_problem('events')
        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_BANK,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=95.00,
        )
        event2 = self.tu.get_last_event_or_problem('events')
        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_BANK,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=99.00,
        )
        event3 = self.tu.get_last_event_or_problem('events')
        self._process_all_events(ep)
        problem = self.tu.get_last_event_or_problem('problems')
        # At this point, all three should have been processed.
        confidence = ep.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_CONFIDENCE]
        self.assertTrue(confidence == 99.00,
                        'Shutdowns of the same type should override each other.  Should be 99, but was {0}'.format(confidence))
        self.assertTrue(event1['id'] in problem['events'], 'First event should be in problem event list')
        self.assertTrue(event2['id'] in problem['events'], 'Second event should be in problem event list')
        self.assertTrue(event3['id'] in problem['events'], 'Third event should be in problem event list')
        self.assertTrue(ep.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_STATUS]
                        == common_constants.PROB_SHUTDOWN_WARNING, 'Shutdown state should be shut down after 3 shutdown events')
        open_problem_id = ep.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_OPEN_PROBLEM_ID]
        self.assertTrue(open_problem_id == problem['id'], 'Elisha shutdown open problem is wrong: {0} vs {1}'\
                        .format(open_problem_id, problem['id']))

        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_BANK,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=00.00,
        )
        event4 = self.tu.get_last_event_or_problem('events')
        self._process_all_events(ep)
        # Refresh the problem data
        problem = self.tu.get_last_event_or_problem('problems')
        status = ep.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_STATUS]
        self.assertTrue(status == common_constants.PROB_SHUTDOWN_RUNNING,
                        'Ending shutdown state should be running after 0 confidence, not {0}'.format(status))
        self.assertTrue(problem['confidence'] == 99.00, "The confidence in the problems table should NOT go back to zero")
        confidence = ep.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_CONFIDENCE]
        self.assertTrue(confidence == 0, "Elisha shutdown confidence should drop to zero after a 0 confidence event")
        self.assertEqual(ep.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_OPEN_PROBLEM_ID], -1,
                        "Elisha shutdown should set open problem id to -1 after a resume event")
        self.assertTrue(problem['ended_at'] == event4['occurred_at'], "Elisha shutdown should close the open problem after resume")
        # Partly this next check is because we can get multiple resume events and we don't want to make it complicated.
        self.assertFalse(event4['id'] in problem['events'], "Don't put resume events into shutdown problem")

    def test_old_problem_combinations(self):
        # Detect both problems about five minutes ago
        initial_detected_at = datetime.now() - timedelta(minutes=5)

        ep = self._get_ep_instance()
        start_event_time = initial_detected_at - timedelta(hours=9)
        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_BANK,
            occurred_at=datetime.now(),
            detected_at=initial_detected_at + timedelta(seconds=5),
            source=UNIT_TEST_SOURCE,
            confidence=90.00,
        )
        self._process_all_events(ep)
        problem1 = self.tu.get_last_event_or_problem('problems')
        self.assertEqual(problem1['confidence'], 90)

        start_event_time = initial_detected_at - timedelta(hours=8)
        start_event_time = start_event_time.replace(minute=0, second=0)
        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN,
            occurred_at=start_event_time,
            detected_at=initial_detected_at,
            source=UNIT_TEST_SOURCE,
            confidence=70.00,
        )
        self._process_all_events(ep)
        problem2 = self.tu.get_last_event_or_problem('problems')
        self.assertEqual(problem2['confidence'], 91.25)

    def test_confidence_combinations(self):
        ep = self._get_ep_instance()
        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_BANK,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=90.00,
        )
        self._process_all_events(ep)
        problem1 = self.tu.get_last_event_or_problem('problems')
        self.assertTrue(problem1['confidence'] == 90)

        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_STANDALONE,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=90.00,
        )
        self._process_all_events(ep)
        problem2 = self.tu.get_last_event_or_problem('problems')
        self.assertTrue(abs(float(problem2['confidence']) - 95.00) < 1.0,
                        "90% + 90% confidence should be around 95, was {0}".format(problem2['confidence']))

        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=90.00,
        )
        self._process_all_events(ep)
        problem3 = self.tu.get_last_event_or_problem('problems')
        self.assertTrue(problem3['confidence'] > 95,
                        "90% + 90% + 90% confidence should be > 95, was {0}".format(problem3['confidence']))

        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_BANK,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=95.00,
        )
        self._process_all_events(ep)
        problem4 = self.tu.get_last_event_or_problem('problems')
        self.assertTrue(problem4['confidence'] > problem3['confidence'],
                        "adding more confidence should increase it: went from {0} to {1} on event 4"\
                        .format(problem3['confidence'], problem4['confidence']))

        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=99.00,
        )
        self._process_all_events(ep)
        problem5 = self.tu.get_last_event_or_problem('problems')
        self.assertTrue(problem5['confidence'] > problem4['confidence'],
                        "adding more confidence should increase it: went from {0} to {1} on event 5"\
                        .format(problem4['confidence'], problem5['confidence']))

        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=00.00,
        )
        self._process_all_events(ep)
        self.assertTrue(ep.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_CONFIDENCE] == 0)
        self.assertEqual(ep.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_OPEN_PROBLEM_ID], -1)

        # Try one more to make sure it doesn't break anything (each one will send its own resume event).
        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_STANDALONE,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=00.00,
        )
        self._process_all_events(ep)
        self.assertTrue(ep.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_SHUTDOWN_CONFIDENCE] == 0)
        self.assertEqual(ep.state_info[common_constants.PROB_TYPE_SHUTDOWN][common_constants.PROB_OPEN_PROBLEM_ID], -1)

    def test_updated_at(self):
        earliest = self._db_now()
        ep = self._get_ep_instance()
        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_BANK,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=90.00,
        )
        self._process_all_events(ep)
        problem = self.tu.get_last_event_or_problem('problems')
        last_updated_at = problem['updated_at']
        checkpoint1 = self._db_now()
        self.assertTrue(last_updated_at >= earliest)
        self.assertTrue(last_updated_at <= checkpoint1)
        sleep(0.3)
        checkpoint2 = self._db_now()
        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_SHUTDOWN,
            subtype=common_constants.EVENT_SUBTYPE_BANK,
            occurred_at=datetime.now(),
            source=UNIT_TEST_SOURCE,
            confidence=95.00,
        )
        self._process_all_events(ep)
        updated_problem = self.tu.get_last_event_or_problem('problems')
        checkpoint3 = self._db_now()
        self.assertTrue(updated_problem['updated_at'] >= checkpoint2)
        self.assertTrue(updated_problem['updated_at'] <= checkpoint3)

    def test_unknown_event(self):
        ep = self._get_ep_instance()
        original_state_info = ep.state_info
        event = Event(
            id=42,
            occurred_at=datetime.now(),
            detected_at=datetime.now(),
            event_type="Year 2020 Stuff",
            event_subtype="murder hornets in hoistway",
        )
        state_info = ep._unknown_event_type(Mock(), event, original_state_info.copy())
        self.assertEqual(original_state_info, state_info)

if __name__ == "__main__":
    unittest.main()
