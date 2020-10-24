import os
import random
import json
from datetime import datetime
import unittest

from floor_detector.floor_processor import FloorProcessor
import floor_detector.constants as constants
from utilities import common_constants
from utilities.db_utilities import engine
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

RANDOM_SEED = 15
ITERATIONS = 100000
ELEVATION_NOISE_RANGE = 5
TRIP_PROBABILITY = 0.99
MISSING_TRIP_PROBABILITY = 0.007  # probability of missing trip, given we selected trip.
MAP_RESET_PROBABILITY = 0.005
APP_RESTART_PROBABILITY = 0.002
# TODO: Floor drift is currently turned off.
FLOOR_DRIFT_PROBABILITY = 0.0  # probability, given a trip to a pre-visited floor
FLOOR_DRIFT_INCREMENT = 0


class TestFloorsMonteCarlo(unittest.TestCase):
    testutil = TestUtilities()
    fp = None
    curr_floor = None
    floor_visited = None
    floor_map = None

    @classmethod
    def setUpClass(cls):
        random.seed(RANDOM_SEED)
        print(
            "Setting up for testing, NOTE THAT THESE TESTS STOP THE EXISTING SYSTEM AND ARE DESTRUCTIVE..."
        )
        os.system("sudo systemctl stop floor.service")
        os.system("sudo systemctl stop anomalydetector.service")
        os.system("sudo systemctl stop elevation.service")

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

    def test_floors_monte_carlo(self):
        self.floor_map = [-50, 0, 50, 100, 150, 200, 250, 300, 350, 400]
        config = {
            "type": "elevator",
            common_constants.CONFIG_FLOOR_COUNT: len(self.floor_map),
        }
        self.testutil.set_config(config)
        self.fp = FloorProcessor()
        self.set_initial_floor()
        print(
            "Starting floor {0} at elevation {1}".format(
                self.curr_floor, self.floor_map[self.curr_floor]
            )
        )
        for self.iteration in range(ITERATIONS):
            self.run_one_iteration()
            if self.iteration % 100 == 0:
                # Every now and then remove old data
                with engine.connect() as con:
                    con.execute("DELETE FROM events;")
                    con.execute("DELETE FROM trips;")

    def run_one_iteration(self):
        missed_trip_flag = False
        new_floor_flag = False
        r = random.uniform(0.0, 1.0)
        if r < TRIP_PROBABILITY:
            next_floor = (
                self.curr_floor + random.randint(1, len(self.floor_map) - 1)
            ) % len(self.floor_map)
            if not self.floor_visited[next_floor]:
                new_floor_flag = True
                self.floor_visited[next_floor] = True
                # Don't add noise to the initial visit to floor
                elevation_noise = 0
            else:
                elevation_noise = -ELEVATION_NOISE_RANGE + random.randint(
                    0, ELEVATION_NOISE_RANGE * 2
                )
            elevation_change = (
                elevation_noise
                + self.floor_map[next_floor]
                - self.floor_map[self.curr_floor]
            )
            r2 = random.uniform(0.0, 1.0)
            if (not new_floor_flag) and r2 < MISSING_TRIP_PROBABILITY:
                # Every now and then we miss the trip, but not on first visit
                print("MISSING TRIP with elevation change {0}".format(elevation_change))
                missed_trip_flag = True
                self.testutil.create_event(
                    event_type=ELEVATION_EVENT,
                    subtype=MISSING_TRIP,
                    details={ELEV_CHANGE: elevation_change},
                    occurred_at=datetime.now(),
                )
                # When we can't lock into a floor, the passing threshold is much higher.
                pass_threshold = constants.MIN_FLOOR_SEPARATION - 1
            else:
                self.testutil.insert_trip(
                    starts_at=datetime.now(), elevation_change=elevation_change
                )
                pass_threshold = constants.MIN_FLOOR_SEPARATION - 5
            self.fp.process_trips()
            self.assertLessEqual(
                abs(self.fp.elevation - self.floor_map[next_floor]), pass_threshold
            )
            print(
                "{0} PASS: {1} vs simulator {2}, floor {3}, elevation {4}".format(
                    self.iteration,
                    self.fp.elevation,
                    self.floor_map[next_floor],
                    next_floor,
                    elevation_change,
                )
            )
            self.curr_floor = next_floor
        if r < MAP_RESET_PROBABILITY:
            print("RESETTING THE MAP")
            self.testutil.create_event(
                event_type=ELEVATION_EVENT,
                subtype=ELEVATION_RESET,
                occurred_at=datetime.now(),
            )
            self.set_initial_floor()
            self.fp.process_trips()
        r4 = random.uniform(0.0, 1.0)
        if r4 < APP_RESTART_PROBABILITY:
            print("RESTARTING THE APP")
            del self.fp
            self.fp = FloorProcessor()
        r3 = random.uniform(0.0, 1.0)
        if r3 < FLOOR_DRIFT_PROBABILITY:
            floor_to_move = random.randint(0, len(self.floor_map) - 1)
            drift = (
                -FLOOR_DRIFT_INCREMENT
                if floor_to_move % 2 == 0
                else FLOOR_DRIFT_INCREMENT
            )
            # For simplicity we don't drift all the floors.
            if drift > 0 and floor_to_move < len(self.floor_map) - 1:
                if self.floor_map[floor_to_move] < self.floor_map[floor_to_move + 1] - (
                    constants.MIN_FLOOR_SEPARATION + FLOOR_DRIFT_INCREMENT + 1
                ):
                    self.floor_map[floor_to_move] += drift
            if drift < 0 and floor_to_move > 0:
                if self.floor_map[floor_to_move - 1] < self.floor_map[floor_to_move] - (
                    constants.MIN_FLOOR_SEPARATION + FLOOR_DRIFT_INCREMENT + 1
                ):
                    self.floor_map[floor_to_move] += drift

            if floor_to_move == 0:
                self.floor_map[0] -= FLOOR_DRIFT_INCREMENT
                print("MOVED FLOOR {0} down by {1}".format(0, FLOOR_DRIFT_INCREMENT))
            else:
                if (
                    self.floor_map[floor_to_move] - self.floor_map[floor_to_move - 1]
                    > constants.MIN_FLOOR_SEPARATION + FLOOR_DRIFT_INCREMENT + 2
                ):
                    self.floor_map[floor_to_move] -= FLOOR_DRIFT_INCREMENT
                    print(
                        "MOVED FLOOR {0} down by {1}".format(
                            floor_to_move, FLOOR_DRIFT_INCREMENT
                        )
                    )

    def set_initial_floor(self):
        self.curr_floor = 1  # The test is simpler if we start at a 0 elevation than ignoring the first trip
        self.floor_visited = [
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        ]


if __name__ == "__main__":
    unittest.main()
