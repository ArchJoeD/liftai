import json
from datetime import datetime, timedelta
from time import sleep
import unittest
from unittest.mock import Mock

import dateutil.parser
from freezegun import freeze_time

from floor_detector.floor_processor import FloorProcessor
from utilities import common_constants
from utilities.db_utilities import engine, session_scope, FloorMap
from utilities.test_utilities import TestUtilities


FLOOR_SCHEMA = common_constants.FLOORS_JSON_SCHEMA
FLOOR_LANDING = common_constants.FLOORS_JSON_LANDING_NUM
FLOOR_ELEVATION = common_constants.FLOORS_JSON_ELEVATION
FLOOR_CUMULATIVE_ERR = common_constants.FLOORS_JSON_CUMULATIVE_ERR
FLOOR_LAST_UPDATED = common_constants.FLOORS_JSON_LAST_UPDATED
ELEVATION_RESET = common_constants.EVENT_SUBTYPE_ELEVATION_RESET
ELEVATION_EVENT = common_constants.EVENT_TYPE_ELEVATION
MISSING_TRIP = common_constants.EVENT_SUBTYPE_MISSING_TRIP
ELEV_CHANGE = common_constants.EVENT_DETAILS_ELEVATION_CHANGE


class TestFloorDetection(unittest.TestCase):
    testutil = TestUtilities()

    def _delete_data(self):
        with engine.connect() as con:
            con.execute("DELETE FROM events;")
            con.execute("DELETE FROM trips;")
            con.execute("DELETE FROM floor_maps;")

    def setUp(self):
        self._delete_data()

    def tearDown(self):
        self._delete_data()

    def delete_map(self):
        with engine.connect() as con:
            con.execute("DELETE FROM floor_maps")

    def set_floor_count(self, floor_count):
        config = {"type": "elevator", common_constants.CONFIG_FLOOR_COUNT: floor_count}
        self.testutil.set_config(config)

    def remove_floor_count(self):
        config = {"type": "elevator"}
        self.testutil.set_config(config)

    def test_update_trip(self):
        self.set_floor_count(10)
        fp = FloorProcessor()
        self.testutil.insert_trip()
        trp = self.testutil.get_last_trip()
        fp._update_trip(trp["id"], "42", 4321)
        trp_again = self.testutil.get_last_trip()
        self.assertEqual(trp_again["id"], trp["id"])
        self.assertEqual(trp_again["ending_floor"], "42")
        self.assertEqual(trp_again["floor_estimated_error"], 4321)

        floor_map = None
        with session_scope() as session:
            floor_map = FloorMap.get_lastest_map(session)

            self.assertIsNotNone(floor_map)
            self.assertEqual(trp_again["floor_map_id"], floor_map.id)

    def test_create_new_floor(self):
        self.set_floor_count(10)
        fp = FloorProcessor()
        before = datetime.now()
        floor = fp._create_new_floor(123, datetime.now())
        after = datetime.now()
        floor_id = list(floor.keys())[0]
        self.assertEqual(floor[floor_id][FLOOR_ELEVATION], 123)
        self.assertEqual(floor[floor_id][FLOOR_CUMULATIVE_ERR], 0)
        self.assertGreaterEqual(
            dateutil.parser.parse(floor[floor_id][FLOOR_LAST_UPDATED]), before
        )
        self.assertLessEqual(
            dateutil.parser.parse(floor[floor_id][FLOOR_LAST_UPDATED]), after
        )

    def test_no_floors_configured(self):
        self.set_floor_count(10)
        fp = FloorProcessor()
        fp._get_floor_count = Mock(return_value=None)
        fp._get_events_and_trips = Mock()
        fp.process_trips()
        fp._get_events_and_trips.assert_not_called()

    def test_create_new_floor_with_no_map(self):
        self.set_floor_count(10)
        fp = FloorProcessor()
        self.delete_map()
        floor = fp._create_new_floor(123, datetime.now())
        floor_id = list(floor.keys())[0]
        self.assertEqual(floor[floor_id][FLOOR_ELEVATION], 123)

    def test_create_and_add_one_floor(self):
        self.set_floor_count(10)
        fp = FloorProcessor()
        floor = fp._create_new_floor(-234, datetime.now())
        fp._add_floor_recompute_landings(floor)
        floors = fp._get_floors()
        floor_id = list(floor.keys())[0]
        self.assertEqual(floors[floor_id][FLOOR_ELEVATION], -234)
        self.assertEqual(floors[floor_id][FLOOR_LANDING], 0)

    def test_create_and_add_multiple_floors(self):
        floors_to_add = 5
        self.set_floor_count(floors_to_add)
        fp = FloorProcessor()
        floor_info = {}
        for elevation_diff in range(floors_to_add):
            floor = fp._create_new_floor(100 + elevation_diff, datetime.now())
            fp._add_floor_recompute_landings(floor)
            floor_info[list(floor.keys())[0]] = 100 + elevation_diff
        floors = fp._get_floors()
        self.assertEqual(len(floors), floors_to_add)
        landing_ids = []
        for fid in floors:
            self.assertEqual(floors[fid][FLOOR_ELEVATION], floor_info[fid])
            self.assertNotIn(floors[fid][FLOOR_LANDING], landing_ids)
            landing_ids.append(floors[fid][FLOOR_LANDING])
        self.assertEqual(
            len(landing_ids), len(set(landing_ids)), "duplicate landing id"
        )

    def test_with_no_floor_count_configuration(self):
        self.remove_floor_count()
        fp = FloorProcessor()
        fp._get_events_and_trips = Mock()
        fp.process_trips()
        fp._get_events_and_trips.assert_not_called()

    def test_floor_count(self):
        self.set_floor_count(10)
        fp = FloorProcessor()
        self.assertEqual(fp._get_floor_count(), 10)
        self.set_floor_count(2)
        self.assertEqual(fp._get_floor_count(), 2)
        self.set_floor_count(100)
        self.assertEqual(fp._get_floor_count(), 100)

    @freeze_time("2015-10-21 06:15:00")
    def test_too_many_floors(self):
        """
        Make sure that if we try to create more floors that the configuration
        that it will create a new map and not add the floor.  We need to freeze
        time because python 3.5 doesn't support generic assert_called_once()
        so we need to tell unittest the exact parameter send to _create_new_map().
        """
        self.set_floor_count(10)
        fp = FloorProcessor()
        fp._create_new_map = Mock()
        fp._get_floor_count = Mock(return_value=2)
        floor = fp._create_new_floor(100, datetime.now())
        self.assertIsNotNone(floor)
        fp._add_floor_recompute_landings(floor)
        floor = fp._create_new_floor(150, datetime.now())
        self.assertIsNotNone(floor)
        fp._add_floor_recompute_landings(floor)
        fp._create_new_map.assert_not_called()
        print("IGNORE the error message immediately below about map misalignment")
        floor = fp._create_new_floor(200, datetime.now())
        self.assertIsNone(floor)
        fp._create_new_map.assert_called_with(datetime.now(), "misalignment")

    def test_trips_with_no_elevation_change(self):
        """
        If a trip happens during a gap in the altimeter data, it gets flagged as having the
        elevation processed but the elevation_change field is NULL.  The elevation is
        actually in an event.  We need to make sure the floor processor can handle this.
        """
        self.set_floor_count(10)
        fp = FloorProcessor()
        # fp creates a map on the first run with last_update = now.  So wait a small time.
        sleep(0.1)
        # Try a normal trip first
        self.testutil.insert_trip(starts_at=datetime.now(), elevation_change=36)
        fp.process_trips()
        # Now a trip without elevation change
        self.testutil.insert_trip(starts_at=datetime.now(), elevation_change=None)
        with engine.connect() as con:
            con.execute(
                "UPDATE trips SET elevation_processed = True where elevation_change IS NULL"
            )
        fp._get_closest_floor = Mock()
        fp.process_trips()
        fp._get_closest_floor.assert_not_called()

    def test_update_floors_and_map(self):
        floors_to_add = 3
        self.set_floor_count(floors_to_add)
        fp = FloorProcessor()
        for elevation_diff in range(floors_to_add):
            floor = fp._create_new_floor(10 + elevation_diff, datetime.now())
            fp._add_floor_recompute_landings(floor)
        floors = fp._get_floors()
        map_update_time = datetime.now() - timedelta(seconds=30)
        maps_last_elevation = 123
        floor_to_modify = list(floors.keys())[1]
        modified_cumulative_err = 5000
        floors[floor_to_modify][FLOOR_CUMULATIVE_ERR] = modified_cumulative_err
        fp._update_floors_and_map(floors, map_update_time, maps_last_elevation)
        self.assertEqual(fp.elevation, maps_last_elevation)
        del fp
        fp = FloorProcessor()
        self.assertEqual(fp.elevation, maps_last_elevation)
        floors = fp._get_floors()
        self.assertEqual(
            floors[floor_to_modify][FLOOR_CUMULATIVE_ERR], modified_cumulative_err
        )
        self.assertEqual(fp._get_last_elevation(), maps_last_elevation)
        self.assertEqual(fp._get_last_update_timestamp(), map_update_time)

    def test_get_closest_floor(self):
        floor_count = 10
        lowest_elevation = -100
        elevation_increments = 40
        self.set_floor_count(floor_count)
        fp = FloorProcessor()
        for i in range(floor_count):
            floor = fp._create_new_floor(
                lowest_elevation + i * elevation_increments, datetime.now()
            )
            fp._add_floor_recompute_landings(floor)
        fid, floors = fp._get_closest_floor(-110)
        self.assertEqual(floors[fid][FLOOR_ELEVATION], -100)
        fid, floors = fp._get_closest_floor(-99)
        self.assertEqual(floors[fid][FLOOR_ELEVATION], -100)
        fid, floors = fp._get_closest_floor(-10)
        self.assertEqual(floors[fid][FLOOR_ELEVATION], -20)
        fid, floors = fp._get_closest_floor(127)
        self.assertEqual(floors[fid][FLOOR_ELEVATION], 140)
        fid, floors = fp._get_closest_floor(1000)
        self.assertEqual(floors[fid][FLOOR_ELEVATION], 260)

    def test_create_new_map(self):
        self.set_floor_count(10)
        fp = FloorProcessor()
        floor = fp._create_new_floor(1234, datetime.now())
        fp._add_floor_recompute_landings(floor)
        new_map_time = datetime.now()
        fp._create_new_map(new_map_time, "test")
        floor = fp._create_new_floor(4321, datetime.now())
        fp._add_floor_recompute_landings(floor)
        with engine.connect() as con:
            map = con.execute(
                "SELECT start_time, last_update, last_elevation, floors "
                "FROM floor_maps ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(map["start_time"], new_map_time)
        self.assertEqual(map["last_update"], new_map_time)
        self.assertEqual(map["last_elevation"], 0)
        added_floor = list(map["floors"].keys())[0]
        self.assertEqual(map["floors"][added_floor][FLOOR_ELEVATION], 4321)

    def test_last_update_timestamp(self):
        start_of_test = datetime.now()
        self.set_floor_count(10)
        fp = FloorProcessor()
        update_time = datetime.now() - timedelta(seconds=20)
        self.assertGreaterEqual(fp._get_last_update_timestamp(), start_of_test)
        fp._set_last_update_timestamp(update_time)
        self.assertEqual(fp._get_last_update_timestamp(), update_time)
        del fp
        fp = FloorProcessor()
        self.assertEqual(fp._get_last_update_timestamp(), update_time)

    def test_update_get_last_elevation(self):
        self.set_floor_count(10)
        fp = FloorProcessor()
        # We don't need to add a floor, but it never gets called without floors.
        floor = fp._create_new_floor(-500, datetime.now())
        fp._add_floor_recompute_landings(floor)
        floor = fp._create_new_floor(200, datetime.now())
        fp._add_floor_recompute_landings(floor)
        fp._update_last_elevation(42)
        self.assertEqual(fp._get_last_elevation(), 42)
        del fp
        fp = FloorProcessor()
        self.assertEqual(fp._get_last_elevation(), 42)

    def test_get_events_and_trips(self):
        self.set_floor_count(20)
        t00 = datetime.now() - timedelta(minutes=10)
        self.testutil.insert_trip(
            starts_at=t00, ends_at=t00 + timedelta(seconds=5), elevation_change=36
        )
        t01 = t00 + timedelta(seconds=30)
        self.testutil.insert_trip(
            starts_at=t01, ends_at=t01 + timedelta(seconds=5), elevation_change=-34
        )
        t02 = t01 + timedelta(seconds=30)
        self.testutil.create_event(
            event_type=ELEVATION_EVENT,
            subtype=MISSING_TRIP,
            details={ELEV_CHANGE: 32},
            occurred_at=t02,
        )
        t03 = t02 + timedelta(seconds=30)
        self.testutil.insert_trip(
            starts_at=t03, ends_at=t03 + timedelta(seconds=5), elevation_change=37
        )
        fp = FloorProcessor()
        fp._set_last_update_timestamp(t00 - timedelta(seconds=1))
        items = fp._get_events_and_trips()
        self.assertEqual(items[0]["type"], "trip")
        self.assertEqual(items[0]["occurred_at"], t00)
        self.assertEqual(items[0]["elevation_change"], 36)
        self.assertEqual(items[1]["type"], "trip")
        self.assertEqual(items[1]["occurred_at"], t01)
        self.assertEqual(items[1]["elevation_change"], -34)
        self.assertEqual(items[2]["type"], MISSING_TRIP)
        self.assertEqual(items[2]["occurred_at"], t02)
        self.assertEqual(items[2]["elevation_change"], 32)
        self.assertEqual(items[3]["type"], "trip")
        self.assertEqual(items[3]["occurred_at"], t03)
        self.assertEqual(items[3]["elevation_change"], 37)
        # Make sure it starts from the right point in time...
        fp._set_last_update_timestamp(t03)
        sleep(0.1)
        t04 = t03 + timedelta(seconds=1)
        self.testutil.create_event(
            event_type=ELEVATION_EVENT,
            subtype=ELEVATION_RESET,
            details={ELEV_CHANGE: 32},
            occurred_at=t04,
        )
        items2 = fp._get_events_and_trips()
        self.assertEqual(items2[0]["type"], ELEVATION_RESET)
        self.assertEqual(items2[0]["occurred_at"], t04)


if __name__ == "__main__":
    unittest.main()
