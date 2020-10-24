import os
import csv
import unittest
from unittest.mock import ANY, patch, MagicMock
from collections import namedtuple
from datetime import datetime, timedelta, timezone
import random

from sqlalchemy.sql import text

from utilities import common_constants
from utilities import test_utilities
from utilities.db_utilities import session_scope, engine, Trip, Acceleration
from trips.trip_processor import (
    AccelSample,
    AltimDetectedEnd,
    AltimDetectedStart,
    AltimeterReset,
    IncrSavePoint,
    InsufficientAccelSamples,
    TripData,
    TripProcessor,
)
import trips.constants as constants


SAMPLES_PER_ROW = 2048
SAMPLES_PER_SECOND = 48000

TRIP_LEN = int(3 * constants.MILLISEC_PER_SEC / constants.ACCEL_SAMPLE_PERIOD)
ACCEL_LEN = int(1.0 * constants.MILLISEC_PER_SEC / constants.ACCEL_SAMPLE_PERIOD)
ALTIM_SLOPE = 2

SensorData = namedtuple(
    "SensorData", ["timestamp", "x_data", "y_data", "z_data", "altitude_x16"]
)


class TripsTests(unittest.TestCase):
    testutils = test_utilities.TestUtilities()

    def _delete_data(self):
        engine.execute(
            "DELETE FROM trips; "
            "DELETE FROM accelerations; "
            "DELETE FROM audio; "
            "DELETE FROM accelerometer_data; "
            "DELETE FROM altimeter_data;"
            "DELETE FROM events;"
        )

    def setUp(self):
        self._delete_data()

    def tearDown(self):
        self._delete_data()

    def create_noise_data(self, start_time, end_time, noise_level):
        """
        Returns the total number of samples and overall noise level for the interval.
        """
        total_samples = 0
        total_noise = 0.0
        tstamp = start_time
        milliseconds_per_row = 1000 * SAMPLES_PER_ROW / SAMPLES_PER_SECOND

        query = text(
            "INSERT INTO audio (timestamp, nsamples, sum_of_squares) VALUES (:time, :nsamples, :noise);"
        )
        with engine.connect() as con:
            while tstamp < end_time:
                con.execute(
                    query, time=tstamp, nsamples=SAMPLES_PER_ROW, noise=noise_level
                )
                tstamp += timedelta(milliseconds=milliseconds_per_row)
                total_samples += SAMPLES_PER_ROW
                total_noise += noise_level

        return total_samples, total_noise

    def verify_noise(self, table_name, id, expected_noise):
        query = text("SELECT audio FROM {0} WHERE id = :id".format(table_name))
        with engine.connect() as con:
            audio = con.execute(query, id=id).first()[0]
        noise = audio[common_constants.AUDIO_NOISE]
        self.assertAlmostEqual(noise, expected_noise, places=2)

    def test_accel_noise(self):
        start_time = datetime.now() - timedelta(seconds=2)
        end_time = datetime.now()

        # Create noise during the acceleration
        total_samples, total_noise = self.create_noise_data(start_time, end_time, 15)
        # Create noise outside the time period of the acceleration
        self.create_noise_data(start_time - timedelta(seconds=2), start_time, 10.0)
        self.create_noise_data(end_time, end_time + timedelta(seconds=2), 11.0)

        with session_scope() as session:
            accel = Acceleration.init_with_audio(
                session,
                start_time=start_time,
                duration=1234,
                is_start_of_trip=True,
                is_positive=True,
            )
            session.add(accel)
            session.commit()
            self.verify_noise("accelerations", accel.id, total_noise / total_samples)

    def test_trip_noise(self):
        start_time = datetime.now() - timedelta(seconds=16)  # start starting accel
        start_steady_state_time = start_time + timedelta(seconds=2)  # traveling
        end_steady_state_time = start_time + timedelta(seconds=12)  # start ending accel
        end_time = start_time + timedelta(seconds=14)  # end ending accel

        # Create noise during the trip
        trip_samples, trip_noise = self.create_noise_data(
            start_steady_state_time, end_steady_state_time, 12
        )
        # Create noise during the accelerations
        start_accel_samples, start_accel_noise = self.create_noise_data(
            start_time, start_steady_state_time, 9.0
        )
        end_accel_samples, end_accel_noise = self.create_noise_data(
            end_steady_state_time, end_time, 18.0
        )
        # Create noise outside of the trip
        self.create_noise_data(start_time - timedelta(seconds=1), start_time, 9.0)
        self.create_noise_data(end_time, end_time + timedelta(seconds=1), 18.0)
        with session_scope() as session:
            start_accel = Acceleration.init_with_audio(
                session,
                start_time=start_time,
                duration=1234,
                is_start_of_trip=True,
                is_positive=True,
            )
            end_accel = Acceleration.init_with_audio(
                session,
                start_time=end_steady_state_time,
                duration=4321,
                is_start_of_trip=False,
                is_positive=False,
            )
            session.add(start_accel)
            session.add(end_accel)
            session.commit()
            trip = Trip.init_with_audio(
                session,
                start_accel=start_accel.id,
                end_accel=end_accel.id,
                start_time=start_time,
                end_time=end_time,
            )
            session.add(trip)
            session.commit()
            self.verify_noise(
                "accelerations", start_accel.id, start_accel_noise / start_accel_samples
            )
            self.verify_noise(
                "accelerations", end_accel.id, end_accel_noise / end_accel_samples
            )
            self.verify_noise("trips", trip.id, trip_noise / trip_samples)

    def test_get_peak2peak_vibration(self):
        random.seed(1234)
        X_RANGE = 38.0
        Y_RANGE = 150.0
        Z_RANGE = 2000.0
        BUFFER_SIZE = 3000
        with session_scope() as session:
            tp = TripProcessor(session)
            for _ in range(BUFFER_SIZE):
                tp.accel_data.append(
                    AccelSample(
                        timestamp=datetime.now(),
                        x=float(random.uniform(-X_RANGE/2.0, X_RANGE/2.0)),
                        y=float(random.uniform(0.0, Y_RANGE)),
                        z=float(random.uniform(-Z_RANGE, 0.0)),
                        altim=42
                    )
                )
            start_index = 100
            end_index = BUFFER_SIZE - 100
            json = tp._get_peak2peak_vibration(start_index, end_index)
            self.assertAlmostEqual(json["p2p_x_95"], TripProcessor._convert_raw_accel_to_milligs(X_RANGE) * 0.9, delta=X_RANGE/8)
            self.assertAlmostEqual(json["p2p_y_95"], TripProcessor._convert_raw_accel_to_milligs(Y_RANGE) * 0.9, delta=Y_RANGE/8)
            self.assertAlmostEqual(json["p2p_z_95"], TripProcessor._convert_raw_accel_to_milligs(Z_RANGE) * 0.9, delta=Z_RANGE/8)
            self.assertAlmostEqual(json["p2p_x_max"], TripProcessor._convert_raw_accel_to_milligs(X_RANGE), delta=X_RANGE/8)
            self.assertAlmostEqual(json["p2p_y_max"], TripProcessor._convert_raw_accel_to_milligs(Y_RANGE), delta=Y_RANGE/8)
            self.assertAlmostEqual(json["p2p_z_max"], TripProcessor._convert_raw_accel_to_milligs(Z_RANGE), delta=Z_RANGE/8)

    def test_get_jerk(self):
        random.seed(4321)
        PERCENT_ACCURACY = 15
        BUFFER_SIZE = 1000
        JERK_START_INDEX = 100
        JERK_SLOPE = 8
        jerk_value = 0.0
        
        with session_scope() as session:
            tp = TripProcessor(session)
            # Populate the buffer with random data in the Z axis
            # But add a line with slope -10 in the middle
            for i in range(BUFFER_SIZE):
                if i >= JERK_START_INDEX and i < JERK_START_INDEX + constants.NEII_JERK_WINDOW_SIZE:
                    # Add a section with downward jerk in the middle
                    tp.accel_data.append(
                        AccelSample(
                            timestamp=datetime.now(),
                            x = 0.0,
                            y = 0.0,
                            z = jerk_value,
                            altim = 42
                    ))
                    jerk_value -= JERK_SLOPE
                else:
                    tp.accel_data.append(
                        AccelSample(
                            timestamp=datetime.now(),
                            x=0.0,
                            y=0.0,
                            z=float(random.uniform(-30.0, 30.0)),
                            altim=42
                        )
                    )

            expected_jerk = TripProcessor._convert_raw_accel_slope_to_meters_per_sec_cubed(JERK_SLOPE)
            for start_index in range( 20, 60, 7):
                jerk = tp._get_jerk(start_index, BUFFER_SIZE - 50)["jerk"]
                self.assertAlmostEqual(jerk, expected_jerk, delta=expected_jerk*(PERCENT_ACCURACY/100), msg="Failed at starting index {0}".format(start_index))

    def create_altimeter_and_accelerometer_data(self):
        query1 = text(
            "INSERT INTO accelerometer_data (timestamp, x_data, y_data, z_data) "
            "VALUES (:time1, 1.234, 4.321, 1.111), "
            "       (:time2, 2.222, 3.333, 4.444), "
            "       (:time4, 0.123, 0.222, 100.1);"
        )
        query2 = text(
            "INSERT INTO altimeter_data (timestamp, altitude_x16) "
            "VALUES (:time0, 3456), "
            "       (:time3, 6543);"
        )
        t = []
        start_time = datetime.now() - timedelta(
            seconds=30
        )  # must be sufficiently in the past
        for i in range(5):
            t.append(start_time + timedelta(seconds=i))
        with engine.connect() as con:
            con.execute(query1, time1=t[1], time2=t[2], time4=t[4])
            con.execute(query2, time0=t[0], time3=t[3])

    def verify_altimeter_and_accelerometer_data(self, data):
        self.assertAlmostEqual(data[0]["altitude_x16"], 3456.0)
        self.assertAlmostEqual(data[1]["x_data"], 1.234)
        self.assertAlmostEqual(data[1]["y_data"], 4.321)
        self.assertAlmostEqual(data[1]["z_data"], 1.111)
        self.assertAlmostEqual(data[2]["x_data"], 2.222)
        self.assertAlmostEqual(data[2]["y_data"], 3.333)
        self.assertAlmostEqual(data[2]["z_data"], 4.444)
        self.assertAlmostEqual(data[3]["altitude_x16"], 6543.0)
        self.assertAlmostEqual(data[4]["x_data"], 0.123)
        self.assertAlmostEqual(data[4]["y_data"], 0.222)
        self.assertAlmostEqual(data[4]["z_data"], 100.1)

    def test_sensor_window_sum(self):
        list_of_tuples = []
        for i in range(100):
            list_of_tuples.append(
                AccelSample(datetime.now(), i, i * 10, i * 100, 1000 + i)
            )
        with session_scope() as session:
            tp = TripProcessor(session)
            sum_z = tp._sensor_window_sum(list_of_tuples, 10, 20, "z")
            self.assertEqual(sum_z, sum(range(10, 20)) * 100, "failed range 10 to 20")
            sum_z = tp._sensor_window_sum(list_of_tuples, 0, 3, "z")
            self.assertEqual(sum_z, sum(range(0, 3)) * 100, "failed range 0 to 3")
            sum_z = tp._sensor_window_sum(list_of_tuples, 2, 100, "z")
            self.assertEqual(sum_z, sum(range(2, 100)) * 100, "failed range 2 to 100")

    def test_write_out_chart_data(self):
        chart_data = []
        for i in range(10):
            chart_data.append(["next value", i, i * 2.0])
        with session_scope() as session:
            tp = TripProcessor(session)
            tp._write_out_chart_data(chart_data)

        file = os.path.join(common_constants.STORAGE_FOLDER, constants.CSV_FILE_NAME)
        with open(file, "r", newline="") as csvfile:
            csv_reader = csv.reader(csvfile, quoting=csv.QUOTE_ALL)
            i = 0
            for row in csv_reader:
                self.assertEqual("next value", row[0])
                self.assertEqual(str(i), row[1])
                self.assertEqual(str(i * 2.0), row[2])
                i += 1

    def test_get_next_batch_of_data(self):
        self.create_altimeter_and_accelerometer_data()
        with session_scope() as session:
            tp = TripProcessor(session)
            tp.last_timestamp = datetime.now() - timedelta(minutes=2)
            data = tp._get_next_batch_of_data()
            self.verify_altimeter_and_accelerometer_data(data)

    def test_process_batch_with_no_trips(self):
        last_timestamp = datetime.now() - timedelta(minutes=2)
        batch_of_data = self.generate_batch_of_data(
            last_timestamp, number_of_total_samples=200
        )
        with session_scope() as session:
            tp = TripProcessor(session)
            tp.last_timestamp = datetime.now() - timedelta(minutes=2)
            for row in batch_of_data:
                tp._process_row(row)
        last_trip = self.testutils.get_last_trip()
        self.assertIsNone(last_trip)

    @staticmethod
    def vibration_json_side_effect(value):
        return value

    @patch("trips.trip_processor.TripProcessor._convert_one_axis_vibration_to_json")
    def test_get_vibration_json(self, convert_one_axis):
        convert_one_axis.side_effect = TripsTests.vibration_json_side_effect
        with session_scope() as session:
            tp = TripProcessor(session)
            result = tp._get_vibration_json(829.1, 45.5, 103.8)
            self.assertEqual(result["x_psd"], 829.1)
            self.assertEqual(result["y_psd"], 45.5)
            self.assertEqual(result["z_psd"], 103.8)

    def test_convert_one_axis_vibration_to_json_with_4_bins(self):
        vibration = [87.1, 94.4, 76.2, 109.4]
        with session_scope() as session:
            tp = TripProcessor(session)
            result = tp._convert_one_axis_vibration_to_json(vibration)
        self.assertEqual(result["f0"], 87.1)
        self.assertEqual(result["f1"], 94.4)
        self.assertEqual(result["f2"], 76.2)
        self.assertEqual(result["f3"], 109.4)
        self.assertEqual(len(result), 4)

    def test_convert_one_axis_vibration_to_json_with_5_bins(self):
        vibration = [87.1, 94.4, 76.2, 109.4, 34.5]
        with session_scope() as session:
            tp = TripProcessor(session)
            result = tp._convert_one_axis_vibration_to_json(vibration)
        self.assertEqual(result["f0"], 87.1)
        self.assertEqual(result["f1"], 94.4)
        self.assertEqual(result["f2"], 76.2)
        self.assertEqual(result["f3"], 109.4)
        self.assertEqual(result["f4"], 34.5)
        self.assertEqual(len(result), 5)

    def get_latest_acceleration_id(self):
        with session_scope() as session:
            return session.execute(
                "SELECT id FROM accelerations ORDER BY id DESC LIMIT 1"
            ).first()[0]

    def test_save_acceleration_starting_trip_up(self):
        vibration = {}
        vibration["x_psd"] = self.create_one_axis_of_vibration_data()
        vibration["y_psd"] = self.create_one_axis_of_vibration_data()
        vibration["z_psd"] = self.create_one_axis_of_vibration_data()
        self.run_save_acceleration(
            datetime.now() - timedelta(seconds=4), datetime.now(), True, True, vibration
        )

    def test_save_acceleration_starting_trip_down(self):
        vibration = {}
        vibration["x_psd"] = self.create_one_axis_of_vibration_data()
        vibration["y_psd"] = self.create_one_axis_of_vibration_data()
        vibration["z_psd"] = self.create_one_axis_of_vibration_data()
        self.run_save_acceleration(
            datetime.now() - timedelta(seconds=4),
            datetime.now(),
            True,
            False,
            vibration,
        )

    def test_save_acceleration_ending_trip_up(self):
        vibration = {}
        vibration["x_psd"] = self.create_one_axis_of_vibration_data()
        vibration["y_psd"] = self.create_one_axis_of_vibration_data()
        vibration["z_psd"] = self.create_one_axis_of_vibration_data()
        self.run_save_acceleration(
            datetime.now() - timedelta(seconds=4),
            datetime.now(),
            False,
            False,
            vibration,
        )

    def test_save_acceleration_ending_trip_down(self):
        vibration = self.get_a_vibration()
        self.run_save_acceleration(
            datetime.now() - timedelta(seconds=4),
            datetime.now(),
            False,
            True,
            vibration,
        )

    def get_a_vibration(self):
        vibration = {}
        vibration["x_psd"] = self.create_one_axis_of_vibration_data()
        vibration["y_psd"] = self.create_one_axis_of_vibration_data()
        vibration["z_psd"] = self.create_one_axis_of_vibration_data()
        return vibration

    def create_one_axis_of_vibration_data(self):
        vibration = {}
        for i in range(14):
            vibration["f{0}".format(i)] = 100 + random.randint(0, 100)
        return vibration

    def run_save_acceleration(
        self, start_time, end_time, is_start, is_positive, vibration
    ):
        with session_scope() as session:
            tp = TripProcessor(session)
            tp._save_acceleration(
                start_time, end_time, is_start, is_positive, vibration
            )
        id = self.get_latest_acceleration_id()
        self.verify_acceleration(
            id, is_start=is_start, is_positive=is_positive, expected_vibration=vibration
        )

    def verify_acceleration(
        self, accel_id, is_start=True, is_positive=True, expected_vibration=None
    ):
        with engine.connect() as con:
            accel = con.execute(
                text("SELECT * FROM accelerations WHERE id = :id"), id=accel_id
            ).first()
        self.assertGreaterEqual(
            accel["duration"],
            800,
            "Acceleration duration should be at least 0.8 seconds, got {0}".format(
                accel["duration"]
            ),
        )
        self.assertLess(
            accel["duration"],
            5000,
            "Acceleration duration should be less than 5 seconds, got {0}".format(
                accel["duration"]
            ),
        )
        # Magnitude is redundant now.
        self.assertEqual(accel["is_start_of_trip"], is_start)
        self.assertEqual(accel["is_positive"], is_positive)
        if expected_vibration is not None:
            self.assertEqual(accel["vibration"], expected_vibration)

    @patch("utilities.db_utilities.Audio.get_noise_for_time_period")
    def test_save_trip_up(self, get_noise_for_time_period):
        get_noise_for_time_period.return_value = 76.2
        self.run_save_trip(True)

    def run_save_trip(self, is_up):
        start_time = datetime.now() - timedelta(seconds=15)
        start_coasting_time = datetime.now() - timedelta(seconds=13)
        end_coasting_time = datetime.now() - timedelta(seconds=5)
        end_time = datetime.now() - timedelta(seconds=2)
        elevation_change = 134 if is_up else -215
        speed = 499
        coasting_vibration = self.get_a_vibration()

        starting_vibration = self.get_a_vibration()
        ending_vibration = self.get_a_vibration()
        with session_scope() as session:
            tp = TripProcessor(session)
            tp._save_acceleration(
                start_time, start_coasting_time, True, is_up, starting_vibration
            )
            starting_accel_id = self.get_latest_acceleration_id()
            tp._save_acceleration(
                end_coasting_time, end_time, False, not is_up, ending_vibration
            )
            ending_accel_id = self.get_latest_acceleration_id()

            tp._save_trip(
                start_time,
                end_time,
                is_up,
                elevation_change,
                speed,
                coasting_vibration,
                starting_accel_id,
                ending_accel_id,
            )
            # There should only be one trip in the database.
            trip = session.query(Trip).first()
            self.assertEqual(trip.start_time, start_time.replace(tzinfo=timezone.utc))
            self.assertEqual(trip.end_time, end_time.replace(tzinfo=timezone.utc))
            self.assertEqual(trip.is_up, is_up)
            self.assertEqual(trip.elevation_change, elevation_change)
            self.assertEqual(trip.speed, speed)
            self.assertEqual(trip.vibration, coasting_vibration)
            self.assertEqual(trip.start_accel, starting_accel_id)
            self.assertEqual(trip.end_accel, ending_accel_id)
            self.assertEqual(trip.audio["noise"], 76.2)
            self.verify_acceleration(
                starting_accel_id,
                is_start=True,
                is_positive=is_up,
                expected_vibration=starting_vibration,
            )
            self.verify_acceleration(
                ending_accel_id,
                is_start=False,
                is_positive=not is_up,
                expected_vibration=ending_vibration,
            )

    @patch("utilities.db_utilities.Audio.get_noise_for_time_period")
    def test_process_batch_with_trip_up(self, get_noise_for_time_period):
        get_noise_for_time_period.return_value = 432.1
        last_timestamp = datetime.now() - timedelta(minutes=2)
        sensor_data = self.generate_batch_of_data(
            last_timestamp,
            number_of_total_samples=3000,
            speed_fpm=300,
            trip_starts_at=500,
        )
        self.feed_batches_to_trip_processor(sensor_data)
        last_trip = self.testutils.get_last_trip()
        self.assertIsNotNone(last_trip)
        self.assertTrue(last_trip["is_up"])
        self.assertAlmostEqual(
            last_trip["elevation_change"],
            self.get_expected_elevation_change(100, TRIP_LEN, +1),
            delta=2,
        )
        self.assertAlmostEqual(last_trip["speed"], 300.0, delta=6.0)
        self.assertAlmostEqual(last_trip["audio"]["noise"], 432.1, delta=0.1)
        self.verify_acceleration(
            last_trip["start_accel"], is_start=True, is_positive=True
        )
        self.verify_acceleration(
            last_trip["end_accel"], is_start=False, is_positive=False
        )

    @patch("utilities.db_utilities.Audio.get_noise_for_time_period")
    def test_process_batch_with_trip_down(self, get_noise_for_time_period):
        get_noise_for_time_period.return_value = 123.4
        last_timestamp = datetime.now() - timedelta(minutes=3)
        sensor_data = self.generate_batch_of_data(
            last_timestamp,
            number_of_total_samples=2000,
            speed_fpm=100,
            trip_starts_at=200,
            direction="down",
        )
        self.feed_batches_to_trip_processor(sensor_data)
        last_trip = self.testutils.get_last_trip()
        self.assertIsNotNone(last_trip)
        self.assertFalse(last_trip["is_up"])
        self.assertAlmostEqual(
            last_trip["elevation_change"],
            self.get_expected_elevation_change(100, TRIP_LEN, -1),
            delta=2,
        )
        self.assertAlmostEqual(last_trip["speed"], 100.0, delta=2.0)
        self.assertAlmostEqual(last_trip["audio"]["noise"], 123.4, delta=0.1)
        self.verify_acceleration(
            last_trip["start_accel"], is_start=True, is_positive=False
        )
        self.verify_acceleration(
            last_trip["end_accel"], is_start=False, is_positive=True
        )

    def test_process_batch_with_missing_starting_accel(self):
        last_timestamp = datetime.now() - timedelta(minutes=3)
        sensor_data = self.generate_batch_of_data(
            last_timestamp,
            number_of_total_samples=2000,
            speed_fpm=300,
            trip_starts_at=350,
            direction="down",
            no_starting_accel=True,
        )
        self.feed_batches_to_trip_processor(sensor_data)
        last_trip = self.testutils.get_last_trip()
        self.assertIsNone(last_trip)

    def test_process_batch_with_missing_ending_accel(self):
        last_timestamp = datetime.now() - timedelta(minutes=3)
        sensor_data = self.generate_batch_of_data(
            last_timestamp,
            number_of_total_samples=2000,
            speed_fpm=300,
            trip_starts_at=350,
            direction="down",
            no_ending_accel=True,
        )
        self.feed_batches_to_trip_processor(sensor_data)
        last_trip = self.testutils.get_last_trip()
        self.assertIsNone(last_trip)

    def test_process_batch_with_wrong_starting_accel(self):
        last_timestamp = datetime.now() - timedelta(minutes=3)
        sensor_data = self.generate_batch_of_data(
            last_timestamp,
            number_of_total_samples=2000,
            speed_fpm=300,
            trip_starts_at=350,
            direction="down",
            wrong_starting_accel=True,
        )
        self.feed_batches_to_trip_processor(sensor_data)
        last_trip = self.testutils.get_last_trip()
        self.assertIsNone(last_trip)

    def test_process_batch_with_wrong_ending_accel(self):
        last_timestamp = datetime.now() - timedelta(minutes=3)
        sensor_data = self.generate_batch_of_data(
            last_timestamp,
            number_of_total_samples=2000,
            speed_fpm=300,
            trip_starts_at=350,
            direction="down",
            wrong_ending_accel=True,
        )
        self.feed_batches_to_trip_processor(sensor_data)
        last_trip = self.testutils.get_last_trip()
        self.assertIsNone(last_trip)

    def test_process_batch_with_no_altimeter_trip(self):
        last_timestamp = datetime.now() - timedelta(minutes=3)
        sensor_data = self.generate_batch_of_data(
            last_timestamp,
            number_of_total_samples=2000,
            speed_fpm=300,
            trip_starts_at=350,
            direction="down",
            no_altim_trip=True,
        )
        self.feed_batches_to_trip_processor(sensor_data)
        last_trip = self.testutils.get_last_trip()
        self.assertIsNone(last_trip)

    def feed_batches_to_trip_processor(self, sensor_data):
        with session_scope() as session, patch.object(
            TripProcessor, "_get_next_batch_of_data", return_value=sensor_data
        ):
            tp = TripProcessor(session)
            tp.last_timestamp = datetime.now() - timedelta(minutes=2)
            tp.look_for_trips()

    def generate_accel_noise(self, max_noise_level=None):
        # Get a random number with avg of 0.0
        max_noise_level = max_noise_level or 20.0
        return (random.random() - 0.5) * 2.0 * max_noise_level

    def test_speed_conversion(self):
        raw_accel = TripProcessor._convert_to_sum_of_raw_accel(300.0)
        self.assertGreater(raw_accel, 2000)
        speed_fpm = TripProcessor._convert_to_fpm(raw_accel)
        self.assertAlmostEqual(speed_fpm, 300.0)

    def get_expected_elevation_change(self, speed_fpm, trip_length, trip_direction):
        # For now, all trips have a fixed elevation change.
        return int(
            trip_direction
            * ALTIM_SLOPE
            * TRIP_LEN
            / (constants.ALTIM_SAMPLE_PERIOD / constants.ACCEL_SAMPLE_PERIOD)
        )

    def generate_batch_of_data(
        self,
        last_timestamp,
        number_of_total_samples=100,
        trip_starts_at=None,
        speed_fpm=250,
        direction="up",
        no_starting_accel=False,
        no_ending_accel=False,
        wrong_starting_accel=False,
        wrong_ending_accel=False,
        no_altim_trip=False,
    ):
        self.assertLessEqual(
            ACCEL_LEN * 1.0,
            TRIP_LEN / 2,
            "Acceleration time can't be more than half the trip time in test simulation",
        )
        acceleration_val = (
            TripProcessor._convert_to_sum_of_raw_accel(speed_fpm) / ACCEL_LEN
        )

        # Make sure we get the same results every time by resetting the seed.
        # We only need random to add reproducable noise.
        random.seed(a=1000)  # Ensure reproducable results.
        result = []
        tstamp = last_timestamp + timedelta(seconds=1)
        curr_altitude = random.randint(1000, 7000)
        sign = 1 if direction == "up" else -1
        in_trip_flag = False
        altim_randomizer = 0

        for sample_counter in range(number_of_total_samples):
            # First get the current expected accelerometer and altimeter values.
            curr_accel = 0.0
            if trip_starts_at and 0 <= sample_counter - trip_starts_at < TRIP_LEN:
                # We are within a starting or ending acceleration.
                in_trip_flag = True
                if (sample_counter - trip_starts_at) < ACCEL_LEN or (
                    trip_starts_at + TRIP_LEN
                ) - sample_counter < ACCEL_LEN:
                    if (sample_counter - trip_starts_at) < ACCEL_LEN:
                        # Allow for selecting bad data
                        start_vs_end_accel_sign = 1 if not wrong_starting_accel else -1
                        start_vs_end_accel_sign = (
                            start_vs_end_accel_sign if not no_starting_accel else 0
                        )
                    else:
                        # Allow for selecting bad data
                        start_vs_end_accel_sign = -1 if not wrong_ending_accel else 1
                        start_vs_end_accel_sign = (
                            start_vs_end_accel_sign if not no_ending_accel else 0
                        )
                    # Starting or ending acceleration
                    curr_accel = acceleration_val * sign * start_vs_end_accel_sign
            else:
                in_trip_flag = False

            curr_accel += self.generate_accel_noise()

            # Add altimeter samples at the correct rate
            if (
                sample_counter
                % int(constants.ALTIM_SAMPLE_PERIOD / constants.ACCEL_SAMPLE_PERIOD)
                == 0
            ):
                result.append(
                    SensorData(tstamp, None, None, None, curr_altitude),
                )
                # Do this after adding the next altim sample since altimeter lags accelerometer
                if in_trip_flag:
                    # We're moving, so incr/decr on each altim point
                    if not no_altim_trip:
                        curr_altitude += sign * ALTIM_SLOPE
                    else:
                        # If no altim trip, test altimeter noise
                        curr_altitude += altim_randomizer - 1
                        altim_randomizer = (altim_randomizer + 1) % 3

            # Add accelerometer samples on every sample period
            result.append(
                SensorData(
                    tstamp,
                    float(self.generate_accel_noise()),
                    float(self.generate_accel_noise()),
                    float(curr_accel),
                    None,
                ),
            )

            tstamp += timedelta(milliseconds=constants.ACCEL_SAMPLE_PERIOD)
        return result

    def test_no_saved_timestamp(self):
        with session_scope() as session:
            tp = TripProcessor(session)
            os.system("sudo rm {0}".format(tp.last_timestamp_path))
            del tp
            before_starting = datetime.now()
            tp = TripProcessor(session)
            self.assertGreater(tp.last_timestamp, before_starting)
            self.assertLess(tp.last_timestamp, datetime.now())

    def test_saved_timestamp(self):
        with session_scope() as session:
            tp = TripProcessor(session)
            last_timestamp = datetime.now() - timedelta(minutes=42)
            tp.last_timestamp = last_timestamp
            tp._save_last_timestamp()
            del tp
            tp = TripProcessor(session)
            self.assertEqual(tp.last_timestamp, last_timestamp)

    def test_get_vibration_for_sample_interval(self):
        TestTuple = namedtuple("TestTuple", ["a", "b"])
        list_of_tuples = []
        with session_scope() as session:
            tp = TripProcessor(session)
            random.seed(100)  # Ensure reproducable results.

            # Fill the first 50 and last 50 samples with a strong DC signal that we can detect.
            for _ in range(50):
                list_of_tuples.append(TestTuple(a=1000.0, b=1000.0))

            # Fill the middle 200 samples with white noise and no DC offset.
            for _ in range(200):
                list_of_tuples.append(
                    TestTuple(a=0.0, b=self.generate_vibration_noise())
                )

            for _ in range(50):
                list_of_tuples.append(TestTuple(a=1000.0, b=1000.0))

            bins = tp._get_vibration_for_sample_interval(list_of_tuples, "b", 50, 250)
            self.assertEqual(
                len(bins), 14, "TripProcessor should combine bins into a total of 14."
            )
            self.assertLess(
                bins[0],
                30,
                "bin 0 (DC offset) should not be large: bad indexing or bad FFTing",
            )
            for i in range(1, 14):
                self.assertGreater(bins[i], 10, "sanity check of minimum FFT level")

    def generate_vibration_noise(self):
        # Use fairly large random numbers with a zero mean.
        return (random.uniform(-1.0, 1.0)) * 100.0

    def test_record_missed_trip(self):
        trip_start = datetime.now() - timedelta(minutes=2)
        with session_scope() as session:
            tp = TripProcessor(session)
            tp._record_missed_trip(1234, trip_start)
            event = self.testutils.get_events(trip_start)[0]
            self.assertEqual(event["event_type"], common_constants.EVENT_TYPE_ELEVATION)
            self.assertEqual(
                event["event_subtype"], common_constants.EVENT_SUBTYPE_MISSING_TRIP
            )
            details = event["details"]
            self.assertEqual(
                details[common_constants.EVENT_DETAILS_ELEVATION_CHANGE], 1234
            )

    @patch("trips.trip_processor.TripProcessor._get_next_batch_of_data")
    @patch("trips.trip_processor.TripProcessor._process_row")
    def test_look_for_trips(self, process_row, get_next_batch):
        next_batch = [MagicMock()]
        get_next_batch.return_value = next_batch
        process_row.return_value = None
        with session_scope() as session:
            tp = TripProcessor(session)
            tp.look_for_trips()
            process_row.assert_called_once_with(next_batch[0])

    @patch("trips.trip_processor.TripProcessor._get_next_batch_of_data")
    def test_look_for_trips_no_trips(self, get_next_batch):
        last_timestamp = datetime.now() - timedelta(minutes=2)
        next_batch = self.generate_batch_of_data(
            last_timestamp, number_of_total_samples=200
        )
        get_next_batch.return_value = next_batch
        with session_scope() as session:
            tp = TripProcessor(session)
            tp.last_timestamp = datetime.now() - timedelta(minutes=2)
            tp.look_for_trips()
        last_trip = self.testutils.get_last_trip()
        self.assertIsNone(last_trip)

    def test_accel_detect_normal_positive(self):
        self.run_accel_detect(sign=+1)

    def test_accel_detect_fast_positive(self):
        self.run_accel_detect(accel=2000, sign=+1)

    def test_accel_detect_normal_positive_with_leveling(self):
        self.run_accel_detect(sign=+1, leveling=True)

    def test_accel_detect_normal_negative(self):
        self.run_accel_detect(sign=-1)

    def test_accel_detect_noisy_positive(self):
        self.run_accel_detect(sign=+1, noise=200)

    def test_accel_detect_low_accel_negative(self):
        self.run_accel_detect(sign=-1, accel=30)

    def test_accel_detect_low_accel_noisy_positive(self):
        self.run_accel_detect(sign=+1, noise=150, accel=70)

    # Corner case
    def test_accel_detect_low_accel_noisy_negative_with_leveling(self):
        self.run_accel_detect(sign=-1, noise=150, accel=60, leveling=True)

    def run_accel_detect(self, sign=+1, noise=50, accel=300, leveling=False):
        buffer = []
        random.seed(100)  # Ensure reproducable results.

        # Two seconds of no acceleration
        for _ in range(200):
            z_accel = self.generate_accel_noise(max_noise_level=noise)
            buffer.append(AccelSample(datetime.now(), 0.0, 0.0, z_accel, 0))

        # Two seconds of upward acceleration in a ramp up/down pattern
        for i in range(200):
            z_accel = ((100 - abs(i - 100)) * accel * sign) + self.generate_accel_noise(
                max_noise_level=noise
            )
            buffer.append(AccelSample(datetime.now(), 0.0, 0.0, z_accel, 0))

        # Optional second of leveling
        if leveling:
            for i in range(100):
                z_accel = (
                    (100 - abs(i - 100)) * accel * sign / 3.5
                ) + self.generate_accel_noise(max_noise_level=noise)
                buffer.append(AccelSample(datetime.now(), 0.0, 0.0, z_accel, 0))

        # Then two seconds of no acceleration
        for _ in range(200):
            z_accel = self.generate_accel_noise(max_noise_level=noise)
            buffer.append(AccelSample(datetime.now(), 0.0, 0.0, z_accel, 0))

        STARTING_POINT_IN_BUFFER = 37  # Choose a number near the start of the buffer
        ENDING_POINT_IN_BUFFER = 589  # Choose a number near the end of the buffer
        # Get total acceleration (including both endpoints)
        accel_total = 0
        for i in range(STARTING_POINT_IN_BUFFER, ENDING_POINT_IN_BUFFER + 1):
            accel_total += buffer[i].z

        with session_scope() as session:
            tp = TripProcessor(session)
            start, end = tp._find_acceleration_start_and_end(
                buffer, STARTING_POINT_IN_BUFFER, ENDING_POINT_IN_BUFFER, accel_total
            )

        self.assertGreaterEqual(start, 180, "acceleration start detected too soon")
        self.assertLessEqual(start, 230, "acceleration start detected too late")

        self.assertGreaterEqual(
            end, 370 if not leveling else 470, "acceleration end detected too soon"
        )
        self.assertLessEqual(
            end, 420 if not leveling else 520, "acceleration end detected too late"
        )

    def test_is_altim_row(self):
        self.assertTrue(TripProcessor._is_altim_row(MagicMock(altitude_x16="0.123")))
        self.assertFalse(
            TripProcessor._is_altim_row(MagicMock(other_data="foo", altitude_x16=None))
        )
        self.assertFalse(
            TripProcessor._is_altim_row(MagicMock(other_data="foo", altitude_x16=""))
        )


class TestTripProcessorProcessAccelRow(unittest.TestCase):
    @patch("trips.constants.ACCEL_WINDOW_LEN", 10)
    def test_fifo_has_correct_samples(self):
        session = MagicMock()
        tp = TripProcessor(session)

        last_timestamp = None

        rows = []
        for _ in range(constants.ACCEL_WINDOW_LEN + 1):
            last_timestamp = datetime.now()
            tp.last_timestamp = last_timestamp

            rows.append(
                SensorData(
                    timestamp=last_timestamp,
                    x_data=0,
                    y_data=0,
                    z_data=0,
                    altitude_x16=None,
                )
            )

        for row in rows:
            result = tp._process_accel_row(row)
            self.assertIsNone(result)

        # Assert correct number of samples
        self.assertEqual(len(tp.accel_data), constants.ACCEL_WINDOW_LEN)

        # Assert FIFO takes from start
        self.assertEqual(tp.accel_data[-1].timestamp, last_timestamp)

    def test_row_processed_correctly(self):
        session = MagicMock()
        tp = TripProcessor(session)
        last_altim_value = 100
        tp.last_altim_value = last_altim_value
        sensor_data = SensorData(
            timestamp=datetime.now(),
            x_data=0,
            y_data=1,
            z_data=2,
            altitude_x16=None,
        )

        expected_accel_data = AccelSample(
            timestamp=sensor_data.timestamp,
            x=float(sensor_data.x_data),
            y=float(sensor_data.y_data),
            z=float(sensor_data.z_data),
            altim=last_altim_value,
        )

        result = tp._process_accel_row(sensor_data)

        self.assertEqual(tp.accel_data[-1], expected_accel_data)
        self.assertIsNone(result)

    def test_signals_insufficient_accel_samples(self):
        session = MagicMock()
        tp = TripProcessor(session)

        sensor_data = SensorData(
            timestamp=datetime.now(),
            x_data=0,
            y_data=1,
            z_data=2,
            altitude_x16=None,
        )

        tp.altim_detected_trip_end = True
        tp.extra_accel_samples_needed_count = 1

        result = tp._process_accel_row(sensor_data)

        self.assertEqual(result, InsufficientAccelSamples())


@patch("trips.trip_processor.stats.linregress")
class TestTripProcessorProcessAltimRow(unittest.TestCase):
    passing_std_error = constants.STDERR_MAX_THRESH - 0.001
    passing_linregress_start_return_value = (
        constants.START_TRIP_SLOPE_THRESH,
        ANY,
        ANY,
        ANY,
        passing_std_error,
    )
    passing_linregress_end_return_value = (
        constants.END_TRIP_SLOPE_THRESH - 0.01,
        ANY,
        ANY,
        ANY,
        passing_std_error,
    )

    def test_altim_detected_start_does_not_trigger_if_std_err_is_too_high(
        self, linregress
    ):
        session = MagicMock()
        tp = TripProcessor(session)
        row = MagicMock()

        tp.altim_detected_trip_in_progress = False
        tp.altim_window = list((i, i + 1) for i in range(constants.ALTIM_WINDOW_LEN))

        linregress.return_value = (
            constants.START_TRIP_SLOPE_THRESH,
            ANY,
            ANY,
            ANY,
            self.passing_std_error + 0.001,
        )
        self.assertIsNone(tp._process_altim_row(row))

    def test_altim_detected_start_does_not_trigger_if_slope_is_too_low(
        self, linregress
    ):
        session = MagicMock()
        tp = TripProcessor(session)
        row = MagicMock()

        tp.altim_detected_trip_in_progress = False
        tp.altim_window = list((i, i + 1) for i in range(constants.ALTIM_WINDOW_LEN))

        linregress.return_value = (
            constants.START_TRIP_SLOPE_THRESH - 0.001,
            ANY,
            ANY,
            ANY,
            self.passing_std_error,
        )
        self.assertIsNone(tp._process_altim_row(row))

    def test_altim_detected_start_does_not_trigger_if_trip_is_in_progress(
        self, linregress
    ):
        session = MagicMock()
        tp = TripProcessor(session)
        row = MagicMock()

        tp.altim_detected_trip_in_progress = True
        tp.altim_window = list((i, i + 1) for i in range(constants.ALTIM_WINDOW_LEN))

        linregress.return_value = self.passing_linregress_start_return_value
        self.assertIsNone(tp._process_altim_row(row))

    def test_altim_detected_start_is_triggered(self, linregress):
        session = MagicMock()
        tp = TripProcessor(session)
        row = MagicMock()

        tp.altim_detected_trip_in_progress = False

        tp.altim_window = list(
            (i, i + 1) for i in range(constants.ALTIM_WINDOW_LEN - 1)
        )
        linregress.return_value = self.passing_linregress_start_return_value
        self.assertEqual(
            tp._process_altim_row(row),
            AltimDetectedStart(direction=1.0, start_timestamp=0, starting_elevation=1),
        )

        tp.altim_window = list(
            (i, i + 1) for i in range(constants.ALTIM_WINDOW_LEN - 1)
        )
        linregress.return_value = (
            -constants.START_TRIP_SLOPE_THRESH,
            ANY,
            ANY,
            ANY,
            self.passing_std_error,
        )
        self.assertEqual(
            tp._process_altim_row(row),
            AltimDetectedStart(direction=-1.0, start_timestamp=0, starting_elevation=1),
        )

    def test_altim_detected_end_does_not_trigger_if_trip_not_in_progress(
        self, linregress
    ):
        session = MagicMock()
        tp = TripProcessor(session)
        row = MagicMock(altitude_x16=120)

        tp.altim_detected_trip_in_progress = False
        tp.trip_starting_elevation = 90

        tp.altim_window = list(
            (i, i + 1) for i in range(constants.ALTIM_WINDOW_LEN - 1)
        )
        linregress.return_value = self.passing_linregress_end_return_value
        self.assertIsNone(tp._process_altim_row(row))

    def test_altim_detected_end_does_not_trigger_if_std_err_is_too_high(
        self, linregress
    ):
        session = MagicMock()
        tp = TripProcessor(session)
        row = MagicMock(altitude_x16=120)

        tp.altim_detected_trip_in_progress = True
        tp.trip_starting_elevation = 90

        tp.altim_window = list(
            (i, i + 1) for i in range(constants.ALTIM_WINDOW_LEN - 1)
        )
        linregress.return_value = (
            constants.END_TRIP_SLOPE_THRESH - 0.1,
            ANY,
            ANY,
            ANY,
            constants.STDERR_MAX_THRESH,
        )
        self.assertIsNone(tp._process_altim_row(row))

    def test_altim_detected_end_does_not_trigger_if_slope_is_too_high(self, linregress):
        session = MagicMock()
        tp = TripProcessor(session)
        row = MagicMock(altitude_x16=120)

        tp.altim_detected_trip_in_progress = True
        tp.trip_starting_elevation = 90

        tp.altim_window = list(
            (i, i + 1) for i in range(constants.ALTIM_WINDOW_LEN - 1)
        )
        linregress.return_value = (
            constants.END_TRIP_SLOPE_THRESH,
            ANY,
            ANY,
            ANY,
            self.passing_std_error,
        )
        self.assertIsNone(tp._process_altim_row(row))

    def test_altim_detected_end_does_not_trigger_when_elevation_change_too_low(
        self, linregress
    ):
        session = MagicMock()
        tp = TripProcessor(session)
        initial_elevation = 90
        row = MagicMock(
            altitude_x16=initial_elevation - constants.MIN_TRIP_ELEVATION + 1
        )

        tp.altim_detected_trip_in_progress = True
        tp.trip_starting_elevation = initial_elevation

        tp.altim_window = list(
            (i, i + 1) for i in range(constants.ALTIM_WINDOW_LEN - 1)
        )
        linregress.return_value = self.passing_linregress_end_return_value
        self.assertEqual(tp._process_altim_row(row), AltimeterReset())

    def test_altim_detected_end_is_triggered(self, linregress):
        session = MagicMock()
        tp = TripProcessor(session)
        row = MagicMock(altitude_x16=120)

        tp.altim_detected_trip_in_progress = True
        tp.trip_starting_elevation = 90

        tp.altim_window = list(
            (i, i + 1) for i in range(constants.ALTIM_WINDOW_LEN - 1)
        )
        linregress.return_value = self.passing_linregress_end_return_value
        self.assertEqual(
            tp._process_altim_row(row),
            AltimDetectedEnd(end_timestamp=0, ending_elevation=120),
        )

        tp.altim_window = list(
            (i, i + 1) for i in range(constants.ALTIM_WINDOW_LEN - 1)
        )
        linregress.return_value = (
            -(constants.END_TRIP_SLOPE_THRESH - 0.1),
            ANY,
            ANY,
            ANY,
            self.passing_std_error,
        )
        self.assertEqual(
            tp._process_altim_row(row),
            AltimDetectedEnd(end_timestamp=0, ending_elevation=120),
        )


class TestProcessAction(unittest.TestCase):
    @staticmethod
    def _get_state(tp):
        state = tp.__dict__.copy()
        del state["altim_window"]
        del state["accel_data"]
        del state["result_data"]

        return state

    @staticmethod
    def _perform_action_return_state_before_after(tp, fn):
        before_state = TestProcessAction._get_state(tp)
        fn()
        after_state = TestProcessAction._get_state(tp)
        return before_state, after_state

    @staticmethod
    def _detemine_state_key_differences(before_state, after_state):
        set1 = set(before_state.items())
        set2 = set(after_state.items())
        diff = sorted(tuple(set(key for key, _ in set1 ^ set2)))
        return diff

    def test_no_action_does_not_affect_state(self):
        session = MagicMock()
        tp = TripProcessor(session)

        before_state, after_state = self._perform_action_return_state_before_after(
            tp, lambda: tp.process_action(None)
        )

        self.assertEqual(before_state, after_state)

    def test_altim_detected_start_sets_correct_state(self):
        session = MagicMock()
        tp = TripProcessor(session)
        action = AltimDetectedStart(
            direction=-1, start_timestamp=2, starting_elevation=3
        )
        before_state, after_state = self._perform_action_return_state_before_after(
            tp,
            lambda: tp.process_action(action),
        )

        expected_state_key_changes = [
            "altim_detected_trip_in_progress",
            "altim_trip_start_timestamp",
            "trip_direction",
            "trip_starting_elevation",
        ]
        actual_state_key_changes = self._detemine_state_key_differences(
            before_state, after_state
        )

        self.assertEqual(actual_state_key_changes, expected_state_key_changes)
        self.assertEqual(tp.altim_detected_trip_in_progress, True)
        self.assertEqual(tp.trip_direction, -1)
        self.assertEqual(tp.altim_trip_start_timestamp, action.start_timestamp)
        self.assertEqual(tp.trip_starting_elevation, action.starting_elevation)

    def test_altim_detected_end_sets_correct_state(self):
        session = MagicMock()
        tp = TripProcessor(session)
        trip_starting_elevation = 20

        tp.trip_starting_elevation = trip_starting_elevation
        tp.trip_direction = -1
        tp.altim_detected_trip_in_progress = True

        action = AltimDetectedEnd(end_timestamp=1, ending_elevation=0)
        before_state, after_state = self._perform_action_return_state_before_after(
            tp,
            lambda: tp.process_action(action),
        )

        expected_state_key_changes = [
            "altim_detected_trip_end",
            "altim_detected_trip_in_progress",
            "altim_trip_end_timestamp",
            "extra_accel_samples_needed_count",
            "trip_ending_elevation",
        ]
        actual_state_key_changes = self._detemine_state_key_differences(
            before_state, after_state
        )

        self.assertEqual(actual_state_key_changes, expected_state_key_changes)
        self.assertEqual(tp.altim_detected_trip_in_progress, False)
        self.assertEqual(tp.altim_detected_trip_end, True)
        self.assertEqual(
            tp.extra_accel_samples_needed_count, constants.TRIP_END_COUNT_THRESH
        )
        self.assertEqual(tp.trip_ending_elevation, action.ending_elevation)

    def test_altimeter_reset_sets_correct_state(self):
        session = MagicMock()
        tp = TripProcessor(session)
        tp.altim_detected_trip_in_progress = True

        before_state, after_state = self._perform_action_return_state_before_after(
            tp, lambda: tp.process_action(AltimeterReset())
        )

        expected_state_key_changes = [
            "altim_detected_trip_in_progress",
        ]
        actual_state_key_changes = self._detemine_state_key_differences(
            before_state, after_state
        )

        self.assertEqual(actual_state_key_changes, expected_state_key_changes)
        self.assertEqual(tp.altim_detected_trip_in_progress, False)

    @patch('trips.trip_processor.TripProcessor._process_accel_data')
    def test_insufficient_accel_samples_sets_correct_state(self, _process_accel_data):
        session = MagicMock()
        tp = TripProcessor(session)
        num_samples = 10
        tp.extra_accel_samples_needed_count = num_samples

        for i in range(num_samples):
            before_state, after_state = self._perform_action_return_state_before_after(
                tp, lambda: tp.process_action(InsufficientAccelSamples())
            )

            
            actual_state_key_changes = self._detemine_state_key_differences(
                before_state, after_state
            )

            if tp.extra_accel_samples_needed_count > 0:
                expected_state_key_changes = [
                    "extra_accel_samples_needed_count",
                ]   
                self.assertEqual(actual_state_key_changes, expected_state_key_changes)
                self.assertEqual(tp.extra_accel_samples_needed_count, num_samples - (i + 1))
            else:
                expected_state_key_changes = [
                    "altim_detected_trip_end",
                    "extra_accel_samples_needed_count",
                ]   
                self.assertEqual(actual_state_key_changes, expected_state_key_changes)
                self.assertEqual(tp.extra_accel_samples_needed_count, 0)
                self.assertEqual(tp.altim_detected_trip_end, False)

                _process_accel_data.assert_called_once_with()
  
    @patch("trips.trip_processor.TripProcessor._process_accel_data")
    @patch("trips.trip_processor.TripProcessor._process_and_save_trip_data")
    def test_insufficient_accel_samples_triggers_trip_data_processing_if_trip_data_available(
        self, process_and_save_trip_data, process_accel_data
    ):
        session = MagicMock()
        tp = TripProcessor(session)
        process_accel_data.return_value = TripData(
            prelim_sot=ANY,
            prelim_eot=ANY,
            midpoint=ANY,
            rough_start_accel=ANY,
            rough_end_accel=ANY,
        )
        tp.extra_accel_samples_needed_count = 1
        tp.process_action(InsufficientAccelSamples())

        process_and_save_trip_data.assert_called_once_with(
            process_accel_data.return_value
        )

    @patch("trips.trip_processor.TripProcessor._process_and_save_trip_data")
    def test_process_trip_data_works(self, process_and_save_trip_data):
        session = MagicMock()
        tp = TripProcessor(session)
        action = TripData(
            prelim_sot=ANY,
            prelim_eot=ANY,
            midpoint=ANY,
            rough_start_accel=ANY,
            rough_end_accel=ANY,
        )
        tp.result_data = [MagicMock()]
        tp.process_action(action)

        process_and_save_trip_data.assert_called_once_with(action)
        self.assertEqual(tp.result_data, [])

    def test_process_incr_save_point_wosk(self):
        session = MagicMock()
        tp = TripProcessor(session)
        num_samples = 10

        for i in range(num_samples):
            before_state, after_state = self._perform_action_return_state_before_after(
                tp, lambda: tp.process_action(IncrSavePoint())
            )

            expected_state_key_changes = [
                "save_point_counter",
            ]
            actual_state_key_changes = self._detemine_state_key_differences(
                before_state, after_state
            )

            self.assertEqual(actual_state_key_changes, expected_state_key_changes)
            self.assertEqual(tp.save_point_counter, (i + 1))


if __name__ == "__main__":
    unittest.main()
