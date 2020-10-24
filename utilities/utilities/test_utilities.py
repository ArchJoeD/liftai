import os
import json
import unittest
from datetime import datetime, timedelta

import pytz
from sqlalchemy import text

from utilities import common_constants
from utilities.db_utilities import Event, Problem, Session
from utilities.device_configuration import DeviceConfiguration


class TestUtilities:
    very_large_vibration_number = 90000
    ordinary_vibration_number = 3126
    internal_session = False

    def __init__(self, session=None):
        self.internal_session = False if session else True
        self.session = session if session else Session(autocommit=True)

    def __del__(self):
        if self.internal_session:
            self.session.close()

    def create_empty_storage_files(self, storage_folder):
        for filename in os.listdir(storage_folder):
            if filename.endswith(".pkl"):
                f = open(filename, "r+")
                f.seek(0)
                f.truncate()

    def set_config(self, config):
        with open(common_constants.CONFIG_FILE_NAME, "w") as cf:
            json.dump(config, cf)

    def set_config_threshold(self, threshold):
        config = DeviceConfiguration.get_config_data()
        config.update({common_constants.CONFIG_STOPPAGE_THRESHOLD: threshold})
        self.set_config(config)

    def insert_bank_trips(self, trips, bank_size, ts=datetime.now()):
        self.session.execute(
            "INSERT INTO bank_trips (timestamp, bank_trips, bank_elevators) VALUES ('%s', %s, %s)"
            % (ts, trips, bank_size)
        )

    def create_event(
        self,
        event_type=common_constants.EVENT_TYPE_SHUTDOWN,
        subtype=None,
        occurred_at=None,
        detected_at=None,
        source=None,
        confidence=0.00,
        details=None,
        chart_info=None,
    ):
        now = datetime.now()

        if not occurred_at:
            occurred_at = now

        if not detected_at:
            detected_at = now

        event = Event(
            event_type=event_type,
            event_subtype=subtype,
            occurred_at=occurred_at,
            detected_at=detected_at,
            source=source,
            confidence=confidence,
            details=details,
            chart_info=chart_info,
        )
        self.session.add(event)
        self.session.flush()

    def create_problem(
        self,
        problem_type,
        problem_subtype=None,
        created_at=None,
        started_at=None,
        ended_at=None,
        customer_info=None,
        confidence=0.00,
    ):

        now = datetime.now(pytz.utc)

        if not started_at:
            started_at = now

        if not created_at:
            created_at = now

        problem = Problem(
            created_at=created_at,
            started_at=started_at,
            ended_at=ended_at,
            problem_type=problem_type,
            problem_subtype=problem_subtype,
            customer_info=customer_info,
            confidence=confidence,
        )
        self.session.add(problem)
        self.session.flush()

        return problem

    def verify_event(self, event_type, event_subtype, occurred_near):
        occurred_at_min = occurred_near - timedelta(seconds=1)
        occurred_at_max = occurred_near + timedelta(seconds=1)

        count = (
            self.session.query(Event)
            .filter(
                Event.occurred_at >= occurred_at_min,
                Event.occurred_at <= occurred_at_max,
                Event.event_type == event_type,
                Event.event_subtype == event_subtype,
            )
            .count()
        )

        return count == 1

    def get_events(self, start_time):
        rows = (
            self.session.query(Event)
            .filter(Event.occurred_at >= start_time)
            .order_by(Event.id)
        )
        events = [
            {
                "occurred_at": event.occurred_at,
                "detected_at": event.detected_at,
                "source": event.source,
                "event_type": event.event_type,
                "event_subtype": event.event_subtype,
                "confidence": event.confidence,
                "details": event.details,
                "id": event.id,
            }
            for event in rows
        ]
        return events

    def get_problems(self, start_time):
        rows = (
            self.session.query(Problem)
            .filter(Problem.started_at >= start_time)
            .order_by(Problem.id)
        )

        problems = [
            {
                "started_at": problem.started_at,
                "ended_at": problem.ended_at,
                "problem_type": problem.problem_type,
                "problem_subtype": problem.problem_subtype,
                "customer_info": problem.customer_info,
                "confidence": problem.confidence,
                "events": problem.events,
                "id": problem.id,
            }
            for problem in rows
        ]
        return problems

    def remove_test_events_and_problems(self):
        self.session.execute("DELETE FROM events")
        self.session.execute("DELETE FROM problems")

    def get_last_event_or_problem(self, table):
        try:
            event_or_problem = self.session.execute(
                "SELECT * FROM %s ORDER BY id DESC LIMIT 1" % table
            ).fetchone()
        except Exception as ex:
            print("Exception trying to fetch last event: {0}".format(ex))
            raise ex
        return event_or_problem

    def insert_trips_bulk(
        self, con, starts_at=datetime.now() - timedelta(seconds=2), ends_at=None
    ):
        if ends_at is None:
            ends_at = starts_at + timedelta(
                seconds=1
            )  # It's NOT ok to have a zero length run for testing
        self.session.execute(
            "INSERT INTO Trips (start_accel, end_accel, start_time, end_time, is_up)\
                     VALUES (%s, %s, '%s', '%s', %s)"
            % (-1, -1, starts_at, ends_at, True)
        )

    @staticmethod
    def construct_schema_1_vibration_data(
        is_trip=True,
        jerk=0.91,
        p2p_x_95=34.71,
        p2p_y_95=24.10,
        p2p_z_95=50.02,
        p2p_x_max=49.97,
        p2p_y_max=38.81,
        p2p_z_max=87.33,
    ):
        jerk = {} if is_trip else {"jerk": jerk}
        vibration = {
            "p2p_x_95": p2p_x_95,
            "p2p_y_95": p2p_y_95,
            "p2p_z_95": p2p_z_95,
            "p2p_x_max": p2p_x_max,
            "p2p_y_max": p2p_y_max,
            "p2p_z_max": p2p_z_max,
            "x_psd": {
                "f0": 12.0,
                "f1": 145.0,
                "f2": 41.0,
                "f3": 83.0,
                "f4": 203.0,
                "f5": 193.0,
                "f6": 326.0,
                "f7": 759.0,
                "f8": 3433.0,
                "f9": 2221.0,
                "f10": 1653.0,
                "f11": 1759.0,
                "f12": 2202.0,
                "f13": 728.0,
            },
            "y_psd": {
                "f0": 2.0,
                "f1": 816.0,
                "f2": 6.0,
                "f3": 75.0,
                "f4": 107.0,
                "f5": 276.0,
                "f6": 281.0,
                "f7": 588.0,
                "f8": 870.0,
                "f9": 1921.0,
                "f10": 1748.0,
                "f11": 3522.0,
                "f12": 4469.0,
                "f13": 827.0,
            },
            "z_psd": {
                "f0": 1515.0,
                "f1": 735864.0,
                "f2": 2587.0,
                "f3": 4189.0,
                "f4": 1273.0,
                "f5": 489.0,
                "f6": 203.0,
                "f7": 428.0,
                "f8": 1246.0,
                "f9": 1437.0,
                "f10": 2239.0,
                "f11": 4808.0,
                "f12": 4313.0,
                "f13": 759.0,
            },
        }
        return {**jerk, **vibration}

    def insert_trip(
        self,
        starts_at=None,
        ends_at=None,
        is_up=True,
        trip_vib_data=None,
        starting_acceleration_data=None,
        ending_acceleration_data=None,
        elevation_change=None,
        ending_floor_id=None,
        trip_audio=None,
        speed=250,
    ):
        """
        :param starts_at: timestamp
        :param ends_at: timestamp
        :param is_up: Boolean
        :param trip_vib_data: dictionary matching trip vibration schema
        :param accel_data: dictionary containing data for both accelerations as array of dictionaries
        :param elevation_change: normally filled in by elevation app
        :param ending_floor_id: normally filled in by floor detector
        :param trip_audio: contains noise and fft data
        :param speed: trip speed in feet per minute
        :return: None
        """
        accel_ids = []
        accel_data = []
        if starts_at is None:
            starts_at = datetime.now() - timedelta(seconds=30)
        if ends_at is None:
            ends_at = starts_at + timedelta(seconds=20)

        elevation_processed = None if elevation_change is None else True

        if starting_acceleration_data is None:
            starting_acceleration_data = {
                "start_time": starts_at,
                "duration": 2.0,
                "is_start_of_trip": True,
                "is_positive": is_up,
                "vibration_schema": 1,
                "vibration": self.construct_schema_1_vibration_data(
                    is_trip=False, p2p_x_95=self.ordinary_vibration_number
                ),
                "audio": {common_constants.AUDIO_NOISE: 1.2345},
            }
        accel_data.append(starting_acceleration_data)
        if ending_acceleration_data is None:
            ending_acceleration_data = {
                "start_time": ends_at - timedelta(seconds=4),
                "duration": 4.1,
                "is_start_of_trip": False,
                "is_positive": not is_up,
                "vibration_schema": 1,
                "vibration": self.construct_schema_1_vibration_data(
                    is_trip=False, p2p_y_max=self.very_large_vibration_number
                ),
                "audio": {common_constants.AUDIO_NOISE: 5.4321},
            }
        accel_data.append(ending_acceleration_data)
        query_str = text(
            "INSERT INTO accelerations (start_time, duration, is_start_of_trip, "
            "is_positive, vibration_schema, vibration, audio) VALUES (:start_time, :duration, "
            ":is_start_of_trip, :is_positive, :vibration_schema, :vibration, :audio) RETURNING id"
        )
        NUMBER_OF_ACCELERATIONS_PER_TRIP = (
            2  # Starting acceleration and ending acceleration.
        )
        for i in range(NUMBER_OF_ACCELERATIONS_PER_TRIP):
            accel_ids.append(
                self.session.execute(
                    query_str,
                    {
                        "start_time": accel_data[i]["start_time"],
                        "duration": accel_data[i]["duration"],
                        "is_start_of_trip": accel_data[i]["is_start_of_trip"],
                        "is_positive": accel_data[i]["is_positive"],
                        "vibration_schema": accel_data[i]["vibration_schema"],
                        "vibration": json.dumps(accel_data[i]["vibration"]),
                        "audio": json.dumps(accel_data[i]["audio"]),
                    },
                ).first()[0]
            )

        if trip_audio is None:
            trip_audio = {}

        if trip_vib_data is None:
            trip_vib_data = self.construct_schema_1_vibration_data(is_trip=True)
        if ends_at is None:
            ends_at = starts_at + timedelta(
                seconds=3
            )  # It's NOT ok to have a zero length run for testing

        query_str = text(
            "INSERT INTO Trips (start_accel, end_accel, start_time, end_time, is_up, "
            "vibration_schema, vibration, elevation_change, elevation_processed, ending_floor, audio, speed) "
            "VALUES (:start_accel, :end_accel, :start_time, :end_time, :is_up, :vibration_schema, "
            ":vibration, :elevation_change, :elevation_processed, :ending_floor, :audio, :speed)"
        )
        self.session.execute(
            query_str,
            {
                "start_accel": accel_ids[0],
                "end_accel": accel_ids[1],
                "start_time": starts_at,
                "end_time": ends_at,
                "is_up": is_up,
                "vibration_schema": 1,
                "vibration": json.dumps(trip_vib_data),
                "elevation_change": elevation_change,
                "elevation_processed": elevation_processed,
                "ending_floor": ending_floor_id,
                "audio": json.dumps(trip_audio),
                "speed": speed,
            },
        )

    def get_last_trip(self):
        last_trip = self.session.execute(
            "SELECT * FROM trips ORDER BY id DESC LIMIT 1"
        ).first()
        return last_trip

    def delete_trips(self):
        self.session.execute("DELETE FROM trips")
        self.session.execute("DELETE FROM accelerations")

    def delete_bank_trips(self, start_time):
        self.session.execute(
            "DELETE FROM bank_trips WHERE timestamp >= '%s'" % start_time
        )

    def insert_weekly_trips_and_last_trip(
        self, weeks=5, trips=20, include_last_trip=True
    ):
        # First put a last trip into the database which happened 1 hour ago.
        if include_last_trip:
            last_trip_time = datetime.now() - timedelta(hours=1)
            self.insert_trip(
                starts_at=last_trip_time, ends_at=last_trip_time + timedelta(seconds=5)
            )
        # Get a weekly starting time not long after the last trip.
        weekly_time = datetime.now() - timedelta(minutes=50)
        for _ in range(0, weeks):
            weekly_time = weekly_time - timedelta(weeks=1)
            start_time = weekly_time
            for _ in range(0, trips):
                # Create a string of trips starting at the weekly time, one-after-another
                self.insert_trip(
                    starts_at=start_time, ends_at=start_time + timedelta(seconds=5)
                )
                start_time = start_time + timedelta(seconds=10)

    def get_latest_notification(self):
        return self.session.execute(
            "SELECT * FROM data_to_send ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def create_floor_map(
        self, start_time=None, last_update=None, last_elevation=None, num_floors=10
    ):
        """
        Creates a floor map for testing

        By default the landing numbers is the floor_id.  The actual landing the customer
        sees is incremented by common_constants.FLOORS_USER_TRANSLATION
        """
        # Might as well start with elevation set to 0, no absolute reference
        query = text(
            "INSERT INTO floor_maps (start_time, last_update, last_elevation, floors) "
            "VALUES (:start_time, :last_update, :last_elevation, :floors)"
        )
        floors = {
            i: {
                common_constants.FLOORS_JSON_SCHEMA: common_constants.FLOORS_CURRENT_SCHEMA,
                common_constants.FLOORS_JSON_LANDING_NUM: i,
                common_constants.FLOORS_JSON_ELEVATION: i * 10,
                common_constants.FLOORS_JSON_CUMULATIVE_ERR: 0,
                common_constants.FLOORS_JSON_LAST_UPDATED: datetime.now().isoformat(),
            }
            for i in range(num_floors)
        }
        self.session.execute(
            query,
            {
                "start_time": start_time,
                "last_update": last_update,
                "last_elevation": last_elevation,
                "floors": json.dumps(floors),
            },
        )
        pass


class SessionTestCase(unittest.TestCase):
    session = None

    def setUp(self):
        self.session = Session()

    def tearDown(self):
        self.session.rollback()
        self.session.close()
