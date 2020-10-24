import pdb
import os
import unittest
from unittest.mock import patch, Mock
from datetime import datetime, timedelta

from sqlalchemy import text

import elevation.constants as constants
import utilities.common_constants as common_constants
from utilities.test_utilities import TestUtilities
from elevation.processor import ElevationProcessor
from utilities.db_utilities import engine
from utilities.misc_utilities import MiscUtilities


ALTIMETER_DATA_SPACING = 1  # units of seconds
FLOOR_DISTANCE = 30


class ElevationTesting(unittest.TestCase):
    testutils = TestUtilities()

    def _delete_data(self):
        self.testutils.delete_trips()
        with engine.connect() as con:
            con.execute("DELETE FROM trips")
            con.execute("DELETE FROM altimeter_data")
            con.execute("DELETE FROM events")

    def setUp(self):
        self._delete_data()
        config = {"type": "elevator"}
        self.testutils.set_config(config)

    def tearDown(self):
        self._delete_data()

    def create_trip_based_altimeter_data(self, start_time, end_time):
        """
        Add altimeter data that changes during each trip in the database.  The altimeter pattern is to alternate
        between up and down, going one floor further than the last trip.
        Start at floor N, then N+1, then N-1, then N+2, then N-2, etc.
        """
        query = (
            "INSERT INTO altimeter_data (timestamp, altitude_x16, temperature) VALUES "
            "(:timestamp, :altitude, 85)"
        )
        trip_check_query = "SELECT COUNT(*) FROM trips WHERE start_time < :this_time AND end_time > :this_time;"
        with engine.connect() as con:
            t = start_time
            alt = 0
            sign = +1
            trip_iteration = 0
            in_trip = False

            while t <= end_time:
                if con.execute(text(trip_check_query), this_time=t).first()[0] > 0:
                    if not in_trip:
                        trip_iteration += 1
                        alt += FLOOR_DISTANCE * sign * trip_iteration
                        sign = -sign
                        in_trip = True
                else:
                    in_trip = False
                con.execute(text(query), timestamp=t, altitude=alt)
                t = t + timedelta(seconds=ALTIMETER_DATA_SPACING)

    def create_some_trips(self, initial_trip_count, trip_info):
        # Add some initial trips to get past the number of skipped trips.
        for i in range(initial_trip_count):
            self.testutils.insert_trip(
                starts_at=datetime.now() - timedelta(hours=24) + timedelta(minutes=i)
            )
        # Now add the trips that the algorithm will operate on.
        for start_end in trip_info:
            self.testutils.insert_trip(starts_at=start_end[0], ends_at=start_end[1])

    def get_event_count(self):
        with engine.connect() as con:
            return con.execute("SELECT COUNT(*) FROM events").first()[0]

    def verify_reset_elevation(self, gap_end):
        # Verify the results after a long gap.
        query = text(
            "SELECT event_subtype, occurred_at FROM events WHERE event_type = :elevation_type ORDER BY id DESC"
        )
        with engine.connect() as con:
            events = con.execute(
                query, elevation_type=common_constants.EVENT_TYPE_ELEVATION
            ).fetchall()
        # We should get two events: gap end, elevation reset
        self.assertEqual(len(events), 2)
        for event in events:
            self.assertIn(
                event["event_subtype"],
                {
                    common_constants.EVENT_SUBTYPE_PROCESSED_GAP,
                    common_constants.EVENT_SUBTYPE_ELEVATION_RESET,
                },
            )
            if event["event_subtype"] == common_constants.EVENT_SUBTYPE_ELEVATION_RESET:
                self.assertEqual(event["occurred_at"], gap_end)

    def test_missed_trips(self):
        occurred_at = datetime.now() - timedelta(minutes=1)
        elevation_change = 202
        ep = ElevationProcessor()
        ep._missed_trips(occurred_at, elevation_change)
        event = self.testutils.get_last_event_or_problem("events")
        self.assertIsNone(event, "The elevation app shouldn't be creating missed trips events any more.")

    def test_elevation_reset(self):
        occurred_at = datetime.now() - timedelta(minutes=8)
        ep = ElevationProcessor()
        ep._elevation_reset(occurred_at)
        self.assertTrue(
            self.testutils.verify_event(
                common_constants.EVENT_TYPE_ELEVATION,
                common_constants.EVENT_SUBTYPE_ELEVATION_RESET,
                occurred_at,
            )
        )

    def test_processed_gaps(self):
        end_of_gap = datetime.now() - timedelta(minutes=7)
        ep = ElevationProcessor()
        ep._processed_gaps(end_of_gap)
        event = self.testutils.get_last_event_or_problem("events")
        self.assertEqual(event["occurred_at"], end_of_gap)
        self.assertEqual(event["event_type"], common_constants.EVENT_TYPE_ELEVATION)
        self.assertEqual(
            event["event_subtype"], common_constants.EVENT_SUBTYPE_PROCESSED_GAP
        )

    def test_get_elevation_change(self):
        trip_start = datetime.now() - timedelta(minutes=5)
        trip_end = trip_start + timedelta(seconds=10)
        trip_info = ((trip_start, trip_end),)
        self.create_some_trips(0, trip_info)
        self.create_trip_based_altimeter_data(
            trip_start - timedelta(seconds=5), trip_end + timedelta(seconds=5)
        )
        ep = ElevationProcessor()
        elevation_change = ep._get_elevation_change(trip_start, trip_end)
        self.assertEqual(elevation_change, FLOOR_DISTANCE)

    def test_handle_any_gaps_no_gaps(self):
        ep = ElevationProcessor()
        ep.handle_any_gaps()
        self.assertEqual(
            self.get_event_count(),
            0,
            "handle_any_gaps() without any gaps shouldn't generate an event",
        )

    def test_handle_any_gaps_altimeter(self):
        self.run_handle_any_gaps_full_gap(
            common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP
        )

    def test_handle_any_gaps_accelerometer(self):
        self.run_handle_any_gaps_full_gap(
            common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP
        )

    def run_handle_any_gaps_full_gap(self, event_type):
        ep = ElevationProcessor()
        gap_end = datetime.now() - timedelta(minutes=4)
        self.testutils.create_event(
            event_type=event_type,
            subtype=common_constants.EVENT_SUBTYPE_GAP_START,
            occurred_at=gap_end - timedelta(minutes=1),
        )
        self.testutils.create_event(
            event_type=event_type,
            subtype=common_constants.EVENT_SUBTYPE_GAP_END,
            occurred_at=gap_end,
        )
        ep.handle_any_gaps()
        self.assertTrue(
            self.testutils.verify_event(
                common_constants.EVENT_TYPE_ELEVATION, common_constants.EVENT_SUBTYPE_PROCESSED_GAP, gap_end
            )
        )

    def test_handle_any_gaps_end_altimeter_gap(self):
        self.run_handle_any_gaps_end_gap(common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP)

    def test_handle_any_gaps_end_accelerometer_gap(self):
        self.run_handle_any_gaps_end_gap(
            common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP
        )

    def run_handle_any_gaps_end_gap(self, event_type):
        # If the start of a gap is long ago, 
        # FYI: There won't be any detected trips within the gap (requires both accel and altim).
        trip_start_time = datetime.now() - timedelta(
            minutes=constants.OLDEST_ALTIMETER_DATA + 3
        )
        self.testutils.insert_trip(starts_at=trip_start_time)
        ep = ElevationProcessor()
        gap_end = datetime.now() - timedelta(minutes=2)
        self.testutils.create_event(
            event_type=event_type,
            subtype=common_constants.EVENT_SUBTYPE_GAP_END,
            occurred_at=gap_end,
        )
        ep.handle_any_gaps()
        self.verify_reset_elevation(gap_end)

    def test_handle_any_gaps_start_then_end_altimeter_gap(self):
        self.run_handle_any_gaps_start_then_end_gap(
            common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP, False
        )

    def test_handle_any_gaps_start_then_end_accelerometer_gap(self):
        self.run_handle_any_gaps_start_then_end_gap(
            common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP, True
        )

    def run_handle_any_gaps_start_then_end_gap(self, event_type, accelerometer):
        ep = ElevationProcessor()
        gap_start = datetime.now() - timedelta(minutes=4)
        gap_end = gap_start + timedelta(minutes=1)
        # Start of gap
        self.testutils.create_event(
            event_type=event_type,
            subtype=common_constants.EVENT_SUBTYPE_GAP_START,
            occurred_at=gap_start,
        )
        # Verify nothing happens
        for _ in range(3):
            ep.handle_any_gaps()
        self.assertEqual(self.get_event_count(), 1)
        # End of gap
        self.testutils.create_event(
            event_type=event_type,
            subtype=common_constants.EVENT_SUBTYPE_GAP_END,
            occurred_at=gap_end,
        )
        ep.handle_any_gaps()
        with engine.connect() as con:
            query = text(
                "SELECT event_subtype FROM events WHERE event_type = :elevation_type ORDER BY id DESC"
            )
            events = con.execute(
                query, elevation_type=common_constants.EVENT_TYPE_ELEVATION
            ).fetchall()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_subtype"],common_constants.EVENT_SUBTYPE_PROCESSED_GAP)


    def test_handle_any_gaps_overlapping_altimeter_first(self):
        self.run_handle_any_gaps_overlapping(
            common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP,
            common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP,
        )

    def test_handle_any_gaps_overlapping_accelerometer_first(self):
        self.run_handle_any_gaps_overlapping(
            common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP,
            common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP,
        )

    def run_handle_any_gaps_overlapping(self, gap1, gap2):
        ep = ElevationProcessor()
        gap1_start = datetime.now() - timedelta(minutes=10)
        gap2_start = gap1_start + timedelta(minutes=1)
        gap2_end = gap2_start + timedelta(minutes=1)
        gap1_end = gap2_end + timedelta(minutes=1)
        self.create_trip_based_altimeter_data(
            gap1_start - timedelta(seconds=3), gap1_end + timedelta(seconds=3)
        )
        # Start of gap 1
        self.testutils.create_event(
            event_type=gap1,
            subtype=common_constants.EVENT_SUBTYPE_GAP_START,
            occurred_at=gap1_start,
        )
        # Verify nothing happens
        for _ in range(3):
            ep.handle_any_gaps()
        self.assertEqual(self.get_event_count(), 1)
        # Start of gap 2
        self.testutils.create_event(
            event_type=gap2,
            subtype=common_constants.EVENT_SUBTYPE_GAP_START,
            occurred_at=gap2_start,
        )
        # Verify nothing happens
        for _ in range(3):
            ep.handle_any_gaps()
        self.assertEqual(self.get_event_count(), 2)
        # End of gap 2
        self.testutils.create_event(
            event_type=gap2,
            subtype=common_constants.EVENT_SUBTYPE_GAP_END,
            occurred_at=gap2_end,
        )
        # Verify nothing happens
        for _ in range(3):
            ep.handle_any_gaps()
        self.assertEqual(self.get_event_count(), 3)
        # End of gap 1
        self.testutils.create_event(
            event_type=gap1,
            subtype=common_constants.EVENT_SUBTYPE_GAP_END,
            occurred_at=gap1_end,
        )
        ep.handle_any_gaps()
        self.assertTrue(
            self.testutils.verify_event(
                common_constants.EVENT_TYPE_ELEVATION,
                common_constants.EVENT_SUBTYPE_PROCESSED_GAP,
                gap1_end,
            )
        )
        self.assertEqual(
            self.get_event_count(),
            5,
            "Should only get gap processed events",
        )

    # TODO: It would be good to add tests with overlapping consecutive gaps: gap1_start, gap2_start, gap1_end, gap2_end

    def test_handle_any_gaps_long_gap(self):
        ep = ElevationProcessor()
        gap_start = datetime.now() - timedelta(
            minutes=constants.MAX_SENSOR_GAP + 3
        )
        gap_end = gap_start + timedelta(minutes=constants.MAX_SENSOR_GAP + 1)
        self.testutils.create_event(
            event_type=common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP,
            subtype=common_constants.EVENT_SUBTYPE_GAP_START,
            occurred_at=gap_start,
        )
        self.testutils.create_event(
            event_type=common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP,
            subtype=common_constants.EVENT_SUBTYPE_GAP_END,
            occurred_at=gap_end,
        )
        ep.handle_any_gaps()
        self.verify_reset_elevation(gap_end)

    def test_update_sensor_gap_status(self):
        logger = Mock()
        altim, accel = MiscUtilities.get_sensor_gap_status(engine, logger)
        self.assertTrue(altim, "Altimeter should not be in a gap with no events")
        self.assertTrue(accel, "Accelerometer should not be in a gap with no events")
        self.testutils.create_event(
            event_type=common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP,
            subtype=common_constants.EVENT_SUBTYPE_GAP_START,
            occurred_at=datetime.now()
            - timedelta(minutes=constants.OLDEST_ALTIMETER_DATA + 1),
        )
        altim, accel = MiscUtilities.get_sensor_gap_status(engine, logger)
        self.assertFalse(altim, "Altimeter should be in a gap with one event")
        self.assertTrue(accel, "Accelerometer should not be in a gap")
        self.testutils.create_event(
            event_type=common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP,
            subtype=common_constants.EVENT_SUBTYPE_GAP_START,
            occurred_at=datetime.now()
            - timedelta(minutes=constants.OLDEST_ALTIMETER_DATA + 2000),
        )
        altim, accel = MiscUtilities.get_sensor_gap_status(engine, logger)
        self.assertFalse(altim, "Altimeter should be in a gap")
        self.assertFalse(accel, "Accelerometer should be in a gap")

    def test_ignoring_old_event(self):
        self.testutils.create_event(
            event_type=common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP,
            subtype=common_constants.EVENT_SUBTYPE_GAP_END,
            occurred_at=datetime.now()
            - timedelta(minutes=constants.OLDEST_ALTIMETER_DATA + 1),
        )
        ep = ElevationProcessor()
        self.assertEqual(
            self.get_event_count(),
            1,
            "handle_any_gaps() should ignore old events"
        )

    def test_ignore_events_before_last_elevation_event(self):
        self.testutils.create_event(
            event_type=common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP,
            subtype=common_constants.EVENT_SUBTYPE_GAP_END,
            occurred_at=datetime.now() - timedelta(minutes=5),
        )
        self.testutils.create_event(
            event_type=common_constants.EVENT_TYPE_ELEVATION,
            subtype="Does not matter what this is",
            occurred_at=datetime.now() - timedelta(minutes=4),
        )
        ep = ElevationProcessor()
        self.assertEqual(
            self.get_event_count(),
            2,
            "handle_any_gaps() should ignore events before the last elevation event"
        )

if __name__ == "__main__":
    unittest.main()
