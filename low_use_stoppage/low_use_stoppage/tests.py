import os
import unittest
from decimal import Decimal
from datetime import datetime, timedelta, time
from unittest.mock import Mock

import low_use_stoppage.constants as constants
from low_use_stoppage.processor import LowUseStoppageProcessor
from utilities import common_constants
from utilities.db_utilities import engine
from utilities.test_utilities import TestUtilities


class TestLowUsageStoppage(unittest.TestCase):
    testutil = TestUtilities()

    avg_trips_low = constants.AVG_TRIPS_HIGHER_CONFIDENCE_THRESHOLD - 1
    avg_trips_hi = constants.AVG_TRIPS_HIGHER_CONFIDENCE_THRESHOLD + 1
    max_trips_low = constants.MAX_TRIPS_LOWER_CONFIDENCE_THRESHOLD - 1
    max_trips_hi = constants.MAX_TRIPS_LOWER_CONFIDENCE_THRESHOLD + 1

    def _delete_data(self):
        self.testutil.delete_trips()
        with engine.connect() as con:
            con.execute("DELETE FROM trips")
            con.execute("DELETE FROM problems")
            con.execute("DELETE FROM events")
        for item in os.listdir(common_constants.STORAGE_FOLDER):
            if item.endswith(".pkl"):
                os.remove(os.path.join(common_constants.STORAGE_FOLDER, item))

    def _set_up_trips(self, weekly_tuple, no_trips_during_hour=-1):
        # weekly tuple (1, 2, 0, 5) means 1 trip last week, 2 trips the week before, none the week before that...
        # We need to populate three consecutive days in order to get one day of trips because we need to cover both
        # the real day (for midnight detection) and the virtual day (for the other algorithms).  It takes three
        # days of data to cover all possible combinations of real day and virtual day.
        start_time = self._get_real_midnight() - timedelta(days= 1) # Start with yesterday and cover to end of tomorrow

        week = 1
        for trips_this_week in weekly_tuple:
            for day in range(0, 3):
                for i in range(0, trips_this_week):
                    # Add trips in multiple hours
                    hour = i % 24
                    if no_trips_during_hour == hour:
                        # Avoid adding more trips in the hours right before and after j.
                        hour = (i+3) % 24
                    self.testutil.insert_trip(starts_at = start_time          # start of yesterday...
                                            + timedelta(days= day)        # march along the three consecutive days
                                            + timedelta(minutes = 5)      # plus some extra minutes...
                                            + timedelta(hours = hour)     # plus the next hour in sequence
                                            - timedelta(weeks= week))     # get 4 weeks of three consecutive days
            week += 1

    def _get_real_midnight(self):
        return datetime(datetime.now().year, datetime.now().month, datetime.now().day)

    def _add_event(self, processor, subtype, confidence, when):
        processor._log_event("testing",
                             common_constants.EVENT_TYPE_SHUTDOWN,
                             subtype,
                             confidence,
                             when,
                             when)

    def _get_last_event(self):
        with engine.connect() as con:
            return con.execute("SELECT occurred_at, detected_at, source, confidence FROM events "
                               "WHERE event_subtype = '{0}' ORDER BY id DESC LIMIT 1".format(common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN)).fetchone()

    def _get_low_use_instance(self, is_accel_running=True):
        mock = Mock()
        mock.return_value = is_accel_running
        bsp = LowUseStoppageProcessor()
        bsp._is_accelerometer_working = mock
        return bsp

    @classmethod
    def setUpClass(cls):
        print("Setting up for testing (NOTE: THESE ARE DESTRUCTIVE TESTS!!!)...")

    def setUp(self):
        self._delete_data()
        config = {"type": "elevator", common_constants.CONFIG_STOPPAGE_THRESHOLD: "DF"}
        self.testutil.set_config(config)

    def tearDown(self):
        self._delete_data()

#  These are for testing the code for setting up trips.  They're partially manual and only run once.
#    def test_set_up_trips_1(self):
#        self._set_up_trips( (24, 24, 24, 24))
        # Either use pdb to halt here or temporarily remove the tearDown() method, then inspect the DB trips table.

#    def test_set_up_trips_2(self):
#        self._set_up_trips( (1, 2, 0, 30), no_trips_during_hour=0)

#    def test_set_up_trips_3(self):
#        self._set_up_trips( (24, 24, 24, 24), no_trips_during_hour=1)

#    def test_set_up_trips_4(self):
#        self._set_up_trips( (24, 24, 24, 24), no_trips_during_hour=22)

#    def test_set_up_trips_5(self):
#        self._set_up_trips( (7, 25, 24, 3), no_trips_during_hour=23)

#    def test_setup_up_trips_6(self):
#        self._set_up_trips((15, 19, 24, 1), no_trips_during_hour=17)

    def test_basic_setup(self):
        p = self._get_low_use_instance()
        self.assertTrue(p is not None)

    def test_corrupted_storage_files(self):
        self._get_low_use_instance()
        self.testutil.create_empty_storage_files(common_constants.STORAGE_FOLDER)
        self._get_low_use_instance()       # Should not raise an exception
        self.assertTrue(True)

    def test_calculate_start_of_day(self):
        p = self._get_low_use_instance()
        self._set_up_trips( (24, 24, 24, 24), no_trips_during_hour=6)
        p._calculate_start_of_day()
        self.assertTrue( p.midnight == 6, "Calcuated start of day should have been 6, but was {0}".format(p.midnight))

    def test_start_of_day_after_now(self):
        p = self._get_low_use_instance()
        self._set_up_trips( (24, 24, 24, 24), no_trips_during_hour=23)
        p._calculate_start_of_day()
        self.assertTrue( p.midnight == 23, "Calcuated start of day should have been 23, but was {0}".format(p.midnight))

    def test_get_start_of_day(self):
        p = self._get_low_use_instance()
        self._set_up_trips((24, 24, 24, 24), no_trips_during_hour=11)
        t = p._get_start_of_today(datetime.now().replace(hour=10, minute=50, second=30))
        self.assertTrue(t.hour == 11, "start of day had the wrong hour, when now is before midnight, it is {0}".format(t))
        self.assertTrue(t.date() == (datetime.now() - timedelta(days=1)).date(), "start of day should have been yesterday since this is before virtual midnight. It is {0}".format(t))
        t2 = p._get_start_of_today(datetime.now().replace(hour=11, minute =1, second=10))
        self.assertTrue(t2.hour == 11, "start of day had the wrong hour, when not is after midnight.  It is {0}".format(t2))
        self.assertTrue(t2.date() == datetime.now().date(), "start of day should have been today. It is {0}".format(t2))

    def test_preexisting_condition(self):
        p = self._get_low_use_instance()
        p.midnight = 0
        p.last_state = 70
        self.assertTrue(p._is_preexisting_shutdown_condition() == False)
        self._add_event(p, common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN, 70, datetime.now() - timedelta(days=3))
        self.assertTrue(p._is_preexisting_shutdown_condition() == True)
        self._delete_data()
        self._add_event(p, common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN, 70, datetime.now() - timedelta(days=1))
        self.assertTrue(p._is_preexisting_shutdown_condition() == True)
        self._delete_data()
        p.last_state = 0
        self._add_event(p, common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN, 70, datetime.now() - timedelta(days=1))
        self.assertTrue(p._is_preexisting_shutdown_condition() == False)
        p.last_state = 75
        p.midnight = 23
        self._add_event(p, common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN, 70, datetime.now() - timedelta(days=1))
        self.assertTrue(p._is_preexisting_shutdown_condition() == True)
        p.last_state = 0
        self._add_event(p, common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN, 70, datetime.now() - timedelta(days=1))
        self.assertTrue(p._is_preexisting_shutdown_condition() == False)


    def test_get_no_trips_last_week(self):
        p = self._get_low_use_instance()
        self._set_up_trips((0, 24, 24, 24), no_trips_during_hour=8)
        start_of_today = p._get_start_of_today(datetime.now().replace(hour=16))
        with engine.connect() as con:
            trips = p._get_trips_last_week(con, start_of_today)
        self.assertTrue(trips == 0, "Should have had no trips last week, but we had {0}".format(trips))

    def test_multiple_trips_last_week(self):
        p = self._get_low_use_instance()
        self._set_up_trips((19,24,24,24), no_trips_during_hour=0)
        start_of_today = p._get_start_of_today(datetime.now().replace(hour=1))
        with engine.connect() as con:
            trips = p._get_trips_last_week(con, start_of_today)
        self.assertTrue(trips == 19, "Should have had 19 trips last week, but we had {0}".format(trips))

    def test_get_trips_today(self):
        p = self._get_low_use_instance()
        start_of_today = datetime.now() - timedelta(hours=23)
        with engine.connect() as con:
            x = p._get_trips_since_datetime(con, start_of_today)
            self.assertTrue(x == 0, "Reported {0} trips, should have been 0".format(x))
            self.testutil.insert_trip()
            x = p._get_trips_since_datetime(con, start_of_today)
            self.assertTrue(x == 1, "Reported {0} trips, should have been 1".format(x))
            self.testutil.insert_trip()
            x = p._get_trips_since_datetime(con, start_of_today)
            self.assertTrue(x == 2, "Reported {0} trips, should have been 2".format(x))

    def test_get_trip_data_1(self):
        p = self._get_low_use_instance()
        self._set_up_trips( (12, 0, 24, 6), no_trips_during_hour=3)
        start_of_today = p._get_start_of_today(datetime.now().replace(hour=6))
        with engine.connect() as con:
            trip_data = p._get_trip_data(con, start_of_today)
            self.assertTrue(trip_data[0] == 4, "Should be 4 weeks of trip data, was {0}".format(trip_data[0]))
            self.assertTrue(trip_data[1] == 1, "Should have 1 week without trips, was {0}".format(trip_data[1]))
            self.assertTrue(trip_data[2] == 0, "Should have no past shutdowns in prev 4 same weekdays, was {0}".format(trip_data[2]))

    def test_git_trip_data_2(self):
        p = self._get_low_use_instance()
        p.midnight = 0
        start_of_today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self.testutil.insert_trip(starts_at=start_of_today - timedelta(weeks=1) + timedelta(hours=2, minutes=30))
        self.testutil.insert_trip(starts_at=start_of_today - timedelta(weeks=2) + timedelta(hours=3, minutes=20))
        self.testutil.insert_trip(starts_at=start_of_today - timedelta(weeks=3) + timedelta(hours=4, minutes=40))
        self.testutil.insert_trip(starts_at=start_of_today - timedelta(weeks=4) + timedelta(hours=5, minutes=50))
        with engine.connect() as con:
            trip_data = p._get_trip_data(con, start_of_today)
            self.assertTrue(trip_data[0] == 4, "Should be 4 weeks of trip data, was {0}".format(trip_data[0]))
            self.assertTrue(trip_data[1] == 0, "Should have no weeks without trips, was {0}".format(trip_data[1]))
            self.assertTrue(trip_data[2] == 0, "Should have no past shutdowns, was {0}".format(trip_data[2]))
            self.assertTrue(abs(trip_data[3] - Decimal(1.0)) < Decimal(0.01), "Max trips should be about 1, was {0}".format(trip_data[3]))
            self.assertTrue(abs(trip_data[4] - Decimal(1.0)) < Decimal(0.01), "Avg trips should be about 1, was {0}".format(trip_data[4]))
            expected_latest_first_trip = time(5,50,0)
            self.assertTrue(trip_data[5] == expected_latest_first_trip,
                            "Latest first trip should be {0}, was {1}".format(expected_latest_first_trip, trip_data[5]))
            # We don't use earliest first trip for anything, so don't bother testing it.

    def test_events(self):
        p = self._get_low_use_instance()
        p.midnight = 0
        t = datetime.now() - timedelta(days=1)
        self._add_event(p, common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN, Decimal('72.34'), t)
        e = self._get_last_event()
        self.assertTrue(round(e['confidence'],2) == round(Decimal(72.34),2), "Event confidence should be 72.34 but was {0}".format(e['confidence']))
        self.assertTrue(e['occurred_at'] == t)

    def test_get_prev_combined_conf(self):
        p = self._get_low_use_instance()
        p.midnight = 2
        self._add_event(p, common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN, Decimal('78.90'), datetime.now() - timedelta(days=1))
        self._add_event(p, "foobar", Decimal('99.87'), datetime.now() - timedelta(hours=12))
        conf = p._get_previous_combined_confidence()
        self.assertTrue(round(Decimal(conf),2) == round(Decimal('78.90'),2), "Prev combined conf should be 78.90 but was {0}".format(conf))

    def test_get_prev_combined_conf_when_none(self):
        p = self._get_low_use_instance()
        p.midnight = 2
        # No events in the system.
        conf = p._get_previous_combined_confidence()
        self.assertTrue(conf==0, "Previous combined confidence should have been 0 with no events, "
                                 "but it was {0}".format(conf))

    def test_calculate_combined_confidence(self):
        p = self._get_low_use_instance()
        p.midnight = 7
        self.assertTrue(p._calculate_combined_confidence(existing_combined_confidence=10.00, new_confidence=50.00)
                                                == 50.00, "Combined confidence should be = new confidence")
        self.assertTrue(p._calculate_combined_confidence(10.00, 50.00) == 50.00,
                                                "Combined confidence should be = new confidence of 50")
        self.assertTrue(p._calculate_combined_confidence(Decimal('99.98'), Decimal('99.99')) == Decimal('99.99'),
                                                "Combined confidence should be = new confidence of 99.99")
        self.assertTrue(p._calculate_combined_confidence(70.00, 70.00) == Decimal('85.00'),
                                                "Combined confidence should be halfway to 100%")
        self.assertTrue(p._calculate_combined_confidence(Decimal('99.98'), Decimal('99.98')) == Decimal('99.99'),
                                                "Combined confidence should be halfway to 100%")
        self.assertTrue(p._calculate_combined_confidence(86.00, 65.00) == 86.00,
                        "New confidence should have been too low to impact resulting combined confidence")
        self.assertTrue(p._calculate_combined_confidence(90.00, 80.00) == Decimal('92.50'),
                        "New confidence should have moved combined confidence 1/4 way to 100%")
        self.assertTrue(p._calculate_combined_confidence(Decimal('99.96'), Decimal('80.00')) == Decimal('99.97'),
                        "New confidence should have moved combined confidence 1/4 way to 100%")

    def test_compute_confidence_basic(self):
        p = self._get_low_use_instance()
        # See _detect_shutdown() for the list of safe assumptions.
        # _compute_confidence() uses datetime.now() so make virtual midnight a truncated 15 hours ago for testing.
        start_of_today = datetime.now() - timedelta(hours=15)
        p.midnight = (start_of_today).hour

        # weeks, days_without_trips, days_with_shutdowns, max_trips, avg_trips, latest_first_trip, earliest_first_trip

        trip_data = (4, 0, 0, Decimal(self.max_trips_low), Decimal(self.avg_trips_low), time(16, 0), time(0, 0))
        conf = p._compute_confidence(trip_data, start_of_today)
        self.assertTrue( conf == 0, "First trip wasn't even overdue and we got a non-zero conf of {0}".format(conf))

        trip_data = (4, 0, 0, Decimal(self.max_trips_low), Decimal(self.avg_trips_low), time(12, 0), time(0, 0))
        conf = p._compute_confidence(trip_data, start_of_today)
        self.assertTrue(conf == 0, "First trip was only 3 hours overdue and we got a non-zero conf of {0}".format(conf))

        trip_data = (4, 0, 0, Decimal(self.max_trips_low), Decimal(self.avg_trips_low), time(11, 0), time(0, 0))
        conf = p._compute_confidence(trip_data, start_of_today)
        self.assertTrue(conf == 70, "First trip was 4 hours overdue and we got a value of {0}".format(conf))

        trip_data = (4, 0, 0, Decimal(self.max_trips_low), Decimal(self.avg_trips_hi), time(11, 0), time(0, 0))
        conf = p._compute_confidence(trip_data, start_of_today)
        self.assertTrue(conf == 76, "First trip was 4 hours overdue (+boost) and we got a value of {0}".format(conf))

        trip_data = (4, 0, 0, Decimal(self.max_trips_hi), Decimal(self.avg_trips_low), time(7, 0), time(0, 0))
        conf = p._compute_confidence(trip_data, start_of_today)
        self.assertTrue(conf == 85, "First trip was 8 hours overdue and we got a value of {0}".format(conf))

        trip_data = (4, 0, 0, Decimal(self.max_trips_low), Decimal(self.avg_trips_hi), time(7, 0), time(0, 0))
        conf = p._compute_confidence(trip_data, start_of_today)
        self.assertTrue(conf == 91, "First trip was 8 hours overdue (+boost) and we got a value of {0}".format(conf))

        trip_data = (4, 0, 0, Decimal(self.max_trips_hi), Decimal(self.avg_trips_low), time(2, 0), time(0, 0))
        conf = p._compute_confidence(trip_data, start_of_today)
        self.assertTrue(conf == 93, "First trip was 13 hours overdue and we got a value of {0}".format(conf))

        trip_data = (4, 0, 0, Decimal(self.max_trips_low), Decimal(self.avg_trips_hi), time(2, 0), time(0, 0))
        conf = p._compute_confidence(trip_data, start_of_today)
        self.assertTrue(conf == 96, "First trip was 13 hours overdue (+boost) and we got a value of {0}".format(conf))

    def test_compute_confidence_overrides(self):
        p = self._get_low_use_instance()
        # See _detect_shutdown() for the list of safe assumptions.
        # _compute_confidence() uses datetime.now() so make virtual midnight a truncated 17 hours ago for testing.
        start_of_today = datetime.now() - timedelta(hours=17)
        p.midnight = (start_of_today).hour

        # weeks, days_without_trips, days_with_shutdowns, max_trips, avg_trips, latest_first_trip, earliest_first_trip

        trip_data = (4, 2, 0, Decimal(20), Decimal(10), time(1, 0), time(0, 0))
        conf = p._compute_confidence(trip_data, start_of_today)
        self.assertTrue( conf == 0, "2 days without trips should override being overdue, wrong conf: {0}".format(conf))

        trip_data = (2, 0, 0, Decimal(2.90), Decimal(7), time(1, 0), time(0, 0))
        conf = p._compute_confidence(trip_data, start_of_today)
        self.assertTrue(conf == 0,
                        "Low avg trips + fewer weeks should override being overdue, wrong conf: {0}".format(conf))

        trip_data = (4, 2, 0, Decimal(2.90), Decimal(7), time(1, 0), time(0, 0))
        conf = p._compute_confidence(trip_data, start_of_today)
        self.assertTrue(conf == 0,
                        "Low avg trips + days without trips should override being overdue, wrong conf: {0}".format(conf))

        trip_data = (2, 0, 0, Decimal(20), Decimal(10), time(1, 0), time(0, 0))
        conf = p._compute_confidence(trip_data, start_of_today)
        self.assertTrue(conf == 0, "Only 2 weeks of data should override being overdue, wrong conf: {0}".format(conf))

    def test_multi_day_shutdown(self):
        p = self._get_low_use_instance()
        start_of_today = datetime.now() - timedelta(hours=23)
        p.midnight = (start_of_today).hour
        trip_data = (4, 0, 0, Decimal(self.max_trips_low), Decimal(self.avg_trips_low), time(19, 0), time(1, 0))
        p._detect_shutdown(trip_data, start_of_today)
        self.assertTrue(p.last_state == 70,
                        "4 hours overdue had confidence of {0}".format(p.last_state))


    def test_reboot_continuity(self):
        p = self._get_low_use_instance()
        start_of_today = datetime.now() - timedelta(hours=14)
        p.midnight = (start_of_today).hour
        trip_data = (4, 1, 0, Decimal(self.max_trips_low), Decimal(self.avg_trips_low), time(10, 0), time(1, 0))
        p._detect_shutdown(trip_data, start_of_today)
        self.assertTrue(p.last_state == 70,
                        "4 hours overdue had a confidence of {0}".format(p.last_state))
        del(p)
        p = self._get_low_use_instance()
        self.assertTrue(p.last_state == 70, "state was not persistent after re-creating the processor object")
        start_of_today = datetime.now() - timedelta(hours=17)
        p.midnight = (start_of_today).hour
        trip_data = (4, 0, 0, Decimal(self.max_trips_low), Decimal(self.avg_trips_hi), time(1, 0), time(1, 0))
        p._detect_shutdown(trip_data, start_of_today)
        self.assertTrue(p.last_state == 96,     # includes a boost
                        "13+ hours overdue had a confidence of {0}".format(p.last_state))

    def test_detect_shutdown(self):
        p = self._get_low_use_instance()
        start_of_today = datetime.now() - timedelta(hours=17)
        p.midnight = (start_of_today).hour

        trip_data = (4, 0, 0, Decimal(20), Decimal(10), time(13, 0), time(0, 0))
        p._detect_shutdown(trip_data, start_of_today)
        self.assertTrue(p.last_state == 70, "4 hours overdue and got a confidence of {0}".format(p.last_state))
        e = self._get_last_event()
        # occurred_at, detected_at, source, confidence
        last_event_datetime = e[0]
        self.assertTrue((e[0] - datetime.now()).total_seconds() < 2, "Wrong event time, {0}".format(e[0]) )
        self.assertTrue(e[3] == 70.00, "Confidence was {0}".format(e[3]))

        trip_data = (4, 0, 0, Decimal(20), Decimal(10), time(12, 0), time(0, 0))
        p._detect_shutdown(trip_data, start_of_today)
        self.assertTrue(p.last_state == 70, "5 hours overdue should not change confidence, was {0}".format(p.last_state))
        e = self._get_last_event()
        self.assertTrue(last_event_datetime == e[0], "Another event got generated when confidence stayed the same")

    def test_does_not_blow_up_on_long_shutdown(self):
        """
        If we have a week-long problem, which can happen,
        there'll be no latest_first_trip or earliest_first_trip.
        We should just avoid changing anything in this state, and not
        blow up.
        """
        p = self._get_low_use_instance()
        start_of_today = datetime.now() - timedelta(hours=17)
        p.midnight = (start_of_today).hour

        trip_data = (4, 0, 4, Decimal(20), Decimal(10), None, None)
        p._detect_shutdown(trip_data, start_of_today)
        self.assertTrue(p.last_state == 0, "No latest/earliest trip should have zero confidence, was {0}".format(p.last_state))
        self.assertIsNone(self._get_last_event())

    def test_infrequent_and_frequent_run(self):
        curr_hour = datetime.now().hour
        midnight_hour = curr_hour - 9
        if midnight_hour < 0:
            midnight_hour += 24
        self._set_up_trips((28, 30, 29, 33), no_trips_during_hour=midnight_hour)
        p = self._get_low_use_instance()
        p.frequent_run()
        self.assertTrue(p.last_state == 0)
        p.infrequent_run()
        self.assertTrue(p.last_state >= 75)
        p.frequent_run()
        self.assertTrue(p.last_state >= 75, "frequent_run() falsely detected the end of a shutdown")
        p.infrequent_run()
        self.assertTrue(p.last_state >= 75, "infrequent_run() should have ignored the case where the confidence was unchanged")
        self.testutil.insert_trip(starts_at= datetime.now() - timedelta(hours=4))
        p.infrequent_run()
        self.assertTrue(p.last_state >= 75, "Infrequent_run() should do nothing if a trip happened on virtual today")
        p.frequent_run()
        self.assertTrue(p.last_state == 0)
        prev_conf = p._get_previous_combined_confidence()
        self.assertTrue(prev_conf == 0, "The end of shutdown event never got created")
        p.infrequent_run()
        p.frequent_run()
        p.infrequent_run()
        p.frequent_run()
        self.assertTrue(p.last_state == 0, "Some kind of weird insanity happened")

    def test_infrequent_run_various_day_starts(self):
        curr_hour = (datetime.now() + timedelta(minutes=30)).hour
        print("---- Current hour is {0}".format(curr_hour))
        for h in range (0,24):
            self._set_up_trips((36, 25, 24, 36), no_trips_during_hour=h)
            p = self._get_low_use_instance()
            p.infrequent_run()
            if h <= curr_hour:
                hours_since_midnight = curr_hour - h
            else:
                hours_since_midnight = 24 + curr_hour - h
            hours_overdue = hours_since_midnight - 1    # Latest first trip happens one hour after midnight.
            if hours_overdue > 16:
                expected_confidence = 99
            elif hours_overdue > 12:
                expected_confidence = 93
            elif hours_overdue > 7:
                expected_confidence = 85
            elif hours_overdue > 3:
                expected_confidence = 70
            else:
                expected_confidence = 0
            print("Hours since midnight: {0}, expecting {1}, got {2}".format(hours_since_midnight, expected_confidence, p.last_state))
            print("Midnight hour= {0}, Start of today= {1}".format(p.midnight, p._get_start_of_today(datetime.now())))
            self.assertTrue(p.last_state == expected_confidence,
                            "Expected confidence {0}, but got {1}".format(expected_confidence, p.last_state))
            del(p)
            self._delete_data()

    def test_accelerometer_detection(self):
        curr_hour = datetime.now().hour
        midnight_hour = curr_hour - 9
        if midnight_hour < 0:
            midnight_hour += 24
        self._set_up_trips((28, 30, 29, 33), no_trips_during_hour=midnight_hour)
        p = self._get_low_use_instance(is_accel_running=False)
        p.frequent_run()
        self.assertEqual(p.last_state, 0)
        p.infrequent_run()
        self.assertEqual(p.last_state, 0, "Low use shutdown processor didn't stop detecting shutdowns when accelerometer stopped")

if __name__ == "__main__":
    unittest.main()
