import os
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from time import sleep
import random

import pytz

from report_generator.status_data import (
    StatusData,
    vibration_fields,
    vibration_prefix_map,
)
from report_generator.generator import RGenerator
from report_generator import constants
from utilities import common_constants
from utilities.db_utilities import (
    Session,
    DataToSend,
    Problem,
    Event,
    Trip,
    Acceleration,
)
from utilities.test_utilities import TestUtilities
from utilities.device_configuration import DeviceConfiguration


def avg(a, b):
    return (a + b) / 2.0


def get_hourly_report_time():
    return pytz.utc.localize(datetime.utcnow()).replace(
        minute=0, second=0, microsecond=0
    ) - timedelta(hours=1)


def get_latest_data_to_send(session, endpoint=common_constants.REPORT_ENDPOINT):
    return (
        session.query(DataToSend)
        .filter(DataToSend.endpoint == endpoint)
        .order_by(DataToSend.id.desc())
        .first()
    )


class ReportTesting(unittest.TestCase):
    testutils = TestUtilities()

    # TODO: Migrate this to use TestUtilities
    def _create_problem(
        self,
        problem_type=common_constants.PROB_TYPE_SHUTDOWN,
        started_at=datetime.now(),
        ended_at=None,
        updated_at=None,
        confidence=None,
    ):
        fields = ["problem_type", "problem_subtype", "started_at"]
        values = [problem_type, "unit_testing", str(started_at) if started_at else None]
        if ended_at:
            fields.append("ended_at")
            values.append(str(ended_at) if ended_at else "NULL")
        if confidence is not None:
            fields.append("confidence")
            values.append(confidence)
        if updated_at:
            fields.append("updated_at")
            values.append(str(updated_at))
        elif started_at:
            fields.append("updated_at")
            values.append(str(started_at))
        f_for_insert = ", ".join(fields)
        v_for_insert = ", ".join("'{}'".format(x) if x else "NULL" for x in values)
        self.session.execute(
            "INSERT INTO problems ({0}) VALUES ({1});".format(
                f_for_insert, v_for_insert
            )
        )

    def _delete_problems(self):
        self.session.query(Problem).delete()

    def _delete_data_to_send(self):
        self.session.query(DataToSend).delete()

    def setUp(self):
        self.session = Session()
        self._delete_stuff()
        DeviceConfiguration.write_config_file(DeviceConfiguration.get_default_config())

    def tearDown(self):
        try:
            self._delete_stuff()
        finally:
            self.session.rollback()
            self.session.close()

    def _delete_stuff(self):
        self._delete_problems()
        self._delete_data_to_send()
        self.testutils.delete_trips()
        self.testutils.delete_bank_trips(datetime.now() - timedelta(days=2))

        rgen = RGenerator()
        rgen.delete_storage()

    def test_is_time_for_hourly_report_normal_case(self):
        rgen = RGenerator()
        rgen.saved_values[rgen.name_last_hourly_report] = pytz.utc.localize(
            datetime.utcnow()
        ).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        self.assertTrue(rgen._is_time_for_hourly_report())

    def test_is_time_for_hourly_report_not_yet(self):
        rgen = RGenerator()
        rgen.saved_values[rgen.name_last_hourly_report] = pytz.utc.localize(
            datetime.utcnow()
        ).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        self.assertFalse(rgen._is_time_for_hourly_report())

    def test_is_time_for_hourly_report_long_after(self):
        rgen = RGenerator()
        last_report_time = pytz.utc.localize(datetime.utcnow()).replace(
            minute=0, second=0, microsecond=0
        ) - timedelta(days=7)
        rgen.saved_values[rgen.name_last_hourly_report] = last_report_time
        self.assertTrue(rgen._is_time_for_hourly_report())
        rgen.generate_reports(self.session)

        row = get_latest_data_to_send(self.session)
        self.assertEqual(
            row.payload["date"], (last_report_time + timedelta(hours=1)).isoformat()
        )

    def test_send_report(self):
        rgen = RGenerator()
        report_time = get_hourly_report_time()
        report_payload = {
            "logo": "* made on Earth by humans *",
            "stuff": {"int_stuff": 42, "str_stuff": "XLII"},
        }
        report_endpoint = "dev/null"
        rgen._send_report(
            self.session,
            report_payload,
            report_time_utc=report_time,
            endpoint=report_endpoint,
        )
        row = get_latest_data_to_send(self.session, report_endpoint)
        self.assertEqual(row.timestamp, report_time)
        self.assertEqual(row.endpoint, report_endpoint)
        self.assertEqual(row.payload, report_payload)
        self.assertFalse(row.flag)
        self.assertTrue(row.resend)

    def test_generate_reports(self):
        rgen = RGenerator()
        last_report_time = (
            pytz.utc.localize(datetime.utcnow()) - timedelta(hours=2)
        ).replace(minute=0, second=0, microsecond=0)
        rgen.saved_values[rgen.name_last_hourly_report] = last_report_time
        next_report_time = last_report_time + timedelta(hours=1)
        # Create some trips
        speed = 300.0
        expected_avg_speed = 0.0
        expected_max_speed = 0.0
        for i in range(12):
            expected_avg_speed += speed + i * 10
            expected_max_speed = speed + i * 10
            self.testutils.insert_trip(
                starts_at=next_report_time + timedelta(minutes=i),
                ends_at=next_report_time + timedelta(minutes=i, seconds=10 + i),
                trip_audio={common_constants.AUDIO_NOISE: 3.1416},
                speed=speed + i * 10,
            )
        expected_avg_speed /= 12
        before_report = pytz.utc.localize(datetime.now())
        sleep(0.2)
        rgen.generate_reports(self.session)
        sleep(0.2)
        after_report = pytz.utc.localize(datetime.now())
        row = get_latest_data_to_send(self.session)
        self.assertLessEqual(before_report, row.timestamp)
        self.assertGreaterEqual(after_report, row.timestamp)
        self.assertFalse(row.flag)
        self.assertTrue(row.resend)
        self.assertEqual(
            row.payload["date"], (last_report_time + timedelta(hours=1)).isoformat()
        )
        self.assertEqual(
            row.payload["type"], common_constants.MESSAGE_TYPE_HOURLY_REPORT
        )
        self.assertEqual(row.payload["max_trip_duration"], 21)
        self.assertEqual(row.payload["min_trip_duration"], 10)
        self.assertEqual(row.payload["duty_cycle"], 0.05)
        self.assertEqual(row.payload["uptime"], 1.0)
        self.assertAlmostEqual(row.payload["trip_noise"], 3.1416, places=4)
        self.assertAlmostEqual(row.payload["start_accel_noise"], 1.2345, places=4)
        self.assertAlmostEqual(row.payload["end_accel_noise"], 5.4321, places=4)
        self.assertAlmostEqual(row.payload["min_speed"], speed)
        self.assertAlmostEqual(row.payload["max_speed"], expected_max_speed)
        self.assertAlmostEqual(row.payload["avg_speed"], expected_avg_speed)

        # Verify we get sane values back for more complicated fields.
        self.assertGreaterEqual(row.payload["vibration"]["s_avg_jerk"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["s_max_jerk"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["e_avg_jerk"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["e_max_jerk"], 0.0)

        self.assertGreaterEqual(row.payload["vibration"]["s_ptp_x_max"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["s_ptp_y_max"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["s_ptp_z_max"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["e_ptp_x_max"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["e_ptp_y_max"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["e_ptp_z_max"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["t_ptp_x_max"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["t_ptp_y_max"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["t_ptp_z_max"], 0.0)

        self.assertGreaterEqual(row.payload["vibration"]["s_ptp_x_95"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["s_ptp_y_95"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["s_ptp_z_95"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["e_ptp_x_95"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["e_ptp_y_95"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["e_ptp_z_95"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["t_ptp_x_95"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["t_ptp_y_95"], 0.0)
        self.assertGreaterEqual(row.payload["vibration"]["t_ptp_z_95"], 0.0)

    def test_report_uptime_no_problems(self):
        start_of_report_hour = get_hourly_report_time()
        uptime = StatusData._get_uptime_one_hour(self.session, start_of_report_hour)
        self.assertEqual(uptime, 1.0)

    def test_report_uptime_all_problem(self):
        start_of_report_hour = get_hourly_report_time()
        self._create_problem(
            started_at=start_of_report_hour - timedelta(seconds=1),
            ended_at=None,
            confidence=99.00,
        )
        uptime = StatusData._get_uptime_one_hour(self.session, start_of_report_hour)
        self.assertEqual(uptime, 0.0)

    def test_report_uptime_ongoing_problem(self):
        start_of_report_hour = get_hourly_report_time()
        self._create_problem(
            started_at=start_of_report_hour + timedelta(minutes=30),
            ended_at=None,
            confidence=99.00,
        )
        uptime = StatusData._get_uptime_one_hour(self.session, start_of_report_hour)
        self.assertEqual(round(uptime, 1), 0.5)

    def test_report_uptime_problem_started_and_ended(self):
        start_of_report_hour = get_hourly_report_time()
        self._create_problem(
            started_at=start_of_report_hour + timedelta(minutes=1),
            ended_at=start_of_report_hour + timedelta(minutes=16),
            confidence=99.00,
        )
        uptime = StatusData._get_uptime_one_hour(self.session, start_of_report_hour)
        self.assertEqual(round(uptime, 2), 0.75)

    def test_report_uptime_problem_ended(self):
        start_of_report_hour = get_hourly_report_time()
        self._create_problem(
            started_at=start_of_report_hour - timedelta(hours=48),
            ended_at=start_of_report_hour + timedelta(minutes=6),
            confidence=99.00,
        )
        uptime = StatusData._get_uptime_one_hour(self.session, start_of_report_hour)
        self.assertEqual(round(uptime, 2), 0.90)

    def test_report_uptime_two_problems(self):
        start_of_report_hour = get_hourly_report_time()
        self._create_problem(
            started_at=start_of_report_hour + timedelta(minutes=10),
            ended_at=start_of_report_hour + timedelta(minutes=20),
            confidence=99.00,
        )
        self._create_problem(
            started_at=start_of_report_hour + timedelta(minutes=30),
            ended_at=start_of_report_hour + timedelta(minutes=50),
            confidence=99.00,
        )
        uptime = StatusData._get_uptime_one_hour(self.session, start_of_report_hour)
        self.assertEqual(round(uptime, 2), 0.50)

    def test_max_and_min_trip_duration_one_trip(self):
        rgen = RGenerator()
        last_report_time = get_hourly_report_time() - timedelta(hours=1)
        rgen.saved_values[rgen.name_last_hourly_report] = last_report_time
        next_report_time = last_report_time + timedelta(hours=1)
        trip_duration = 20
        trip_offset = 600
        self.testutils.insert_trip(
            starts_at=next_report_time + timedelta(seconds=trip_offset),
            ends_at=next_report_time + timedelta(seconds=trip_offset + trip_duration),
        )
        rgen.generate_reports(self.session)
        row = get_latest_data_to_send(self.session)

        self.assertEqual(row.payload["max_trip_duration"], trip_duration)
        self.assertEqual(row.payload["min_trip_duration"], trip_duration)

    def test_max_and_min_trip_duration_multiple_trips(self):
        rgen = RGenerator()
        last_report_time = get_hourly_report_time() - timedelta(hours=2)
        rgen.saved_values[rgen.name_last_hourly_report] = last_report_time
        next_report_time = last_report_time + timedelta(hours=1)
        trip_duration_1 = 20
        trip_duration_2 = 8
        trip_duration_3 = 15
        trip_offset_1 = 100
        trip_offset_2 = 200
        trip_offset_3 = 300
        self.testutils.insert_trip(
            starts_at=next_report_time + timedelta(seconds=trip_offset_1),
            ends_at=next_report_time
            + timedelta(seconds=trip_offset_1 + trip_duration_1),
        )
        self.testutils.insert_trip(
            starts_at=next_report_time + timedelta(seconds=trip_offset_2),
            ends_at=next_report_time
            + timedelta(seconds=trip_offset_2 + trip_duration_2),
        )
        self.testutils.insert_trip(
            starts_at=next_report_time + timedelta(seconds=trip_offset_3),
            ends_at=next_report_time
            + timedelta(seconds=trip_offset_3 + trip_duration_3),
        )
        rgen.generate_reports(self.session)
        row = get_latest_data_to_send(self.session)

        self.assertEqual(row.payload["max_trip_duration"], trip_duration_1)
        self.assertEqual(row.payload["min_trip_duration"], trip_duration_2)

    def test_max_and_min_trip_duration_no_trips(self):
        rgen = RGenerator()
        last_report_time = get_hourly_report_time() - timedelta(hours=1)
        rgen.saved_values[rgen.name_last_hourly_report] = last_report_time
        rgen.generate_reports(self.session)
        row = get_latest_data_to_send(self.session)

        self.assertNotIn("max_trip_duration", row.payload)
        self.assertNotIn("min_trip_duration", row.payload)
        # Check that vibration is gone while we're here
        self.assertNotIn("overall_trip_vibration", row.payload)

    def test_duty_cycle_normal_case(self):
        report_time = get_hourly_report_time()
        for i in range(30):
            self.testutils.insert_trip(
                starts_at=report_time + timedelta(minutes=i),
                ends_at=report_time + timedelta(minutes=i, seconds=30),
            )
        rgen = RGenerator()
        rgen.saved_values[rgen.name_last_hourly_report] = report_time - timedelta(
            hours=1
        )
        rgen.generate_reports(self.session)
        row = get_latest_data_to_send(self.session)
        self.assertEqual(row.payload["duty_cycle"], 0.25)

    def test_duty_cycle_high(self):
        report_time = get_hourly_report_time()
        for i in range(60):
            self.testutils.insert_trip(
                starts_at=report_time + timedelta(minutes=i),
                ends_at=report_time + timedelta(minutes=i, seconds=54),
            )
        rgen = RGenerator()
        rgen.saved_values[rgen.name_last_hourly_report] = report_time - timedelta(
            hours=1
        )
        rgen.generate_reports(self.session)
        row = get_latest_data_to_send(self.session)

        self.assertEqual(row.payload["duty_cycle"], 0.90)

    def test_duty_cycle_no_trips(self):
        report_time = get_hourly_report_time()
        rgen = RGenerator()
        rgen.saved_values[rgen.name_last_hourly_report] = report_time - timedelta(
            hours=1
        )
        rgen.generate_reports(self.session)
        row = get_latest_data_to_send(self.session)

        self.assertEqual(row.payload["duty_cycle"], 0.0)

    def test_releveling_data_is_not_present_if_no_data(self):
        report_time = get_hourly_report_time()
        hourly_report = StatusData.get_hourly_report_payload(self.session, report_time)
        self.assertNotIn("releveling", hourly_report)

    def test_releveling_data_is_present_if_releveling(self):
        report_time = get_hourly_report_time()

        self.testutils.create_problem(
            problem_type=common_constants.PROB_TYPE_ANOMALY,
            problem_subtype=common_constants.PROB_SUBTYPE_RELEVELING,
            started_at=report_time,
        )

        hourly_report = StatusData.get_hourly_report_payload(self.session, report_time)

        self.assertIn("releveling", hourly_report)
        self.assertIn("start_detected", hourly_report["releveling"])
        self.assertIn("end_detected", hourly_report["releveling"])
        self.assertIn("count", hourly_report["releveling"])

    @patch("report_generator.status_data.getloadavg")
    def test_system_load_avg(self, getloadavg):
        report_time = get_hourly_report_time()

        load_avg = 0.15
        getloadavg.return_value = (0, 0, load_avg)
        hourly_report = StatusData.get_hourly_report_payload(self.session, report_time)

        self.assertIn("system", hourly_report)
        self.assertIn("load_avg", hourly_report["system"])
        self.assertEqual(hourly_report["system"]["load_avg"], load_avg)

    def test_initial_storage_values(self):
        rgen = RGenerator()
        self.assertEqual(
            rgen.saved_values[rgen.name_last_hourly_report],
            pytz.utc.localize(datetime.utcnow()).replace(
                minute=0, second=0, microsecond=0
            )
            - timedelta(hours=1),
        )

    def test_save_initial_storage_values(self):
        RGenerator()
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    common_constants.STORAGE_FOLDER, constants.STORAGE_FILE_NAME
                )
            ),
            "Report generator should save initial defaults to pickle file immediately",
        )

    def test_corrupted_storage_files(self):
        # Create an empty storage file
        open(
            os.path.join(common_constants.STORAGE_FOLDER, constants.STORAGE_FILE_NAME),
            "a",
        ).close()
        RGenerator()  # Should not raise an exception
        self.assertTrue(True)

    def test_save_and_restore(self):
        rgen = RGenerator()
        last_hourly = rgen.saved_values[rgen.name_last_hourly_report] - timedelta(
            hours=1
        )
        rgen._save_last_hourly_report_time(last_hourly)
        del rgen
        rgen2 = RGenerator()
        self.assertEqual(rgen2.saved_values[rgen2.name_last_hourly_report], last_hourly)

    def test_migration_on_existing_devices(self):
        rgen = RGenerator()
        rgen._save_last_hourly_report_time(datetime.now())
        rgen._restore_last_hourly_report_time()
        self.assertIsNotNone(
            rgen.saved_values[rgen.name_last_hourly_report].tzinfo,
            "Report generator doesn't migrate non-UTC-localized last hourly report times",
        )
        rgen._save_last_hourly_report_time(datetime.now())
        del rgen
        rgen2 = RGenerator()
        self.assertIsNotNone(
            rgen2.saved_values[rgen2.name_last_hourly_report].tzinfo,
            "Report generator doesn't migrate non-UTC-localized last hourly report times after restart",
        )


class StatusDataTest(unittest.TestCase):
    testutils = TestUtilities()

    def _delete_stuff(self):
        self.session.query(Trip).delete()
        self.session.query(Acceleration).delete()
        self.session.query(DataToSend).delete()
        self.session.query(Event).delete()

    def setUp(self):
        self.session = Session()
        self.testutils = TestUtilities(self.session)
        self._delete_stuff()

    def tearDown(self):
        self._delete_stuff()
        self.session.rollback()
        self.session.close()

    def test_releveling_open_is_reported(self):
        report_time = get_hourly_report_time()
        end_of_hour = report_time + timedelta(hours=1)

        self.testutils.create_problem(
            problem_type=common_constants.PROB_TYPE_ANOMALY,
            problem_subtype=common_constants.PROB_SUBTYPE_RELEVELING,
            created_at=report_time,
            started_at=report_time,
        )

        result = StatusData._get_releveling_data(self.session, report_time, end_of_hour)
        self.assertTrue(result.start_detected)

    def test_releveling_close_is_reported(self):
        report_time = get_hourly_report_time()
        end_of_hour = report_time + timedelta(hours=1)

        self.testutils.create_problem(
            problem_type=common_constants.PROB_TYPE_ANOMALY,
            problem_subtype=common_constants.PROB_SUBTYPE_RELEVELING,
            started_at=report_time - timedelta(hours=1),
            ended_at=report_time,
        )

        result = StatusData._get_releveling_data(self.session, report_time, end_of_hour)
        self.assertTrue(result.end_detected)

    def test_releveling_events_count_is_reported(self):
        report_time = get_hourly_report_time()
        end_of_hour = report_time + timedelta(hours=1)

        self.testutils.create_problem(
            problem_type=common_constants.PROB_TYPE_ANOMALY,
            problem_subtype=common_constants.PROB_SUBTYPE_RELEVELING,
            started_at=report_time,
            ended_at=end_of_hour,
        )

        NUM_EXPECTED_RELEVELINGS = 3
        for i in range(NUM_EXPECTED_RELEVELINGS):
            self.testutils.create_event(
                event_type=common_constants.EVENT_TYPE_ANOMALY,
                subtype=common_constants.EVENT_SUBTYPE_RELEVELING,
                occurred_at=report_time + timedelta(minutes=i * 2),
                detected_at=report_time + timedelta(minutes=i * 2),
            )

        result = StatusData._get_releveling_data(self.session, report_time, end_of_hour)
        self.assertEqual(result.count, NUM_EXPECTED_RELEVELINGS)

    @patch("report_generator.status_data.StatusData._run_vibration_sql_query")
    def test_customer_vibration_data(self, run_vibration_sql_query):
        random.seed(1234)
        status_data = StatusData()
        start_time = (
            pytz.utc.localize(datetime.utcnow()) - timedelta(hours=1)
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        vibration_data = self.generate_customer_vibration_sql_data()
        run_vibration_sql_query.return_value = vibration_data
        result_vibration_data = status_data._get_vibration_data(
            self.session, start_time
        )
        self.verify_customer_vibration_sql_data(result_vibration_data, vibration_data)

    def verify_customer_vibration_sql_data(self, actual_data, generated_data):
        # First we need to figure out which row in the generated data
        # corresponds to which type.
        type_index_map = {}
        types = list(vibration_prefix_map.keys())
        index = 0
        for type in types:
            type_index_map[vibration_prefix_map[type]] = index
            index += 1

        for item in actual_data:
            gen_row = type_index_map[item[:2]]
            self.assertEqual(actual_data[item], generated_data[gen_row][item[2:]])

    def generate_customer_vibration_sql_data(self):
        vibration_data = []
        # The type index map allows us to convert retrieve the original values.
        types = list(vibration_prefix_map.keys())
        for type in types:
            vibration_set = self.generate_customer_vibration_set(type)
            vibration_set["type"] = type
            vibration_data.append(vibration_set)
        return vibration_data

    def generate_customer_vibration_set(self, type):
        """
        Generate random customer vibration data for an acceleration or trip.
        """
        self.assertIn(type, list(vibration_prefix_map.keys()))
        trip_type = "trip"
        self.assertIn(
            trip_type,
            list(vibration_prefix_map.keys()),
            "Trip type was changed, need to fix test",
        )
        is_trip = type == trip_type
        row = {}
        for field in vibration_fields:
            if is_trip and "jerk" in field:
                # No trip jerk values
                continue
            row[field] = round(float(random.uniform(0.0, 1000.0)), 2)
        return row

    def generate_psd_vibration_set(self):
        # Power spectral density, used internally for machine learning, not reports.
        return {
            "f0": round(float(random.uniform(0.0, 3000.0)), 2),
            "f1": round(float(random.uniform(0.0, 3000.0)), 2),
            "f2": round(float(random.uniform(0.0, 3000.0)), 2),
            "f3": round(float(random.uniform(0.0, 3000.0)), 2),
            "f4": round(float(random.uniform(0.0, 3000.0)), 2),
            "f5": round(float(random.uniform(0.0, 3000.0)), 2),
            "f6": round(float(random.uniform(0.0, 3000.0)), 2),
            "f7": round(float(random.uniform(0.0, 3000.0)), 2),
            "f8": round(float(random.uniform(0.0, 3000.0)), 2),
            "f9": round(float(random.uniform(0.0, 3000.0)), 2),
            "f10": round(float(random.uniform(0.0, 3000.0)), 2),
            "f11": round(float(random.uniform(0.0, 3000.0)), 2),
            "f12": round(float(random.uniform(0.0, 3000.0)), 2),
            "f13": round(float(random.uniform(0.0, 3000.0)), 2),
        }

    def generate_all_psd_vibration_data(self, is_trip):
        psd_vibration_data = {
            "x_psd": self.generate_psd_vibration_set(),
            "y_psd": self.generate_psd_vibration_set(),
            "z_psd": self.generate_psd_vibration_set(),
        }
        customer_vibration_data = self.generate_psd_vibration_set()
        return {**psd_vibration_data, **customer_vibration_data}

    def test_run_vibration_sql_query(self):
        random.seed(1234)
        report_time = get_hourly_report_time()
        mid_report_time = report_time + timedelta(minutes=30)
        # Create the vibration data for two trips and associated accelerations.
        start_vibration_1 = self.generate_customer_vibration_set("start_accel")
        start_vibration_2 = self.generate_customer_vibration_set("start_accel")
        end_vibration_1 = self.generate_customer_vibration_set("end_accel")
        end_vibration_2 = self.generate_customer_vibration_set("end_accel")
        trip_vibration_1 = self.generate_customer_vibration_set("trip")
        trip_vibration_2 = self.generate_customer_vibration_set("trip")

        params = {
            "start_time": mid_report_time,
            "is_start_of_trip": True,
            "vibration": start_vibration_1,
        }
        self.session.add(Acceleration(**params))
        params["vibration"] = start_vibration_2
        self.session.add(Acceleration(**params))
        params = {
            "start_time": mid_report_time,
            "is_start_of_trip": False,
            "vibration": end_vibration_1,
        }
        self.session.add(Acceleration(**params))
        params["vibration"] = end_vibration_2
        self.session.add(Acceleration(**params))
        params = {
            "start_time": mid_report_time,
            "vibration": trip_vibration_1,
        }
        self.session.add(Trip(**params))
        params["vibration"] = trip_vibration_2
        self.session.add(Trip(**params))

        # Run the SQL query to get the vibration data.
        status_data = StatusData()
        actual_data = status_data._run_vibration_sql_query(
            self.session, report_time, report_time + timedelta(hours=1)
        )
        for row in actual_data:
            type = row["type"]
            if type == "start_accel":
                gen_data_1 = start_vibration_1
                gen_data_2 = start_vibration_2
                has_jerk = True
            elif type == "end_accel":
                gen_data_1 = end_vibration_1
                gen_data_2 = end_vibration_2
                has_jerk = True
            elif type == "trip":
                gen_data_1 = trip_vibration_1
                gen_data_2 = trip_vibration_2
                has_jerk = False
            else:
                self.fail("Unrecognized type {0}".format(type))

            if has_jerk:
                # self.assertEqual(row["max_jerk"], gen_data["jerk"])
                self.assertAlmostEqual(
                    float(row["avg_jerk"]),
                    avg(gen_data_1["avg_jerk"], gen_data_2["avg_jerk"]),
                    delta=0.01,
                )
                self.assertAlmostEqual(
                    float(row["max_jerk"]),
                    max(gen_data_1["max_jerk"], gen_data_2["max_jerk"]),
                    delta=0.01,
                )
            else:
                # fields without values will get removed before going into the report
                self.assertIsNone(
                    row["avg_jerk"], msg="Trips should not have jerk values"
                )
                self.assertNotIn(
                    row["max_jerk"], row, msg="Trips should not have jerk values"
                )

            self.assertAlmostEqual(
                float(row["ptp_x_95"]),
                avg(gen_data_1["ptp_x_95"], gen_data_2["ptp_x_95"]),
                delta=0.01,
            )
            self.assertAlmostEqual(
                float(row["ptp_y_95"]),
                avg(gen_data_1["ptp_y_95"], gen_data_2["ptp_y_95"]),
                delta=0.01,
            )
            self.assertAlmostEqual(
                float(row["ptp_z_95"]),
                avg(gen_data_1["ptp_z_95"], gen_data_2["ptp_z_95"]),
                delta=0.01,
            )

            self.assertAlmostEqual(
                float(row["ptp_x_max"]),
                max(gen_data_1["ptp_x_max"], gen_data_2["ptp_x_max"]),
                delta=0.01,
            )
            self.assertAlmostEqual(
                float(row["ptp_y_max"]),
                max(gen_data_1["ptp_y_max"], gen_data_2["ptp_y_max"]),
                delta=0.01,
            )
            self.assertAlmostEqual(
                float(row["ptp_z_max"]),
                max(gen_data_1["ptp_z_max"], gen_data_2["ptp_z_max"]),
                delta=0.01,
            )


if __name__ == "__main__":
    unittest.main()
