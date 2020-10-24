import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from pytz import utc

from notifications.notifications import NotificationTopic
from roawatch.watcher import Watcher
from utilities import common_constants
from utilities.test_utilities import SessionTestCase, TestUtilities


class RoaWatchTest(SessionTestCase):
    watcher = Watcher()

    def setUp(self):
        super().setUp()
        self.watcher = Watcher()
        self.watcher.n = Mock(spec=self.watcher.n)

        self.tu = TestUtilities(self.session)

    def tearDown(self):
        self.tu.delete_trips()
        super().tearDown()

    @patch(
        "utilities.floor_detection.DeviceConfiguration.get_floor_count", return_value=2
    )
    def test_reports_only_ending_floor_if_no_previous_trip(self, get_floor_count):
        duration = 5
        starts_at = datetime.now()
        ends_at = starts_at + timedelta(seconds=duration)

        self.tu.create_floor_map(starts_at, starts_at, 0, 2)
        self.tu.insert_trip(starts_at=starts_at, ends_at=ends_at, ending_floor_id=0)
        self.watcher.check_for_trips(self.session)

        self.watcher.n.send.assert_called_once_with(
            NotificationTopic.ROA_EVENT,
            notif_data={
                "subtype": "trip",
                "duration": duration,
                "direction": "up",
                "start_floor": None,
                "end_floor": 0 + common_constants.FLOORS_USER_TRANSLATION,
            },
        )

    @patch(
        "utilities.floor_detection.DeviceConfiguration.get_floor_count", return_value=2
    )
    def test_reports_both_start_and_ending_floor_if_previous_trip(
        self, get_floor_count
    ):
        duration = 5
        first_starts_at = datetime.now()
        first_ends_at = first_starts_at + timedelta(seconds=duration)
        second_starts_at = first_ends_at + timedelta(seconds=duration)
        second_ends_at = second_starts_at + timedelta(seconds=duration)

        self.tu.create_floor_map(first_starts_at, first_starts_at, 0, 2)

        self.tu.insert_trip(
            starts_at=first_starts_at, ends_at=first_ends_at, ending_floor_id=0
        )
        self.tu.insert_trip(
            starts_at=second_starts_at, ends_at=second_ends_at, ending_floor_id=1
        )

        self.watcher.check_for_trips(self.session)

        self.assertEqual(self.watcher.n.send.call_count, 2)
        starting_landing = 0 + common_constants.FLOORS_USER_TRANSLATION
        ending_landing = 1 + common_constants.FLOORS_USER_TRANSLATION
        self.watcher.n.send.assert_called_with(
            NotificationTopic.ROA_EVENT,
            notif_data={
                "subtype": "trip",
                "direction": "up",
                "duration": duration,
                "start_floor": starting_landing,
                "end_floor": ending_landing,
            },
        )

    @patch("roawatch.watcher.get_landing_floor_for_trip", return_value=None)
    @patch("roawatch.watcher.Watcher._get_last_and_current_trip_pairs")
    def test_last_trip_id_is_moved_forward_after_processing(
        self, get_last_and_current_trip_pairs, get_landing_floor_for_trip
    ):
        session = Mock()
        now = datetime.now(utc)
        num_trips = 3
        expected_last_id = num_trips - 1
        t1, t2, t3 = (
            Mock(
                id=i,
                ending_floor=0,
                start_time=now + timedelta(seconds=(i * 5)),
                end_time=now + timedelta(seconds=(i * 5) + 5),
            )
            for i in range(num_trips)
        )
        get_last_and_current_trip_pairs.return_value = ((t1, t2), (t2, t3))

        self.watcher.check_for_trips(session)
        self.assertEqual(self.watcher.last_trip_id, expected_last_id)

    @patch("roawatch.watcher.get_landing_floor_for_trip", return_value=None)
    @patch("roawatch.watcher.Watcher._get_last_and_current_trip_pairs")
    def test_last_trip_id_does_not_move_forward_if_ending_floor_is_missing_and_trip_ended_less_than_a_minute_ago(
        self, get_last_and_current_trip_pairs, get_landing_floor_for_trip
    ):
        session = Mock()
        # Start in the present so trips are not old enough to bypass processing hold
        base_start_time = datetime.now(utc)
        num_trips = 3
        expected_last_id = -1  # Initial value
        t1, t2, t3 = (
            Mock(
                id=i,
                ending_floor=None,
                start_time=base_start_time + timedelta(seconds=(i * 5)),
                end_time=base_start_time + timedelta(seconds=(i * 5) + 5),
            )
            for i in range(num_trips)
        )
        get_last_and_current_trip_pairs.return_value = ((t1, t2), (t2, t3))

        self.watcher.check_for_trips(session)
        self.assertEqual(self.watcher.last_trip_id, expected_last_id)

    @patch("roawatch.watcher.get_landing_floor_for_trip", return_value=None)
    @patch("roawatch.watcher.Watcher._get_last_and_current_trip_pairs")
    def test_last_trip_id_does_not_move_forward_if_ending_floor_is_missing(
        self, get_last_and_current_trip_pairs, get_landing_floor_for_trip
    ):
        session = Mock()
        # Start in the past so trips are old enough for processing
        base_start_time = datetime.now(utc) - timedelta(minutes=2)
        num_trips = 3
        expected_last_id = num_trips - 1
        t1, t2, t3 = (
            Mock(
                id=i,
                ending_floor=None,
                start_time=base_start_time + timedelta(seconds=(i * 5)),
                end_time=base_start_time + timedelta(seconds=(i * 5) + 5),
            )
            for i in range(num_trips)
        )
        get_last_and_current_trip_pairs.return_value = ((t1, t2), (t2, t3))

        self.watcher.check_for_trips(session)
        self.assertEqual(self.watcher.last_trip_id, expected_last_id)

    @patch("roawatch.watcher.Watcher._get_last_and_current_trip_pairs")
    @patch("utilities.floor_detection.can_use_floor_data")
    @patch("roawatch.watcher.get_landing_floor_for_trip", return_value=1)
    def test_floor_data_not_used_if_map_not_usable(
        self,
        get_landing_floor_for_trip,
        can_use_floor_data,
        get_last_and_current_trip_pairs,
    ):
        session = Mock()
        base_start_time = datetime.now(utc) - timedelta(minutes=2)
        num_trips = 2
        duration = 5

        t1, t2 = (
            Mock(
                id=i,
                ending_floor=i,
                start_time=base_start_time + timedelta(seconds=(i * duration)),
                end_time=base_start_time + timedelta(seconds=(i * duration) + duration),
            )
            for i in range(num_trips)
        )

        get_last_and_current_trip_pairs.return_value = ((t1, t2),)

        self.watcher.check_for_trips(session)

        # There should be no starting floor or ending floor
        self.watcher.n.send.assert_called_once_with(
            NotificationTopic.ROA_EVENT,
            notif_data={
                "subtype": "trip",
                "duration": duration,
                "direction": "up",
                "start_floor": None,
                "end_floor": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
