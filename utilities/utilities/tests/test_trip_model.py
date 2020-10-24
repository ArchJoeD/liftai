from unittest.mock import patch, MagicMock, Mock
from datetime import datetime, timedelta

from pytz import utc
from sqlalchemy.orm import load_only

from utilities.db_utilities import FloorMap, Trip, get_landing_floor_for_trip
from utilities.test_utilities import SessionTestCase
from utilities import common_constants


class TestTrip(SessionTestCase):
    def test_filter_trips_after_is_exclusive(self):
        now = datetime.now(utc)

        self.session.add(Trip(end_time=now))

        num_trips = Trip.filter_trips_after(self.session.query(Trip), now).count()
        self.assertEqual(num_trips, 0)

    def test_filter_trips_after_includes_trips_after_provided_date(self):
        now = datetime.now(utc)

        self.session.add(Trip(end_time=now + timedelta(seconds=1)))
        num_trips = Trip.filter_trips_after(self.session.query(Trip), now).count()
        self.assertEqual(num_trips, 1)

        self.session.add(Trip(end_time=now + timedelta(seconds=2)))
        num_trips = Trip.filter_trips_after(self.session.query(Trip), now).count()
        self.assertEqual(num_trips, 2)

    def test_filter_trips_after_does_not_include_null_end_times(self):
        now = datetime.now(utc)

        self.session.add(Trip(end_time=None))
        num_trips = Trip.filter_trips_after(self.session.query(Trip), now).count()
        self.assertEqual(num_trips, 0)

    @patch("utilities.db_utilities.Trip.get_latest_trip_with_ending_floor")
    def test_get_latest_landing_number_returns_none_if_no_trip_with_ending_floor(
        self, get_latest_trip_with_ending_floor
    ):
        session = Mock()
        get_latest_trip_with_ending_floor.return_value = None

        result = Trip.get_latest_landing_number(session)
        get_latest_trip_with_ending_floor.assert_called_once_with(
            session.query(Trip).options(load_only(Trip.end_time, Trip.ending_floor))
        )
        self.assertIsNone(result)

    @patch("utilities.db_utilities.Trip.get_latest_trip_with_ending_floor")
    @patch("utilities.db_utilities.FloorMap.get_active_map_for_datetime")
    def test_get_latest_landing_number_returns_none_if_no_floor_map(
        self, get_active_map_for_datetime, get_latest_trip_with_ending_floor
    ):
        session = Mock()
        trip = Mock()
        get_latest_trip_with_ending_floor.return_value = trip
        get_active_map_for_datetime.return_value = None

        result = Trip.get_latest_landing_number(session)
        get_active_map_for_datetime.assert_called_once_with(session, trip.end_time)
        self.assertIsNone(result)

    @patch("utilities.db_utilities.Trip.get_latest_trip_with_ending_floor")
    @patch("utilities.db_utilities.FloorMap.get_active_map_for_datetime")
    def test_get_latest_landing_returns_landing_number(
        self, get_active_map_for_datetime, get_latest_trip_with_ending_floor
    ):
        session = Mock()
        ending_floor = "0"
        trip = Mock(ending_floor=ending_floor)
        expected_landing_num = 2
        floor_map = FloorMap(
            floors={
                ending_floor: {
                    common_constants.FLOORS_JSON_LANDING_NUM: expected_landing_num - 1
                }
            }
        )
        get_latest_trip_with_ending_floor.return_value = trip
        get_active_map_for_datetime.return_value = floor_map

        result = Trip.get_latest_landing_number(session)

        self.assertEqual(result, expected_landing_num)

    def test_get_latest_landing_returns_landing_number_no_mock(self):
        now = datetime.now(utc)
        ending_floor = "0"
        expected_landing_num = 2

        self.session.add(
            Trip(
                ending_floor=ending_floor,
                start_time=now - timedelta(seconds=5),
                end_time=now,
            )
        )
        self.session.add(
            FloorMap(
                start_time=now,
                floors={
                    ending_floor: {
                        common_constants.FLOORS_JSON_LANDING_NUM: expected_landing_num - 1
                    }
                },
            )
        )

        result = Trip.get_latest_landing_number(self.session)

        self.assertEqual(result, expected_landing_num)

    @patch("utilities.db_utilities.FloorMap.get_active_map_for_datetime")
    def test_get_landing_floor_for_trip_returns_none_if_trip_missing_ending_floor(
        self, get_active_map_for_datetime
    ):
        session = Mock()
        trip = Mock(ending_floor=None)
        floor = get_landing_floor_for_trip(session, trip)

        self.assertIsNone(floor)

    @patch("utilities.db_utilities.FloorMap.get_active_map_for_datetime")
    def test_get_landing_floor_for_trip_calls_get_active_map_with_trip_start_time(
        self, get_active_map_for_datetime
    ):
        session = Mock()
        trip = Mock(ending_floor="0")
        get_landing_floor_for_trip(session, trip)

        get_active_map_for_datetime.assert_called_once_with(session, trip.start_time)

    @patch("utilities.db_utilities.FloorMap.get_active_map_for_datetime")
    def test_get_landing_floor_for_trip_returns_none_if_floor_map_not_found(
        self, get_active_map_for_datetime
    ):
        session = Mock()
        trip = Mock(ending_floor="0")
        get_active_map_for_datetime.return_value = None
        floor = get_landing_floor_for_trip(session, trip)

        self.assertIsNone(floor)

    @patch("utilities.db_utilities.FloorMap.get_active_map_for_datetime")
    def test_get_landing_floor_for_trip_returns_none_if_floor_missing_in_map(
        self, get_active_map_for_datetime
    ):
        session = Mock()
        trip = Mock(ending_floor="1")
        get_active_map_for_datetime.return_value = MagicMock(
            floors={"0": {common_constants.FLOORS_JSON_LANDING_NUM: 1}}
        )
        floor = get_landing_floor_for_trip(session, trip)

        self.assertIsNone(floor)

    @patch("utilities.db_utilities.FloorMap.get_active_map_for_datetime")
    def test_get_landing_floor_for_trip_returns_landing(
        self, get_active_map_for_datetime
    ):
        session = Mock()
        trip = Mock(ending_floor="0")
        get_active_map_for_datetime.return_value = Mock(
            floors={"0": {common_constants.FLOORS_JSON_LANDING_NUM: 2}}
        )
        floor = get_landing_floor_for_trip(session, trip)

        self.assertEqual(floor, 2 + common_constants.FLOORS_USER_TRANSLATION)
