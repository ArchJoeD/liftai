#! /usr/bin/python3
import logging
from datetime import datetime

import standalone_stoppage.constants as constants
from utilities.stoppage_processor import StoppageState, StoppageProcessor, common_constants

sql_statement = """
WITH RECURSIVE intervals_all AS -- Get the intervals (weeks) (could be overlapped)
(
SELECT e.end_time - (now() - (SELECT coalesce(max(start_time) + INTERVAL '1 second', to_timestamp(0)) FROM trips)) as start_time,
       e.end_time
FROM (
SELECT generate_series(now() - INTERVAL '7 days' * (select (EXTRACT(days FROM now()-min(start_time))/7)::int from trips),
                       now(), INTERVAL '7 days')::timestamp as end_time
) as e
WHERE e.end_time - (now() - (SELECT coalesce(max(start_time) + INTERVAL '1 second', to_timestamp(0)) FROM trips)) >
      (SELECT coalesce(min(start_time), to_timestamp(0)) from trips)
)
, intervals(start_time, end_time) AS -- Remove overlapping intervals
(
    (SELECT * FROM intervals_all order by end_time desc limit 1)
    UNION
    (SELECT i.* FROM intervals_all i, intervals i2 WHERE i.end_time<i2.start_time ORDER BY i.end_time desc limit 1)
)

SELECT count(*) n, coalesce(min(trips), 0) prev_trips
FROM (
    SELECT i.start_time, i.end_time, count(t.start_time) trips -- Count the number of trips on each interval
    FROM intervals i LEFT JOIN trips t ON (t.start_time>=i.start_time and t.start_time<i.end_time)
    WHERE NOT EXISTS ( -- Remove intervals that overlapps with stoppages periods
        SELECT 1 FROM problems p where i.end_time>p.started_at and i.start_time<p.ended_at AND p.confidence >= 99
    )
    AND i.start_time<(SELECT coalesce(max(start_time), to_timestamp(0)) FROM trips)
    GROUP BY i.start_time, i.end_time
    ORDER by i.start_time DESC LIMIT {0}
) t;
"""


logger = logging.getLogger(__name__)


# Big default confidence levels
class StandaloneStoppageProcessor(StoppageProcessor):
    name = 'standalone_stoppage'
    confidence_values = {'90': 50, '95': 80, '99': 140}

    def __init__(self):
        super().__init__(logger)

    def run(self):
        with self.engine.connect() as con:
            if self._is_accelerometer_working(con):
                r = con.execute(sql_statement.format(constants.MAX_SAMPLES)).fetchone()

                if r is None:
                    logger.debug("No prior weeks' data, not detecting shutdowns.")
                    return
                if r['n'] < constants.MIN_SAMPLES:
                    logger.debug("Only {0} prior weeks' data, we need {1}, not detecting shutdowns"\
                                  .format(r['n'], constants.MIN_SAMPLES))
                    return

                # If we're leaving the OK state, save the last trip that happened.
                if r['prev_trips'] >= self.confidence_values['90'] and self.last_state == StoppageState.OK:
                    last_trip = con.execute("SELECT t.end_time FROM trips AS t ORDER BY t.end_time DESC LIMIT 1").fetchone()
                    if last_trip is not None:
                        self._set_last_trip(last_trip['end_time'])
                    else:
                        logger.error("We detected a shutdown and there are no previous trips in the database")
                        self._set_last_trip(datetime.now())

                if self.last_state != StoppageState.OK and self._is_trip_happening():
                    self._update_state(StoppageState.OK)
                    self._log_resumed_event(common_constants.EVENT_SUBTYPE_STANDALONE)
                    logger.info("A trip happened, so the state is changing back to OK")

                elif r['prev_trips'] >= self.confidence_values['99'] and self.last_state < StoppageState.STOPPED_C99:
                    probability = 99
                    self._update_state(StoppageState.STOPPED_C99)
                    self._log_stoppage_event(probability, common_constants.EVENT_SUBTYPE_STANDALONE)
                    logger.info("99% shutdown probability (standalone), {0} weeks data".format(r['n']))

                elif r['prev_trips'] >= self.confidence_values['95'] and self.last_state < StoppageState.STOPPED_C95:
                    probability = 95
                    self._update_state(StoppageState.STOPPED_C95)
                    self._log_stoppage_event(probability, common_constants.EVENT_SUBTYPE_STANDALONE)
                    logger.info("95% shutdown probability (standalone), {0} weeks data".format(r['n']))

                elif r['prev_trips'] >= self.confidence_values['90'] and self.last_state < StoppageState.STOPPED_C90:
                    probability = 90
                    self._update_state(StoppageState.STOPPED_C90)
                    self._log_stoppage_event(probability, common_constants.EVENT_SUBTYPE_STANDALONE)
                    logger.info("90% shutdown probability (standalone), {0} weeks data".format(r['n']))
