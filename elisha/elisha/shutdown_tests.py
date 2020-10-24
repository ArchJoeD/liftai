import os
import unittest
from datetime import datetime, timedelta
from decimal import *
from time import sleep
from unittest.mock import Mock, ANY

from bank_stoppage.processor import BankStoppageProcessor
from elisha.elisha_processor import ElishaProcessor
from elisha.shutdown import Shutdown
from standalone_stoppage.processor import StandaloneStoppageProcessor
from utilities.test_utilities import TestUtilities
import utilities.common_constants as common_constants
from utilities.db_utilities import Session
from notifications.notifications import Notification, NotificationTopic


UNIT_TEST_SOURCE = "unit test source"
SYSTEM_KEY = "system"


class ShutdownIntegration(unittest.TestCase):
    start_time = datetime.now()
    testutil = TestUtilities()

    @classmethod
    def setUpClass(cls):
        print("Setting up for testing (NOTE: THESE ARE DESTRUCTIVE TESTS!!!)...")
        os.system("sudo systemctl stop elisha.service")
        # TODO: Shut down any services that generate events: stoppage detection, vibration detection, etc.

    def _clear(self):
        os.system("sudo rm -f {}".format(common_constants.CONFIG_FILE_NAME))
        os.system("sudo rm -f {}/elisha*.pkl".format(common_constants.STORAGE_FOLDER))
        os.system("sudo rm -f {}/bank_stoppage*.pkl".format(common_constants.STORAGE_FOLDER))
        os.system("sudo rm -f {}/stand*.pkl".format(common_constants.STORAGE_FOLDER))
        self._remove_test_events_and_problems()

    def setUp(self):
        self.session = Session()
        self.testutil = TestUtilities(self.session)
        self.testutil.set_config({"type": "elevator"})
        self._clear()

    def tearDown(self):
        try:
            self._clear()
        finally:
            self.session.rollback()
            self.session.close()

    def _remove_test_events_and_problems(self):
        self.testutil.delete_trips()
        self.session.execute("DELETE FROM events WHERE occurred_at > '{0}'".format(self.start_time - timedelta(hours=2)))
        self.session.execute("DELETE FROM problems WHERE details ->> '{0}' = '{1}'".format(SYSTEM_KEY, UNIT_TEST_SOURCE))
        self.session.execute("DELETE FROM bank_trips WHERE timestamp > '{0}'".format(self.start_time - timedelta(hours=2)))

    def _turn_the_crank(self, elisha_processor, bank_processor=None, standalone_processor=None):
        if bank_processor is not None:
            bank_processor.run()
        if standalone_processor is not None:
            standalone_processor.run()
        elisha_processor.process_data()

    # TODO: This code is duplicated in tests.py
    def _get_ep_instance(self, is_accel_running=True):
        mock = Mock()
        mock.return_value = is_accel_running
        ep = ElishaProcessor()
        ep.setup(self.session)
        shutdown = Shutdown()
        shutdown._is_accelerometer_working = mock
        ep.shutdown = shutdown
        # Fix for a problem where the switch dictionary points to the old instances of the shutdown object.
        ep._setup_switch_dictionary()
        return ep

    def _get_bank_instance(self, is_accel_running=True):
        mock = Mock()
        mock.return_value = is_accel_running
        bsp = BankStoppageProcessor()
        bsp._is_accelerometer_working = mock
        return bsp

    def _get_standalone_instance(self, is_accel_running=True):
        mock = Mock()
        mock.return_value = is_accel_running
        ssp = StandaloneStoppageProcessor()
        ssp._is_accelerometer_working = mock
        return ssp

    def _verify_event(self, stoppage_processor, expected_confidence, expected_state, expected_subtype):
        print("State is now {0} and we're expecting {1}".format(stoppage_processor.last_state, expected_state))
        self.assertEqual(stoppage_processor.last_state, expected_state)
        events = self.testutil.get_events(self.start_time - timedelta(hours=2))
        self.assertGreater(len(events), 0)
        event = events[len(events)-1]
        self.assertEqual(event['confidence'], expected_confidence)
        self.assertEqual(event['event_subtype'], expected_subtype)

    def _verify_problem(self, expected_confidence, greater_less_or_equal="equal"):
        events = self.testutil.get_events(self.start_time - timedelta(hours=2))
        self.assertGreater(len(events), 0)
        # Get the most recent event and make sure it's contained in the problem's list.
        event = events[len(events) - 1]
        problems = self.testutil.get_problems(self.start_time - timedelta(hours=2))
        self.assertGreater(len(problems), 0)
        problem = problems[len(problems) - 1]
        if expected_confidence == 00.00 and greater_less_or_equal == "equal":
            self.assertIsNotNone(problem['ended_at'])
            # Note that the confidence stays at the high water mark and doesn't go back to zero.
            self.assertGreater(problem['confidence'], 0)
        else:
            self.assertEqual(problem['problem_type'], common_constants.PROB_TYPE_SHUTDOWN)
            if greater_less_or_equal == "equal":
                self.assertEqual(problem['confidence'], expected_confidence)
            elif greater_less_or_equal == "less":
                self.assertLess(problem['confidence'], expected_confidence)
            elif greater_less_or_equal == "greater":
                self.assertGreater(problem['confidence'], expected_confidence)
            else:
                self.assertTrue(False, "Internal logic error with greater_less_or_equal")
            self.assertIn(event['id'], problem['events'])
            self.assertIsNone(problem['ended_at'])
        return problem['confidence']

    def test_shutdown_start_and_end_with_multiple_inputs(self):
        ep = self._get_ep_instance()
        for _ in range(3):
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_BANK, confidence=82.00)
            ep.process_data(self.session)
            self._verify_problem(82.00)
            sleep(1)
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_BANK, confidence=90.00)
            # Shutdown watch happens here.
            ep.process_data(self.session)
            self._verify_problem(90.00)
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_STANDALONE, confidence=90.00)
            ep.process_data(self.session)
            curr_confidence = self._verify_problem(90, greater_less_or_equal="greater")
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_STANDALONE, confidence=95.00)
            ep.process_data(self.session)
            curr_confidence = self._verify_problem(curr_confidence, greater_less_or_equal="greater")
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN, confidence=95.00)
            ep.process_data(self.session)
            curr_confidence = self._verify_problem(curr_confidence, greater_less_or_equal="greater")
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_BANK, confidence=97.00)
            ep.process_data(self.session)
            curr_confidence = self._verify_problem(curr_confidence, greater_less_or_equal="greater")
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN, confidence=99.00)
            # Shutdown warning happens here.
            ep.process_data(self.session)
            curr_confidence = self._verify_problem(curr_confidence, greater_less_or_equal="greater")
            sleep(1)
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_STANDALONE, confidence=99.00)
            ep.process_data(self.session)
            curr_confidence = self._verify_problem(curr_confidence, greater_less_or_equal="greater")
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_STANDALONE, confidence=99.50)
            ep.process_data(self.session)
            curr_confidence = self._verify_problem(curr_confidence, greater_less_or_equal="greater")
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_BANK, confidence=0.00)
            # End of shutdown happens here.
            ep.process_data(self.session)
            self._verify_problem(0.00)
            sleep(1)
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN, confidence=0.00)
            ep.process_data(self.session)
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_STANDALONE, confidence=0.00)
            ep.process_data(self.session)

    def test_shutdown_event_is_tracked(self):
        ep = self._get_ep_instance()
        notif = Mock(Notification)
        ep.shutdown.notif = notif
        confidence = 82.00

        self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_BANK, confidence=confidence)
        ep.process_data(self.session)

        notif.send.assert_called_once_with(
            NotificationTopic.SHUTDOWN_CONFIDENCE,
            include_last_trip=True,
            notif_data={
                "shutdown_subtype": common_constants.EVENT_SUBTYPE_BANK,
                "confidence": confidence,
            }
        )

    def test_shutdown_event_notification_includes_last_trip_if_confidence(self):
        ep = self._get_ep_instance()
        notif = Mock(Notification)
        ep.shutdown.notif = notif
        confidence = 82.00

        self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_BANK, confidence=confidence)
        ep.process_data(self.session)

        notif.send.assert_called_once_with(
            NotificationTopic.SHUTDOWN_CONFIDENCE,
            include_last_trip=True,
            notif_data=ANY
        )

    def test_shutdown_event_notification_excludes_last_trip_if_no_confidence(self):
        ep = self._get_ep_instance()
        notif = Mock(Notification)
        ep.shutdown.notif = notif
        confidence = 0

        self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_BANK, confidence=confidence)
        ep.process_data(self.session)

        notif.send.assert_called_once_with(
            NotificationTopic.SHUTDOWN_CONFIDENCE,
            include_last_trip=False,
            notif_data=ANY
        )

    def test_shutdown_confidence_is_correctly_rounded(self):
        ep = self._get_ep_instance()
        notif = Mock(Notification)
        ep.shutdown.notif = notif

        cases = (
            (98.4, 98),
            (98.5, 98),
            (99.49, 99.49),
        )

        for confidence, notification_confidence in cases:
            self.testutil.create_event(subtype=common_constants.EVENT_SUBTYPE_BANK, confidence=confidence)
            ep.process_data(self.session)

            notif.send.assert_called_once_with(
                NotificationTopic.SHUTDOWN_CONFIDENCE,
                include_last_trip=True,
                notif_data={
                    "shutdown_subtype": common_constants.EVENT_SUBTYPE_BANK,
                    "confidence": notification_confidence,
                }
            )

            notif.reset_mock()


if __name__ == "__main__":
    unittest.main()
