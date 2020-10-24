import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, call, Mock

from pytz import utc

from utilities.db_utilities import FloorMap, Trip
from utilities.floor_detection import can_use_floor_data
from utilities.test_utilities import SessionTestCase


@patch("utilities.floor_detection.Trip.filter_trips_after")
@patch("utilities.floor_detection.FloorMap.get_lastest_map")
@patch("utilities.floor_detection.DeviceConfiguration.get_floor_count")
class TestFloorDetectionCanUseFloorData(unittest.TestCase):
    def test_returns_false_when_no_config(
        self, get_floor_count, get_lastest_map, filter_trips_after
    ):
        get_floor_count.return_value = None
        session = Mock()

        result = can_use_floor_data(session)
        get_floor_count.assert_has_calls([call()])
        self.assertFalse(result)

    def test_returns_false_when_no_floor_map(
        self, get_floor_count, get_lastest_map, filter_trips_after
    ):
        get_floor_count.return_value = 5
        get_lastest_map.return_value = None
        session = Mock()

        result = can_use_floor_data(session)
        get_lastest_map.assert_has_calls([call(session)])
        self.assertFalse(result)

    def test_returns_true_when_floor_map_eq_num_floors(
        self, get_floor_count, get_lastest_map, filter_trips_after
    ):
        get_floor_count.return_value = 1
        get_lastest_map.return_value = FloorMap(floors={"0": {}})
        session = Mock()

        result = can_use_floor_data(session)
        self.assertTrue(result)

    def test_only_checks_trips_after_the_most_recent_floor_map(
        self, get_floor_count, get_lastest_map, filter_trips_after
    ):
        floor_map = FloorMap(start_time=Mock(), floors={"0": {}})
        get_floor_count.return_value = 2
        get_lastest_map.return_value = floor_map
        filter_trips_after.return_value.count.return_value = (
            39  # 20 * 2 = 40 minimum trips needed
        )
        session = Mock()

        can_use_floor_data(session)
        filter_trips_after.assert_has_calls(
            [call(session.query(Trip), floor_map.start_time), call().count(),],
        )

    def test_returns_false_when_floor_map_not_eq_num_floors_and_min_trip_threshold_not_met(
        self, get_floor_count, get_lastest_map, filter_trips_after
    ):
        floor_map = FloorMap(start_time=Mock(), floors={"0": {}})
        get_floor_count.return_value = 2
        get_lastest_map.return_value = floor_map
        filter_trips_after.return_value.count.return_value = (
            39  # 20 * 2 = 40 minimum trips needed
        )
        session = Mock()

        result = can_use_floor_data(session)
        self.assertFalse(result)

    def test_returns_true_when_floor_map_not_eq_num_floors_and_min_trip_threshold_met(
        self, get_floor_count, get_lastest_map, filter_trips_after
    ):
        get_floor_count.return_value = 2
        get_lastest_map.return_value = FloorMap(floors={"0": {}})
        filter_trips_after.return_value.count.return_value = (
            40  # 20 * 2 = 40 minimum trips needed
        )
        session = Mock()

        result = can_use_floor_data(session)
        self.assertTrue(result)


class TestFloorDetectionCanUseFloorDataIntegration(SessionTestCase):

    @patch("utilities.floor_detection.DeviceConfiguration.get_floor_count")
    def test_returns_true_if_floor_count_eq_count_from_floor_map(self, get_floor_count):
        get_floor_count.return_value = 2
        self.session.add(FloorMap(floors={"1": {}, "2": {}}))
        self.assertTrue(can_use_floor_data(self.session))

    @patch("utilities.floor_detection.DeviceConfiguration.get_floor_count")
    def test_returns_false_if_floor_count_not_met_and_insufficient_trips(
        self, get_floor_count
    ):
        get_floor_count.return_value = 2
        minimum_number_of_trips_until_trusted = 20 * 2
        now = datetime.now(utc)

        self.session.add(FloorMap(floors={"1": {}}, start_time=now))

        for i in range(minimum_number_of_trips_until_trusted - 1):
            self.session.add(Trip(end_time=now + timedelta(seconds=i + 1)))

        self.assertFalse(can_use_floor_data(self.session))

    @patch("utilities.floor_detection.DeviceConfiguration.get_floor_count")
    def test_returns_true_if_floor_count_not_met_and_sufficient_trips(
        self, get_floor_count
    ):
        get_floor_count.return_value = 2
        minimum_number_of_trips_until_trusted = 20 * 2
        now = datetime.now(utc)

        self.session.add(FloorMap(floors={"1": {}}, start_time=now))

        for i in range(minimum_number_of_trips_until_trusted):
            self.session.add(Trip(end_time=now + timedelta(seconds=i + 1)))

        self.assertTrue(can_use_floor_data(self.session))
