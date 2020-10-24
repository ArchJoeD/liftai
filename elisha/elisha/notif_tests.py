import os
import unittest
from datetime import datetime, timedelta

import pytz

import utilities.common_constants as common_constants
from notifications.notifications import Notification, NotificationTopic
from utilities.test_utilities import TestUtilities

class TestNotifications(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        print("Setting up for testing (NOTE: THESE ARE DESTRUCTIVE TESTS!!!)...")
        os.system("sudo systemctl stop elisha.service")
        # TODO: Shut down any services that generate events: stoppage detection, vibration detection, etc.

    def setUp(self):
        os.system("sudo rm -f {0}/elisha*.pkl".format(common_constants.STORAGE_FOLDER))

    def tearDown(self):
        os.system("sudo rm -f {0}/elisha*.pkl".format(common_constants.STORAGE_FOLDER))

    def test_basic_notification(self):
        tu = TestUtilities()
        n = Notification()
        n.send(NotificationTopic.RESTART_FROM_POWER_LOSS)
        notif = tu.get_latest_notification()
        notif_json = notif["payload"]
        self.assertEqual(notif_json["type"], "restart_from_power_loss")

    def test_last_trip(self):
        tu = TestUtilities()
        tu.delete_trips()
        trip_start = datetime.now() - timedelta(minutes=14)
        trip_start = trip_start.replace(microsecond=0)
        trip_duration = 8
        trip_end = trip_start + timedelta(seconds=trip_duration)
        tu.insert_trip(starts_at=trip_start, ends_at=trip_end, is_up=True)
        n = Notification()
        n.send(NotificationTopic.RESTART_FROM_POWER_LOSS, include_last_trip=True)
        notif = tu.get_latest_notification()
        notif_json = notif["payload"]
        self.assertEqual(notif_json["last_trip_start_time"], pytz.utc.localize(trip_start).isoformat())
        self.assertEqual(notif_json["last_trip_direction"], "up")
        self.assertEqual(notif_json["last_trip_duration"], trip_duration)
        self.assertNotIn("roawatch", notif_json)
        tu.delete_trips()

    def test_notif_data_is_sent(self):
        tu = TestUtilities()
        expected_start_floor = 1
        notif_data = { "start_floor": expected_start_floor }
        n = Notification()
        n.send(NotificationTopic.RESTART_FROM_POWER_LOSS, notif_data=notif_data)
        latest_notification = tu.get_latest_notification()
        self.assertEqual(latest_notification["payload"]["start_floor"], expected_start_floor)

    def test_topic_to_string_happens(self):
        tu = TestUtilities()
        n = Notification()
        n.send(NotificationTopic.ROA_EVENT)
        latest_notification = tu.get_latest_notification()
        self.assertEqual(latest_notification["payload"]["type"], "roa_event")


if __name__ == "__main__":
    unittest.main()
