#!/usr/bin/env python3
#  Python program to process altimeter and trip data to produce an elevation change per trip.

import logging
from datetime import datetime, timedelta

from sqlalchemy.sql import text

import anomaly_detector.constants as constants
import utilities.common_constants as common_constants
from utilities.db_utilities import engine


sql_time_since_last_trip = """
SELECT NOW() - end_time FROM trips ORDER BY id DESC LIMIT 1;
"""

sql_releveling_check = """
SELECT
  COUNT(z_data),
  SUM(ABS(z_data))
FROM accelerometer_data
WHERE
  ABS(z_data) > {0}
  AND ABS(z_data) < {1}
  AND timestamp > NOW() - INTERVAL '{2} seconds'
  AND timestamp < NOW() - INTERVAL '{3} seconds';
"""

sql_consecutive_relevelings = """
WITH last_not_releveling AS (
  SELECT COALESCE(MAX(occurred_at),'2018-01-01 00:00:00') as when_last  -- use minimum possible date if none
    FROM events
    WHERE event_type = '{0}'
      AND event_subtype = '{1}'
      AND confidence = 0
)
SELECT
  COUNT(e.*),
  COALESCE(MAX(x.when_last),'2018-01-01 00:00:00')   -- use MAX just as an aggregator to make this work, also still need coalesce here, too
FROM last_not_releveling x, events e
WHERE
  e.occurred_at > x.when_last
  AND e.event_type = '{0}'
  AND e.event_subtype = '{1}';
""".format(
    common_constants.EVENT_TYPE_ANOMALY, common_constants.EVENT_SUBTYPE_RELEVELING
)


logger = logging.getLogger(__name__)


class AccelerationAnomalyProcessor:
    def _get_quiet_time_seconds(self):
        with engine.connect() as con:
            tdelta = con.execute(sql_time_since_last_trip).fetchone()
            if tdelta:
                return tdelta[0].total_seconds()
        return None

    def check_for_anomalies(self):
        quiet_time_seconds = self._get_quiet_time_seconds()
        self._check_for_releveling(quiet_time_seconds)
        self._check_for_not_releveling(quiet_time_seconds)

    def _check_for_releveling(self, quiet_time_seconds):
        # There must be no trips for a certain amount of time before the window
        pre_window_guard_interval = constants.QUIET_TIME_GUARD_INTERVAL
        # This window of time is a quiet time, not near any trips.
        detection_window = constants.RELEVELING_WINDOW_SIZE
        # ...and no trips for a certain amount of time after the window
        post_window_guard_interval = constants.QUIET_TIME_GUARD_INTERVAL
        if (
            quiet_time_seconds
            and quiet_time_seconds
            > pre_window_guard_interval + detection_window + post_window_guard_interval
        ):
            outliers = self._get_outliers(constants.RELEVELING_WINDOW_SIZE)
            if outliers and outliers[0] > constants.RELEVELING_THRESHOLD:
                logger.debug(
                    "Possible releveling, count is {0}, raw sum is {1}".format(
                        outliers[0], outliers[1]
                    )
                )
                self._log_event(
                    common_constants.EVENT_SUBTYPE_RELEVELING,
                    datetime.now()
                    - timedelta(
                        seconds=constants.QUIET_TIME_GUARD_INTERVAL
                        + constants.RELEVELING_WINDOW_SIZE / 2
                    ),
                    min(80, outliers[1] / 2),
                )
            elif outliers:
                logger.debug(
                    "Outliers count is {0}, too few for an event".format(outliers[0])
                )
            else:
                logger.error("Nothing fetched when getting outliers, raising exception")
                raise Exception("Nothing fetched when getting releveling outliers")

    def _check_for_not_releveling(self, quiet_time_seconds):
        if (
            quiet_time_seconds
            and quiet_time_seconds
            > constants.LACK_OF_RELEVELING_WINDOW_SIZE
            + constants.QUIET_TIME_GUARD_INTERVAL * 2
        ):
            if self._should_we_check_for_not_releveling():
                logger.debug("Checking for NOT releveling")
                outliers = self._get_outliers(constants.LACK_OF_RELEVELING_WINDOW_SIZE)
                if outliers and outliers[0] == 0:
                    logger.debug("Detected a lack of releveling: problem was fixed")
                    self._log_event(
                        common_constants.EVENT_SUBTYPE_RELEVELING, datetime.now(), 0
                    )

    def _get_outliers(self, window_size):
        with engine.connect() as con:
            return con.execute(
                sql_releveling_check.format(
                    constants.RELEVELING_AMPLITUDE_MIN_THRESHOLD,
                    constants.RELEVELING_AMPLITUDE_MAX_THRESHOLD,
                    window_size + constants.QUIET_TIME_GUARD_INTERVAL,
                    constants.QUIET_TIME_GUARD_INTERVAL,
                )
            ).fetchone()

    def _should_we_check_for_not_releveling(self):
        query = text(
            "SELECT COUNT(*) FROM problems "
            "WHERE problem_type = :problem_type AND problem_subtype = :problem_subtype AND ended_at IS NULL"
        )
        with engine.connect() as con:
            return (
                con.execute(
                    query,
                    problem_type=common_constants.PROB_TYPE_ANOMALY,
                    problem_subtype=common_constants.PROB_SUBTYPE_RELEVELING,
                ).first()[0]
                > 0
            )

    def _log_event(self, event_subtype, occurred_at, confidence):
        logger.debug(
            "Creating event from {0} of type {1} and subtype {2} occurred at {3}".format(
                common_constants.EVENT_SOURCE_ANOMALY_DETECTOR,
                common_constants.EVENT_TYPE_ANOMALY,
                event_subtype,
                occurred_at,
            )
        )
        with engine.connect() as con:
            query_str = text(
                "INSERT INTO events (occurred_at, detected_at, source, event_type, event_subtype, confidence)"
                "     VALUES (:occurred, NOW(), :source, :et, :est, :conf)"
            )
            con.execute(
                query_str,
                occurred=occurred_at,
                source=common_constants.EVENT_SOURCE_ANOMALY_DETECTOR,
                et=common_constants.EVENT_TYPE_ANOMALY,
                est=event_subtype,
                conf=confidence,
            )
