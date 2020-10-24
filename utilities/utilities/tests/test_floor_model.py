from datetime import datetime, timedelta

from pytz import utc

from utilities.db_utilities import FloorMap
from utilities.test_utilities import SessionTestCase


class TestFloor(SessionTestCase):

    def test_num_floors_property_is_corrrect(self):
        floor_map = FloorMap(floors={"1": {}, "2": {}})

        self.session.add(floor_map)
        self.session.flush()  # Force sync with the database
        self.assertEqual(floor_map.num_floors, 2)

    def test_get_latest_map_returns_none_if_no_latest_map(self):
        self.session.query(FloorMap).delete()  # Ensure no objects

        floor_map = FloorMap.get_lastest_map(self.session)
        self.assertIsNone(floor_map)

    def test_get_latest_map_returns_latest_map(self):
        self.session.query(FloorMap).delete()  # Ensure no objects

        first_floor_map = FloorMap(start_time=datetime.now(utc))
        second_floor_map = FloorMap(start_time=datetime.now(utc) + timedelta(minutes=5))

        self.session.add(first_floor_map)
        latest_floor_map = FloorMap.get_lastest_map(self.session)
        self.assertEqual(first_floor_map, latest_floor_map)

        self.session.add(second_floor_map)
        latest_floor_map = FloorMap.get_lastest_map(self.session)
        self.assertEqual(second_floor_map, latest_floor_map)
