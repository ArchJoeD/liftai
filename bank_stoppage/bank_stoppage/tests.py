import os
import unittest
from math import ceil
from time import sleep
from datetime import datetime, timedelta
from unittest.mock import Mock, ANY

import pytz

from bank_stoppage import constants
from bank_stoppage.processor import BankStoppageProcessor, ShutdownDetectionResult
from utilities import common_constants
from utilities.db_utilities import engine
from utilities.stoppage_processor import StoppageState
from utilities.test_utilities import TestUtilities


class TestCommon(unittest.TestCase):
    start_time = datetime.now()
    testutil = TestUtilities()
    first_bank_trip_time = (
        datetime.now()
    )  # This can be modified below if we add bank trips earlier than now.

    def _delete_all_bank_trips(self):
        self.testutil.delete_trips()
        with engine.connect() as con:
            con.execute("DELETE FROM bank_trips")

    def _delete_data(self):
        self.testutil.delete_trips()
        self._delete_all_bank_trips()
        with engine.connect() as con:
            con.execute(
                "DELETE FROM events WHERE occurred_at > '%s'"
                % (self.start_time - timedelta(minutes=241))
            )

    def setUp(self):
        self._delete_all_bank_trips()
        self._delete_data()
        config = {"type": "elevator", common_constants.CONFIG_STOPPAGE_THRESHOLD: "DF"}
        self.testutil.set_config(config)

    def tearDown(self):
        self._delete_data()
        for item in os.listdir(common_constants.STORAGE_FOLDER):
            if item.endswith(".pkl"):
                os.remove(os.path.join(common_constants.STORAGE_FOLDER, item))

    def _get_bank_instance(self, is_accel_running=True):
        bsp = BankStoppageProcessor()
        bsp._is_accelerometer_working = Mock(return_value=is_accel_running)
        bsp.logger = Mock()
        return bsp


class TestBankStoppage(TestCommon):
    def test_can_run_bank_stoppage(self):
        proc = self._get_bank_instance()
        proc.run()

    def test_confidences(self):
        proc = self._get_bank_instance()
        proc.run()
        conf2 = proc._get_confidences_for_elevators(2)
        conf3 = proc._get_confidences_for_elevators(3)
        conf4 = proc._get_confidences_for_elevators(4)
        conf8 = proc._get_confidences_for_elevators(8)
        self.assertTrue(
            conf2["90"] < conf3["90"],
            "more elevators in a bank should mean more trips needed for 90% confidence",
        )
        self.assertTrue(
            conf3["90"] < conf4["90"],
            "more elevators in a bank should mean more trips needed for 90% confidence",
        )
        self.assertTrue(
            conf8["99"] > 0,
            "Need to have confidence numbers for a bank of up to 8 elevators",
        )
        # Do a sampling of thresholds and confidence levels.
        self.testutil.set_config_threshold("VI")
        conf4_vi = proc._get_confidences_for_elevators(4)
        self.assertTrue(conf4["95"] < conf4_vi["95"])
        self.testutil.set_config_threshold("LO")
        conf2_lo = proc._get_confidences_for_elevators(2)
        self.assertTrue(conf2["99"] > conf2_lo["99"])

    def test_basic_shutdown(self):
        proc = self._get_bank_instance()
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.OK)
        self.first_bank_trip_time = datetime.now(pytz.utc) - timedelta(minutes=25)
        last_trip_time = self.first_bank_trip_time - timedelta(minutes=10)
        self.testutil.insert_trip(
            starts_at=last_trip_time, ends_at=last_trip_time + timedelta(seconds=5)
        )
        self.testutil.insert_bank_trips(1000, 2, self.first_bank_trip_time)
        proc.run()
        self.assertTrue(proc.last_state > StoppageState.OK)
        events = self.testutil.get_events(last_trip_time)
        self.assertTrue(len(events) == 1)
        event = events[0]
        self.assertTrue(event["occurred_at"] >= last_trip_time)
        self.assertTrue(event["event_type"] == common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertTrue(event["event_subtype"] == common_constants.EVENT_SUBTYPE_BANK)
        self.assertTrue(event["confidence"] > 00.00)

    def test_zero_bank_trips(self):
        self._delete_all_bank_trips()
        proc = self._get_bank_instance()
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.OK)

        last_trip_time = self.first_bank_trip_time - timedelta(minutes=10)
        self.testutil.insert_trip(
            starts_at=last_trip_time, ends_at=last_trip_time + timedelta(seconds=5)
        )
        proc.run()
        self.assertTrue(proc.last_state <= StoppageState.OK)

        events = self.testutil.get_events(last_trip_time)
        self.assertTrue(len(events) == 0)

    def test_shutdown_and_resume(self):
        proc = self._get_bank_instance()
        thresholds = proc._get_confidences_for_elevators(2)
        self.first_bank_trip_time = datetime.now(pytz.utc) - timedelta(minutes=25)
        last_trip_time = self.first_bank_trip_time - timedelta(minutes=10)
        self.testutil.insert_trip(
            starts_at=last_trip_time,
            ends_at=self.first_bank_trip_time + timedelta(minutes=10, seconds=30),
        )
        self.testutil.insert_bank_trips(0, 2, self.first_bank_trip_time)
        sleep(0.05)
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.OK)

        self.testutil.insert_bank_trips(
            thresholds["90"] - 1,
            2,
            ts=self.first_bank_trip_time + timedelta(seconds=60),
        )
        sleep(0.05)
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.OK)

        self.testutil.insert_bank_trips(
            2, 2, ts=self.first_bank_trip_time + timedelta(seconds=90)
        )
        sleep(0.05)
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.STOPPED_C90)

        events = self.testutil.get_events(self.start_time - timedelta(minutes=60))
        self.assertTrue(len(events) == 1)

        event = events[0]
        self.assertTrue(event["occurred_at"] >= last_trip_time)
        self.assertTrue(event["event_type"] == common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertTrue(event["event_subtype"] == common_constants.EVENT_SUBTYPE_BANK)
        self.assertTrue(event["confidence"] == 90.00)
        self.testutil.insert_bank_trips(
            thresholds["95"] - thresholds["90"],
            2,
            ts=self.first_bank_trip_time + timedelta(seconds=120),
        )
        sleep(0.05)
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.STOPPED_C95)

        events = self.testutil.get_events(self.start_time - timedelta(minutes=60))
        self.assertTrue(len(events) == 2)

        event = events[1]
        print(
            "next event: id={0}, confidence = {1}".format(
                str(event["id"]), str(event["confidence"])
            )
        )
        self.assertTrue(event["occurred_at"] >= last_trip_time)
        self.assertTrue(event["event_type"] == common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertTrue(event["event_subtype"] == common_constants.EVENT_SUBTYPE_BANK)
        self.assertTrue(event["confidence"] == 95.00)
        self.testutil.insert_bank_trips(
            thresholds["99"] - thresholds["95"],
            2,
            ts=self.first_bank_trip_time + timedelta(seconds=150),
        )
        sleep(0.05)
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.STOPPED_C99)

        events = self.testutil.get_events(self.start_time - timedelta(minutes=60))
        self.assertTrue(len(events) == 3)

        event = events[2]
        self.assertTrue(event["occurred_at"] >= last_trip_time)
        self.assertTrue(event["event_type"] == common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertTrue(event["event_subtype"] == common_constants.EVENT_SUBTYPE_BANK)
        self.assertTrue(event["confidence"] == 99.00)
        self.testutil.insert_trip()
        sleep(0.05)
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.OK)

        events = self.testutil.get_events(self.start_time - timedelta(minutes=60))
        self.assertTrue(len(events) == 4)

        event = events[3]
        self.assertTrue(event["occurred_at"] >= last_trip_time)
        self.assertTrue(event["event_type"] == common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertTrue(event["event_subtype"] == common_constants.EVENT_SUBTYPE_BANK)
        self.assertTrue(event["confidence"] == 00.00)


class TestSelfLearningBankStoppage(TestCommon):
    first_bank_trip_time = datetime.now() - timedelta(days=2)

    def _insert_many_trips(self, count=constants.MINIMUM_SELFLEARNING_SELF_TRIPS + 1):
        # We insert a lot of trips here to get over the learning threshold.
        with engine.connect() as con:
            trans = con.begin()
            for i in range(0, count):
                start_time = datetime.now() - timedelta(days=1, seconds=i * 10)
                end_time = start_time + timedelta(seconds=6)
                self.testutil.insert_trips_bulk(
                    con, starts_at=start_time, ends_at=end_time
                )
            trans.commit()

    def setUp(self):
        super().setUp()
        self._insert_many_trips()
        self.testutil.insert_bank_trips(
            constants.MINIMUM_SELFLEARNING_BANK_TRIPS + 5,
            2,
            ts=self.first_bank_trip_time,
        )

    def test_can_run_in_stopped_c90(self):
        proc = self._get_bank_instance()
        proc.last_state = StoppageState.STOPPED_C90
        proc.run()

    def test_can_run_in_stopped_c95(self):
        proc = self._get_bank_instance()
        proc.last_state = StoppageState.STOPPED_C95
        proc.run()

    def test_can_run_in_stopped_c99(self):
        proc = self._get_bank_instance()
        proc.last_state = StoppageState.STOPPED_C99
        proc.run()

    def test_can_recover_from_c90(self):
        proc = self._get_bank_instance()
        proc._update_state(StoppageState.STOPPED_C90)
        proc = self._get_bank_instance()
        proc.run()

    def test_can_recover_from_c95(self):
        proc = self._get_bank_instance()
        proc._update_state(StoppageState.STOPPED_C95)
        proc = self._get_bank_instance()
        proc.run()

    def test_can_recover_from_c99(self):
        proc = self._get_bank_instance()
        proc._update_state(StoppageState.STOPPED_C99)
        proc = self._get_bank_instance()
        proc.run()

    def test_basic_shutdown(self):
        self._delete_data()
        self._insert_many_trips()
        proc = self._get_bank_instance()
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.OK)

        self.first_bank_trip_time = datetime.now(pytz.utc) - timedelta(minutes=25)
        last_trip_time = self.first_bank_trip_time - timedelta(minutes=10)
        self.testutil.insert_trip(
            starts_at=last_trip_time, ends_at=last_trip_time + timedelta(seconds=5)
        )
        self.testutil.insert_bank_trips(1000, 2, self.first_bank_trip_time)
        proc.run()

        self.assertTrue(proc.last_state > StoppageState.OK)
        events = self.testutil.get_events(last_trip_time)
        self.assertTrue(len(events) == 1)
        event = events[0]
        self.assertTrue(event["occurred_at"] >= last_trip_time)
        self.assertTrue(event["event_type"] == common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertTrue(event["event_subtype"] == common_constants.EVENT_SUBTYPE_BANK)
        self.assertTrue(event["confidence"] > 00.00)

    def test_self_learning_on(self):
        lt_time = datetime.now() - timedelta(hours=2)
        self._delete_data()
        proc = self._get_bank_instance()
        self.assertTrue(
            constants.MINIMUM_SELFLEARNING_BANK_TRIPS
            > constants.MINIMUM_SELFLEARNING_SELF_TRIPS,
            "Can't have minimum self trips greater than min bank trips for self learning",
        )
        trip_ratio = (constants.MINIMUM_SELFLEARNING_SELF_TRIPS + 1) / (
            constants.MINIMUM_SELFLEARNING_BANK_TRIPS + 1
        )
        thresh90 = int(constants.CONFIDENCE_TABLE["DF"][2][0] / (trip_ratio * 2))
        thresh95 = int(constants.CONFIDENCE_TABLE["DF"][2][1] / (trip_ratio * 2))
        thresh99 = int(constants.CONFIDENCE_TABLE["DF"][2][2] / (trip_ratio * 2))
        self._insert_many_trips(count=constants.MINIMUM_SELFLEARNING_SELF_TRIPS + 1)
        self.testutil.insert_bank_trips(
            constants.MINIMUM_SELFLEARNING_BANK_TRIPS + 1,
            8,
            ts=lt_time - timedelta(hours=12),
        )
        self.testutil.insert_trip(
            starts_at=lt_time, ends_at=lt_time + timedelta(seconds=5)
        )
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.OK)
        self.testutil.insert_bank_trips(
            thresh90 - 2, 8, ts=lt_time + timedelta(minutes=4)
        )
        proc.run()
        self.assertTrue(
            proc.last_state == StoppageState.OK,
            "Expected OK, got {0}".format(proc.last_state),
        )
        self.testutil.insert_bank_trips(4, 8, ts=lt_time + timedelta(minutes=5))
        proc.run()
        self.assertTrue(
            proc.last_state == StoppageState.STOPPED_C90,
            "Expected 90, got {0}".format(proc.last_state),
        )
        self.testutil.insert_bank_trips(
            thresh95 - thresh90, 8, ts=lt_time + timedelta(minutes=6)
        )
        proc.run()
        self.assertTrue(
            proc.last_state == StoppageState.STOPPED_C95,
            "Expected 95, got {0}".format(proc.last_state),
        )
        self.testutil.insert_bank_trips(
            thresh99 - thresh95, 8, ts=lt_time + timedelta(minutes=7)
        )
        proc.run()
        self.assertTrue(
            proc.last_state == StoppageState.STOPPED_C99,
            "Expected 99, got {0}".format(proc.last_state),
        )
        self.testutil.insert_trip(starts_at=datetime.now())
        proc.run()
        self.assertTrue(
            proc.last_state == StoppageState.OK,
            "Expected OK, got {0}".format(proc.last_state),
        )

    def test_self_learning_off(self):
        self._delete_data()
        proc = self._get_bank_instance()
        lt_time = datetime.now() - timedelta(hours=2)
        self._insert_many_trips(count=constants.MINIMUM_SELFLEARNING_SELF_TRIPS - 1)
        self.testutil.insert_bank_trips(
            constants.MINIMUM_SELFLEARNING_BANK_TRIPS - 1,
            4,
            ts=lt_time - timedelta(hours=24),
        )
        self.testutil.insert_trip(
            starts_at=lt_time, ends_at=lt_time + timedelta(seconds=2)
        )
        self.testutil.insert_bank_trips(
            constants.CONFIDENCE_TABLE["DF"][3][0] - 2,
            3,
            ts=lt_time + timedelta(minutes=4),
        )
        proc.run()
        self.assertTrue(
            proc.last_state == StoppageState.OK,
            "Expected OK, got {0}".format(proc.last_state),
        )
        self.testutil.insert_bank_trips(4, 3, ts=lt_time + timedelta(minutes=5))
        proc.run()
        self.assertTrue(
            proc.last_state == StoppageState.STOPPED_C90,
            "Expected 90, got {0}".format(proc.last_state),
        )
        self.testutil.insert_bank_trips(
            constants.CONFIDENCE_TABLE["DF"][3][1]
            - constants.CONFIDENCE_TABLE["DF"][3][0],
            3,
            ts=lt_time + timedelta(minutes=6),
        )
        proc.run()
        self.assertTrue(
            proc.last_state == StoppageState.STOPPED_C95,
            "Expected 95, got {0}".format(proc.last_state),
        )
        self.testutil.insert_bank_trips(
            constants.CONFIDENCE_TABLE["DF"][3][2]
            - constants.CONFIDENCE_TABLE["DF"][3][1],
            3,
            ts=lt_time + timedelta(minutes=7),
        )
        proc.run()
        self.assertTrue(
            proc.last_state == StoppageState.STOPPED_C99,
            "Expected 99, got {0}".format(proc.last_state),
        )
        self.testutil.insert_trip(starts_at=datetime.now())
        proc.run()
        self.assertTrue(
            proc.last_state == StoppageState.OK,
            "Expected OK, got {0}".format(proc.last_state),
        )

    def test_shutdown_and_resume(self):
        proc = self._get_bank_instance()
        thresholds = proc._get_confidences_for_elevators(2)
        self._insert_many_trips(count=200)
        self.testutil.insert_bank_trips(400, 2, ts=self.first_bank_trip_time)
        self.first_bank_trip_time = datetime.now(pytz.utc) - timedelta(minutes=25)
        last_trip_time = self.first_bank_trip_time - timedelta(minutes=10)
        self.testutil.insert_trip(
            starts_at=last_trip_time,
            ends_at=self.first_bank_trip_time + timedelta(minutes=10, seconds=30),
        )
        self.testutil.insert_bank_trips(0, 2, self.first_bank_trip_time)
        sleep(0.05)
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.OK)
        self.testutil.insert_bank_trips(
            thresholds["90"] - 10,
            2,
            ts=self.first_bank_trip_time + timedelta(seconds=60),
        )
        sleep(0.05)
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.OK)
        self.testutil.insert_bank_trips(
            50, 2, ts=self.first_bank_trip_time + timedelta(seconds=90)
        )
        sleep(0.05)
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.STOPPED_C90)
        events = self.testutil.get_events(self.start_time - timedelta(minutes=60))
        self.assertTrue(len(events) == 1)
        event = events[0]
        self.assertTrue(event["occurred_at"] >= last_trip_time)
        self.assertTrue(event["event_type"] == common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertTrue(event["event_subtype"] == common_constants.EVENT_SUBTYPE_BANK)
        self.assertTrue(event["confidence"] == 90.00)
        self.testutil.insert_bank_trips(
            thresholds["95"] - thresholds["90"],
            2,
            ts=self.first_bank_trip_time + timedelta(seconds=120),
        )
        sleep(0.05)
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.STOPPED_C95)
        events = self.testutil.get_events(self.start_time - timedelta(minutes=60))
        self.assertTrue(len(events) == 2)
        event = events[1]
        print(
            "next event: id={0}, confidence = {1}".format(
                str(event["id"]), str(event["confidence"])
            )
        )
        self.assertTrue(event["occurred_at"] >= last_trip_time)
        self.assertTrue(event["event_type"] == common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertTrue(event["event_subtype"] == common_constants.EVENT_SUBTYPE_BANK)
        self.assertTrue(event["confidence"] == 95.00)
        self.testutil.insert_bank_trips(
            48 + thresholds["99"] - thresholds["95"],
            2,
            ts=self.first_bank_trip_time + timedelta(seconds=150),
        )
        sleep(0.05)
        proc.run()
        self.assertTrue(
            proc.last_state == StoppageState.STOPPED_C99,
            "Expecting 99%, got {0}".format(proc.last_state),
        )
        events = self.testutil.get_events(self.start_time - timedelta(minutes=60))
        self.assertTrue(len(events) == 3)
        event = events[2]
        self.assertTrue(event["occurred_at"] >= last_trip_time)
        self.assertTrue(event["event_type"] == common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertTrue(event["event_subtype"] == common_constants.EVENT_SUBTYPE_BANK)
        self.assertTrue(
            event["confidence"] == 99.00,
            "Expecting 99%, got {0}".format(event["confidence"]),
        )
        self.testutil.insert_trip()
        sleep(0.05)
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.OK)
        events = self.testutil.get_events(self.start_time - timedelta(minutes=60))
        self.assertTrue(len(events) == 4)
        event = events[3]
        self.assertTrue(event["occurred_at"] >= last_trip_time)
        self.assertTrue(event["event_type"] == common_constants.EVENT_TYPE_SHUTDOWN)
        self.assertTrue(event["event_subtype"] == common_constants.EVENT_SUBTYPE_BANK)
        self.assertTrue(event["confidence"] == 00.00)

    def test_insane_ratio_greather_than_0_5_uses_0_5_ratio_instead(self):
        proc = self._get_bank_instance()
        confidences_for_bank_of_2 = proc._get_confidences_for_elevators(2)

        bt_last_two_weeks = 40
        non_scaled_bank_trip_threshold = confidences_for_bank_of_2[
            str(StoppageState.STOPPED_C90)
        ]

        # Verify the threshold for stoppage is where we expect
        ot_last_two_weeks = bt_last_two_weeks * 0.5
        bt_since_last_trip = non_scaled_bank_trip_threshold
        result = proc.self_learning_detection(
            bt_last_two_weeks,
            ot_last_two_weeks,
            bt_since_last_trip,
            confidences_for_bank_of_2,
        )
        self.assertEqual(
            result,
            ShutdownDetectionResult(
                is_shutdown=True, confidence=StoppageState.STOPPED_C90
            ),
        )

        # Go one under the threshold
        # If the ratio is being limited as expected, no multiplier greater than 0.5 on ot_last_two_weeks should cause a shutdown
        bt_since_last_trip = non_scaled_bank_trip_threshold - 1

        multipliers = (0.51, 1, 10, 100)

        for multiplier in multipliers:
            ot_last_two_weeks = ceil(bt_last_two_weeks * multiplier)
            result = proc.self_learning_detection(
                bt_last_two_weeks,
                ot_last_two_weeks,
                bt_since_last_trip,
                confidences_for_bank_of_2,
            )
            self.assertEqual(
                result,
                ShutdownDetectionResult(is_shutdown=False, confidence=StoppageState.OK),
            )


if __name__ == "__main__":
    unittest.main()
