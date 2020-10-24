import os
import unittest
from datetime import datetime, timedelta

from freezegun import freeze_time

from elisha.elisha_processor import ElishaProcessor
from utilities.test_utilities import TestUtilities
import utilities.common_constants as common_constants
from utilities.db_utilities import Session
import elisha.constants as constants
from notifications.notifications import NotificationTopic


class TestReleveling(unittest.TestCase):
    tu = TestUtilities()

    def _process_all_events(self, elisha_processor):
        elisha_processor.test_tool_no_more_events = False
        while not elisha_processor.test_tool_no_more_events:
            elisha_processor.process_data(self.session)

    def _create_relevelings(self, count, start_time, end_time, confidence=12.34):
        delta = (end_time - start_time)/count
        for i in range(count):
            self.tu.create_event(
                event_type=common_constants.EVENT_TYPE_ANOMALY,
                subtype=common_constants.EVENT_SUBTYPE_RELEVELING,
                detected_at=start_time + i*delta,
                occurred_at=start_time + i*delta,
                source='unit test source',
                confidence=confidence,
                details='{"root cause":"scrambled eggs", "other stuff":"unit testing"}',
                chart_info='{"label":"unit test chart", "x-axis label":"unit test X", "y-axis label":"unit test Y"}'
            )

    def _remove_test_events_and_problems(self, session):
        session.execute("DELETE FROM events")
        session.execute("DELETE FROM problems")

    @classmethod
    def setUpClass(cls):
        print("Setting up for testing (NOTE: THESE ARE DESTRUCTIVE TESTS!!!)...")
        os.system("sudo systemctl stop elisha.service")
        # TODO: Shut down any services that generate events: stoppage detection, vibration detection, etc.

    def setUp(self):
        os.system("sudo rm -f {0}/elisha*.pkl".format(common_constants.STORAGE_FOLDER))
        self.session = Session()
        self.ep = ElishaProcessor()
        self.ep.setup(self.session)
        self.tu = TestUtilities(self.session)
        self._remove_test_events_and_problems(self.session)

    def tearDown(self):
        try:
            os.system("sudo rm -f {0}/elisha*.pkl".format(common_constants.STORAGE_FOLDER))
            self._remove_test_events_and_problems(self.session)
        finally:
            self.session.rollback()
            self.session.close()

    def test_releveling_smoke(self):
        now = datetime.now()
        first_releveling = now - timedelta(hours=constants.RELEVELING_LOOKBACK_HOURS-1)
        self._create_relevelings(
            constants.RELEVELING_COUNT_THRESHOLD+1,
            first_releveling,
            now - timedelta(minutes=50),
            confidence=80)
        self._process_all_events(self.ep)
        problem = self.tu.get_last_event_or_problem("problems")
        self.assertEqual(problem['problem_type'], common_constants.PROB_TYPE_ANOMALY,
                         "lots of relevelings didn't cause an anomaly problem")
        self.assertEqual(problem['problem_subtype'], common_constants.PROB_SUBTYPE_RELEVELING,
                         "lots of relevelings didn't cause a releveling subtype problem")
        self.assertEqual(problem['started_at'], first_releveling)
        self.assertIsNone(problem['ended_at'], "Releveling problem got closed out incorrectly")

        self._create_relevelings(
            1,
            now - timedelta(minutes=45),
            now - timedelta(minutes=30),
            confidence=0)
        self._process_all_events(self.ep)
        problem = self.tu.get_last_event_or_problem("problems")
        self.assertIsNotNone(problem['ended_at'], "Releveling problem did not get closed out on non-releveling event")
        self.assertLess(problem["ended_at"], now - timedelta(minutes=28), "Problem closed out too late")
        self.assertGreater(problem["ended_at"], now - timedelta(minutes=47), "Problem closed out too soon")
        # We don't send out notifications when we think releveling ends.

    def _create_releveling_event(self, when, confidence):
        self.tu.create_event(
            event_type=common_constants.EVENT_TYPE_ANOMALY,
            subtype=common_constants.EVENT_SUBTYPE_RELEVELING,
            occurred_at=when,
            detected_at=when,
            confidence=confidence)

    def test_basic_stuff(self):
        self._create_releveling_event(datetime.now(), 42)
        ep = ElishaProcessor()
        ep.setup(self.session)
        rows = ep._get_batch_of_data(self.session)
        for row in rows:
            self.assertEqual(row['event_type'], common_constants.EVENT_TYPE_ANOMALY,
                            "Oops, something interefered with the test")
            self.assertEqual(row['event_subtype'], common_constants.EVENT_SUBTYPE_RELEVELING,
                            "Yikes, something interfered with the test")

    def test_releveling_lookback_threshold(self):
        self._create_relevelings(constants.RELEVELING_COUNT_THRESHOLD + 1,
                                 datetime.now() - timedelta(hours=constants.RELEVELING_LOOKBACK_HOURS + 3),
                                 datetime.now() - timedelta(hours=constants.RELEVELING_LOOKBACK_HOURS + 1),
                                 confidence=80)
        self._process_all_events(self.ep)
        problem = self.tu.get_last_event_or_problem("problems")
        self.assertIsNone(problem, "Stale relevelings still caused a problem to be generated")

    def test_releveling_restart_1(self):
        self._create_relevelings(constants.RELEVELING_COUNT_THRESHOLD - 1,
                                 datetime.now() - timedelta(hours=constants.RELEVELING_LOOKBACK_HOURS - 2),
                                 datetime.now() - timedelta(hours=constants.RELEVELING_LOOKBACK_HOURS - 1),
                                 confidence=80)
        self._create_relevelings(1,
                                 datetime.now() - timedelta(minutes=55),
                                 datetime.now() - timedelta(minutes=50),
                                 confidence=0)
        self._create_relevelings(constants.RELEVELING_COUNT_THRESHOLD - 1,
                                 datetime.now() - timedelta(minutes=45),
                                 datetime.now(),
                                 confidence=80)
        self._process_all_events(self.ep)
        problem = self.tu.get_last_event_or_problem("problems")
        self.assertIsNone(problem, "A non-releveling event didn't reset the releveling counter")

    def test_releveling_restart_2(self):
        self._create_relevelings(constants.RELEVELING_COUNT_THRESHOLD - 1,
                                 datetime.now() - timedelta(hours=constants.RELEVELING_LOOKBACK_HOURS - 2),
                                 datetime.now() - timedelta(hours=constants.RELEVELING_LOOKBACK_HOURS - 1),
                                 confidence=80)
        self._process_all_events(self.ep)
        problem = self.tu.get_last_event_or_problem("problems")
        self.assertIsNone(problem, "Insufficient number of relevelings still caused a problem to be generated")
        self._create_relevelings(1,
                                 datetime.now() - timedelta(minutes=55),
                                 datetime.now() - timedelta(minutes=50),
                                 confidence=0)
        self._process_all_events(self.ep)
        problem = self.tu.get_last_event_or_problem("problems")
        self.assertIsNone(problem, "A non-releveling event caused a problem!")
        self._create_relevelings(constants.RELEVELING_COUNT_THRESHOLD - 1,
                                 datetime.now() - timedelta(minutes=45),
                                 datetime.now(),
                                 confidence=80)
        self._process_all_events(self.ep)
        problem = self.tu.get_last_event_or_problem("problems")
        self.assertIsNone(problem, "Insufficient # of relevelings still caused a problem to be generated")

    # We need to stub the clock so we don't accidentally trigger duplicate notification detection
    @freeze_time(datetime.now(), auto_tick_seconds=1)
    def test_releveling_repetitions(self):
        repetitions = 4
        lookback_minutes = constants.RELEVELING_LOOKBACK_HOURS * 60
        window_size = 10
        self.assertGreater(window_size, 4, "Internal test error, window size needs to be large enough for sets of events")
        self.assertLess(repetitions*window_size, lookback_minutes, "Internal test error, too many repititions")
        for i in range(repetitions):
            self._create_relevelings(constants.RELEVELING_COUNT_THRESHOLD + 1,
                                 datetime.now() - timedelta(minutes=lookback_minutes - 4),
                                 datetime.now() - timedelta(minutes=lookback_minutes - 3),
                                 confidence=80)
            self._process_all_events(self.ep)
            problem = self.tu.get_last_event_or_problem("problems")
            self.assertEqual(problem['problem_type'], common_constants.PROB_TYPE_ANOMALY,
                        "lots of relevelings didn't cause an anomaly problem, repetition {0}".format(i))
            self.assertEqual(problem['problem_subtype'], common_constants.PROB_SUBTYPE_RELEVELING,
                        "lots of relevelings didn't cause a releveling subtype problem, repetition {0}".format(i))
            self.assertIsNone(problem['ended_at'],
                             "Releveling problem got closed out incorrectly, repetition {0}".format(i))

            self._create_relevelings(1,
                                 datetime.now() - timedelta(minutes=lookback_minutes - 2),
                                 datetime.now() - timedelta(minutes=lookback_minutes - 1),
                                 confidence=0)
            self._process_all_events(self.ep)
            problem = self.tu.get_last_event_or_problem("problems")
            self.assertIsNotNone(problem['ended_at'],
                            "Releveling problem did not get closed out on non-releveling event, repetition {0}".format(i))
            lookback_minutes -= window_size


if __name__ == "__main__":
    unittest.main()
