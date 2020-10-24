#! /usr/bin/python3

import logging
from datetime import datetime, timedelta, date
from decimal import Decimal

import low_use_stoppage.constants as constants
from utilities.stoppage_processor import StoppageState, StoppageProcessor, common_constants

sql_trips_dow = """
WITH day_numbers AS (
  -- We left-shift all the times so we can deal with dates and not virtual days that overlap multiple days
  SELECT generate_series( '{0}'::DATE - INTERVAL '4 WEEKS', '{0}'::DATE - INTERVAL '1 WEEK', '1 WEEK') as d
),
trip_data AS (
  SELECT
    dn.d AS day,
    t.start_time - INTERVAL '{1} HOURS' AS trip_time,
    p.id AS problem
  FROM day_numbers dn
  LEFT OUTER JOIN trips t on DATE(t.start_time - INTERVAL '{1} HOURS') = dn.d
  LEFT OUTER JOIN problems p on DATE(p.started_at - INTERVAL '{1} HOURS') <= dn.d AND (DATE(p.ended_at - INTERVAL '{1} HOURS') >= dn.d OR p.ended_at IS NULL)
),
single_days AS (
  SELECT
    day,
    COUNT(trip_time) AS trips,
    CASE
      WHEN COUNT(trip_time) = 0 THEN 1
      ELSE 0
    END AS no_trip_flag,
    CASE
      WHEN COUNT(problem) > 0 THEN 1
      ELSE 0
    END AS problem_flag,
    CASE
      -- first trip of the day is only valid with no shutdowns during the day
      WHEN COUNT(problem) > 0 THEN NULL
      ELSE MIN(trip_time::time)   -- Note that trip time is offset from virtual midnight
    END AS first_trip
  FROM trip_data GROUP BY day ORDER BY day ASC
)
SELECT
  COUNT(*) AS weeks,
  SUM(no_trip_flag) AS days_without_trips,
  SUM(problem_flag) AS days_with_shutdowns,
  ROUND(MAX(trips),2) AS max_trips,
  ROUND(AVG(trips),2) AS avg_trips,
  MAX(first_trip) AS latest_first_trip,
  MIN(first_trip) AS earliest_first_trip
FROM single_days;
"""

sql_trips_per_hour = """
WITH hours AS
(
  SELECT
    generate_series(0,23) AS hour
),
trip_count AS
(
  SELECT
    extract( hour FROM start_time) AS hour,
    1 AS trip
  FROM trips WHERE start_time > NOW() - INTERVAL '28 DAYS'
  UNION ALL
  SELECT
    hour,
    0 AS trip
  FROM hours
)
SELECT
  hour,
  SUM(trip) as trips
FROM trip_count
GROUP BY hour
ORDER BY hour ASC;
"""

sql_trips_week_ago = """
SELECT COUNT(*) FROM trips
  WHERE start_time > '{0}'::DATE - INTERVAL '7 DAYS'
  AND start_time < '{0}'::DATE - INTERVAL '6 DAYS';
"""

sql_total_trips_today = """
-- Use > and not >= so we can use this for trips after a shutdown.
SELECT COUNT(*) FROM trips WHERE start_time > '{0}';
"""

sql_get_low_use_shutdown_status = """
SELECT confidence
FROM events
WHERE event_type = '{0}' AND event_subtype = '{1}'
ORDER BY id DESC LIMIT 1;
"""

logger = logging.getLogger(__name__)


class LowUseStoppageProcessor(StoppageProcessor):
    name = 'low_use_stoppage'
    parms_table_name = 'low_use_stoppage_parms'
    midnight = None

    def __init__(self):
        super().__init__(logger)

    def _calculate_start_of_day(self):
        with self.engine.connect() as con:
            rows = con.execute(sql_trips_per_hour).fetchall()
            # If we don't have at least a day of data yet, just use a default for start of day
            if len(rows) < 24:
                return constants.DEFAULT_START_OF_DAY

            min_trips = None
            midnight_hours = None
            for i in range (0, 24):
                prev_hour, prev_trips = rows[(i-1)%24]
                hour, trips = rows[i]
                next_hour, next_trips = rows[(i+1)%24]
                if not min_trips or sum((prev_trips, trips, next_trips)) <= sum(min_trips):
                    midnight_hours = (prev_hour, hour, next_hour)
                    min_trips = (prev_trips, trips, next_trips)
            zipped = list(zip(midnight_hours, min_trips))
            self.midnight = int(min(zipped, key = lambda i: i[1])[0])
            logger.debug("calcuated midnight as {0}".format(self.midnight))

    def _get_start_of_today(self, now):
        if self.midnight is None:
            # We don't need to save the calculated 'midnight', we can recompute it whenever we need to.
            # We should regenerate it at least once per week or so.
            self._calculate_start_of_day()

        now_hour = now.hour
        t = now
        if now_hour < self.midnight:
            # If it's not yet the midnight hour, hours_since_virtual_midnight < hours_since_latest_first_tripback up a day
            t = t - timedelta(days=1)
        return t.replace(hour=self.midnight, minute=0, second=0, microsecond=0)

    def _get_trip_data(self, connection, start_of_today):
        # This was separated from detecting shutdowns to make testing easier.
        return connection.execute(sql_trips_dow.format(start_of_today, self.midnight)).fetchone()

    def _get_trips_since_datetime(self, connection, beginning):
        trips_today = connection.execute(sql_total_trips_today.format(beginning)).fetchone()
        if not trips_today:
            return 0
        else:
            return trips_today[0]

    def _get_trips_last_week(self, connection, start_of_today):
        trips_last_week = connection.execute(sql_trips_week_ago.format(start_of_today)).fetchone()
        if not trips_last_week:
            return 0
        else:
            return trips_last_week[0]

    def _get_previous_combined_confidence(self):
        with self.engine.connect() as con:
            event_data = con.execute(sql_get_low_use_shutdown_status.format(common_constants.EVENT_TYPE_SHUTDOWN,
                                                    common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN)).fetchone()
            if event_data is not None:
                return event_data['confidence']
            else:
                return Decimal(0)

    def _is_preexisting_shutdown_condition(self):
        # Is there an existing shutdown condition from yesterday or earlier days?
        if self.last_state == StoppageState.OK:
            return False
        virtual_midnight = datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=self.midnight)
        if virtual_midnight > datetime.now():
            virtual_midnight = virtual_midnight - timedelta(days=1)
        # Check if the most recent low use event (if any) from before today had a non-zero confidence.
        with self.engine.connect() as con:
            result = con.execute("SELECT detected_at, confidence FROM events WHERE event_subtype='{0}' AND detected_at < '{1}' ORDER BY id DESC LIMIT 1"
                            .format(common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN,str(virtual_midnight))).fetchone()
        if result and result[1] > 0:
            # This is a shutdown situation from before today, so don't do any processing other than looking for a trip.
            logger.debug("...pre-existing shutdown detected at {0} with confidence {1}".format(result['detected_at'], result['confidence']))
            return True
        # This is a current shutdown situation ongoing today.
        return False

    def _calculate_combined_confidence(self, existing_combined_confidence, new_confidence):
        # This differs from the elisha combined formula, but it's fine due to the limited range here.
        r = None
        if new_confidence > existing_combined_confidence:
            # This is the normal escalation sequence.
            r = new_confidence
        elif new_confidence == existing_combined_confidence:
            # bump the existing confidence halfway to 100%
            r = existing_combined_confidence + (100 - existing_combined_confidence)/2
        elif new_confidence >= 80:
            # bump the existing confidence just a little towards 100%
            r = existing_combined_confidence + (100 - existing_combined_confidence)/4
        else:
            # Only bump up an existing combined confidence if the new confidence > min threshold
            r = existing_combined_confidence
        return round(Decimal(r),2)

    def _compute_confidence(self, trip_data, start_of_today):
        # Convenience definitions (we get a tuple instead of a dictionary, unfortunately):
        weeks_index = 0
        days_without_trips_index = 1
        max_trips_index = 3
        avg_trips_index = 4
        latest_first_trip_index = 5
        weeks = trip_data[weeks_index]
        # These are not consecutive days, they're the same weekday in previous weeks (e.g. last 4 Tuesdays)
        days_without_trips = trip_data[days_without_trips_index]
        max_trips = trip_data[max_trips_index]
        avg_trips = trip_data[avg_trips_index]
        latest_first_trip = trip_data[latest_first_trip_index]  # This is already offset from virt midnight by the SQL
        hours_since_virtual_midnight = ((datetime.now() - start_of_today).total_seconds() + 30*60) // (60*60) % 24
        if latest_first_trip:
            hour_of_latest_first_trip = (latest_first_trip.hour*60 + latest_first_trip.minute + 30) // 60
        else:
            # If we're missing all the data we need, then use a default that won't trigger a shutdown warning.
            hour_of_latest_first_trip = hours_since_virtual_midnight
        hours_overdue = hours_since_virtual_midnight - hour_of_latest_first_trip

        confidence_boost = 0
        if avg_trips > constants.AVG_TRIPS_HIGHER_CONFIDENCE_THRESHOLD \
                and max_trips < constants.MAX_TRIPS_LOWER_CONFIDENCE_THRESHOLD:
            confidence_boost = 6

        r = Decimal(0)
        if days_without_trips >= 2:
            logger.debug("2+ prior weeks without trips, so we can't detect a shutdown now")
            r = Decimal(0)
        elif avg_trips < Decimal(3) and (days_without_trips > 0 or weeks < 4):
            logger.debug("Not enough avg trips in the past (and other factors), so we can't detect a shutdown now")
            r = Decimal(0)
        elif weeks <= 2:
            logger.debug("Not enough data, so we can't detect a shutdown now")
            r = Decimal(0)
        elif hours_overdue <= 3:
            logger.debug("Still too early in the day to detect shutdowns: {0} hrs to go".format(3 - hours_overdue))
            r = Decimal(0)
        elif hours_overdue <= 7:
            logger.debug("4-7 hours overdue, make this a low confidence")
            r = 70 + confidence_boost
        elif hours_overdue <= 12:
            logger.debug("8-12 hours overdue, bump up the confidence")
            r = 85 + confidence_boost
        elif hours_overdue <= 16:
            logger.debug("13-16 hours overdue, high confidence")
            r = 93 + confidence_boost/2
        else:
            logger.debug("17+ hours overdue, max confidence")
            r = 99
        return round(Decimal(r),2)

    def _log_stoppage_event(self, probability, subtype, detected_at=datetime.now(), occurred_at=None):
        # Similar to the same method in the common stoppage_processor,
        # but we don't want to set occurred_at to our last trip time for
        # this particular stoppage processor.
        if occurred_at is None:
            occurred_at = detected_at
            logger.debug("Overriding _log_stoppage_event: No occurred_at time, so we're using "
                              "detected_at time of {0}".format(detected_at))
        else:
            logger.debug("Overriding _log_stoppage_event: occurred_at {0}, detected_at {1}".format(occurred_at,detected_at))
        return self._log_event(self.name,
                        common_constants.EVENT_TYPE_SHUTDOWN,
                        subtype,
                        probability,
                        occurred_at,
                        detected_at)

    def _detect_shutdown(self, trip_data, start_of_today):
        # We already know...
        #    there was at least one trip last week on this day.
        #    there were no trips so far since virtual midnight.
        confidence = self._compute_confidence(trip_data, start_of_today)

        if confidence > 0:
            # At this point we have a possible shutdown
            if self.last_state == StoppageState.OK:
                # This is a new shutdown.
                self._update_current_stopped_timestamp(start_of_today)  # Use real-time, virt midnight can shift around
                logger.debug("First detection of a possible shutdown, confidence = {0}, "
                                  "occurred_at start of today = {1}".format(confidence, start_of_today))
                self._log_stoppage_event(confidence, common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN,
                                         occurred_at=start_of_today)
                # The shutdown basically started at the beginning of today, not at the last trip.
                self._set_last_trip(start_of_today)

            else:
                # If the confidence level hasn't changed from the last time we ran, do nothing.
                if confidence == self.last_state:
                    logger.debug("Confidence number is still {0}, doing nothing, start_of_today is {1}"\
                                      .format(confidence, start_of_today))
                else:
                    # The confidence can drop lower if this is a new day, so any change triggers a bump up.
                    prev_combined_confidence = self._get_previous_combined_confidence()
                    new_combined_confidence = self._calculate_combined_confidence(prev_combined_confidence, confidence)
                    if new_combined_confidence > prev_combined_confidence:
                        logger.debug("Existing shutdown where new confidence of {0} > prev confid of {1}, "
                                          "bumping up to {2}".format(confidence, prev_combined_confidence, new_combined_confidence))
                        self._log_stoppage_event(new_combined_confidence, common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN, occurred_at=start_of_today)
                    else:
                        logger.debug("Existing shutdown where new confidence of {0} results in combined confid of {1}, "
                                          "not changing from {2}".format(confidence, new_combined_confidence, prev_combined_confidence))
            self._update_state(confidence)
        else:
            logger.debug("Computed confidence is 0, so do nothing... start of today is {0}".format(start_of_today))

    def run(self):
        self.infrequent_run()        # This is not used but required as abstract class in stoppage_processor.py

    def frequent_run(self):
        if self.last_state != StoppageState.OK:
            if self._is_trip_happening():
                # Set last trip so that detected_at is correct.
                self._update_state(StoppageState.OK)
                self._set_last_trip(None)
                self._log_resumed_event(common_constants.EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN)
                logger.info("End of shutdown due to a trip")
                return

    def infrequent_run(self):
        start_of_today = self._get_start_of_today(datetime.now())
        with self.engine.connect() as con:
            if self._is_accelerometer_working(con):
                total_trips_today = self._get_trips_since_datetime(con, start_of_today)
                if total_trips_today > 0:
                    logger.debug("Already had trips today, so all done with infrequent_run()")
                    # We only catch shutdowns from the beginning of the day
                    # Let the frequent_run() method catch the end of a shutdown.
                    return
                trips_last_week = self._get_trips_last_week(con, start_of_today)
                if trips_last_week == 0:
                    logger.debug("No trips last week on this day, so all done with infrequent_run()")
                    # If we didn't have any trips a week ago during this day, then don't declare a shutdown today.
                    # Don't change state to OK because it may need to bridge through a non-active day.
                    return
                if self._is_preexisting_shutdown_condition():
                    logger.debug("There's a pre-existing shutdown condition. This code only handles 1 day of shutdown")
                    return

                trip_data = self._get_trip_data(con, start_of_today)
                self._detect_shutdown(trip_data, start_of_today)
