#! /usr/bin/python3
import decimal
import logging
from collections import namedtuple

from sqlalchemy.exc import ProgrammingError
from sqlalchemy.sql import text

from bank_stoppage import constants
from utilities.stoppage_processor import StoppageState, StoppageProcessor, common_constants

last_trip_time_sql = "SELECT max(start_time) FROM trips"
last_trip_time_plus_delay_sql = "SELECT ({last_trip_time_sql}) + INTERVAL ':delay minutes'".format(last_trip_time_sql=last_trip_time_sql)
two_weeks_ago_sql = "NOW() - INTERVAL '2 WEEKS'"

trip_ratio_sql = """
WITH trip_info AS (SELECT
  (SELECT coalesce(SUM(bank_trips), 0)
     FROM bank_trips
    WHERE timestamp > ({last_trip_time_plus_delay_sql})) AS bank_trips_since_last_trip,
  (SELECT COALESCE(SUM(bank_trips), 0)
     FROM bank_trips
    WHERE timestamp > {two_weeks_ago_sql} AND timestamp < ({last_trip_time_sql})) AS bank_trips_2weeks_count,
  (SELECT COALESCE(MAX(bank_elevators), 8)
     FROM bank_trips
    WHERE timestamp > ({last_trip_time_plus_delay_sql})) AS bank_elevators_count,
  (SELECT COUNT(*)
     FROM trips
    WHERE start_time > {two_weeks_ago_sql}) AS our_trips_2weeks_count
)
  SELECT bank_trips_since_last_trip,
         bank_trips_2weeks_count,
         bank_elevators_count,
         our_trips_2weeks_count,
         t.end_time
    FROM trip_info, trips AS t
ORDER BY t.end_time DESC LIMIT 1
""".format(
    last_trip_time_sql=last_trip_time_sql,
    two_weeks_ago_sql=two_weeks_ago_sql,
    last_trip_time_plus_delay_sql=last_trip_time_plus_delay_sql,
)

logger = logging.getLogger(__name__)
ShutdownDetectionResult = namedtuple('ShutdownDetectionResult', ['is_shutdown', 'confidence'])


class BankStoppageProcessor(StoppageProcessor):
    name = 'bank_stoppage'
    parms_table_name = 'bank_stoppage_parms'

    def __init__(self):
        super().__init__(logger)
        self.confidences = constants.CONFIDENCE_DEFAULTS

    def _get_confidence_thresholds_from_config(self):
        ctable = constants.CONFIDENCE_TABLE[self._get_threshold_config().upper()]

        return {
            key: {
                '90': value[0],
                '95': value[1],
                '99': value[2],
            }
            for key, value in ctable.items()
        }


    def _get_confidences_for_elevators(self, num_elevators):
        confidences = self._get_confidence_thresholds_from_config()

        return confidences[num_elevators] if num_elevators in confidences else constants.CONFIDENCE_DEFAULTS

    def default_detection(self, bank_trips_since_last_trip, confidences):
        shutdown_result = ShutdownDetectionResult(is_shutdown=False, confidence=None)

        if bank_trips_since_last_trip >= confidences['99'] and self.last_state < StoppageState.STOPPED_C99:
            # 99% confident that we've hit a stoppage.
            shutdown_result = ShutdownDetectionResult(is_shutdown=True, confidence=StoppageState.STOPPED_C99)

        elif bank_trips_since_last_trip >= confidences['95'] and self.last_state < StoppageState.STOPPED_C95:
            # 95% confident that we've hit a stoppage.
            shutdown_result = ShutdownDetectionResult(is_shutdown=True, confidence=StoppageState.STOPPED_C95)

        elif bank_trips_since_last_trip >= confidences['90'] and self.last_state < StoppageState.STOPPED_C90:
            # 90% confident that we've hit a stoppage.
            shutdown_result = ShutdownDetectionResult(is_shutdown=True, confidence=StoppageState.STOPPED_C90)

        if shutdown_result.is_shutdown:
            logger.info("{}% shutdown probability, bank trips is now {}".format(shutdown_result.confidence, bank_trips_since_last_trip))

        return shutdown_result

    def self_learning_detection(self, bt_last_two_weeks, ot_last_two_weeks, bt_since_last_trip, confidences_for_bank_of_2):
        no_bank_trips = bt_last_two_weeks <= 30
        no_our_trips = ot_last_two_weeks <= 10

        if no_bank_trips or no_our_trips:
            # Don't do anything if we've had some really low about of trips in the bank, and
            # for us.
            logger.info(
                "Not enough trips to run detection. ot_last_two_weeks=%s, bt_last_two_week=%s",
                ot_last_two_weeks,
                bt_last_two_weeks,
            )
            return

        historic_trip_ratio = decimal.Decimal(ot_last_two_weeks) / decimal.Decimal(bt_last_two_weeks)
        if historic_trip_ratio <= 0:
            # Avoid ever dividing by zero. This shouldn't happen ever, but it's better to be safe.
            logger.critical(
                "Calculated a historic_trip_ratio of %s which should never happen. ot_last_two_weeks=%s, bt_last_two_week=%s",
                historic_trip_ratio,
                ot_last_two_weeks,
                bt_last_two_weeks,
            )
            return
        elif historic_trip_ratio > 0.5:
            if historic_trip_ratio > 1:
                logger.warning(
                    "Calculated a historic_trip_ratio greater than 1 which should never happen. historic_trip_ratio=%s, ot_last_two_weeks=%s, bt_last_two_week=%s",
                    historic_trip_ratio,
                    ot_last_two_weeks,
                    bt_last_two_weeks,
                )
            historic_trip_ratio = 0.5

        shutdown_result = ShutdownDetectionResult(is_shutdown=False, confidence=0)

        # We start with the bank-of-two values, then convert that from 2 to the historic trip ratio.  To see this,
        # imagine a historic trip ratio of 0.5 which gets the same confidences as the default static detection.
        scaled_99_confidence = confidences_for_bank_of_2['99'] / (2 * historic_trip_ratio)
        scaled_95_confidence = confidences_for_bank_of_2['95'] / (2 * historic_trip_ratio)
        scaled_90_confidence = confidences_for_bank_of_2['90'] / (2 * historic_trip_ratio)

        if bt_since_last_trip >= scaled_99_confidence and self.last_state < StoppageState.STOPPED_C99:
            # 99% confident that we've hit a stoppage.
            shutdown_result = ShutdownDetectionResult(is_shutdown=True, confidence=StoppageState.STOPPED_C99)
            scaled_conf = scaled_99_confidence
        elif bt_since_last_trip >= scaled_95_confidence and self.last_state < StoppageState.STOPPED_C95:
            # 95% confident that we've hit a stoppage.
            shutdown_result = ShutdownDetectionResult(is_shutdown=True, confidence=StoppageState.STOPPED_C95)
            scaled_conf = scaled_95_confidence
        elif bt_since_last_trip >= scaled_90_confidence and self.last_state < StoppageState.STOPPED_C90:
            # 90% confident that we've hit a stoppage.
            shutdown_result = ShutdownDetectionResult(is_shutdown=True, confidence=StoppageState.STOPPED_C90)
            scaled_conf = scaled_90_confidence

        if shutdown_result.is_shutdown:
            logger.info("SL status: Historic trip ratio of {:.3f} vs. "
                             "confidences of {}".format(historic_trip_ratio, confidences_for_bank_of_2))
            logger.debug("SL Status: Scaled confidences of [{:.2f}, {:.2f}, {:.2f}]".format(
                scaled_90_confidence,
                scaled_95_confidence,
                scaled_99_confidence))
            logger.info("SL Status: Bank trips of {} >= scaled "
                    "confidence of {:.3f} triggered status of {}.\n".format(
                                 bt_since_last_trip,
                                 scaled_conf,
                                 shutdown_result.confidence))
            logger.info("{}%% shutdown probability from self-learning algo, bank trips is now {}".format(shutdown_result.confidence, bt_last_two_weeks))

        return shutdown_result

    def get_trip_ratio_data(self, con):
        query_str = text(trip_ratio_sql)
        rs = con.execute(query_str, delay=constants.DELAY_MINUTES)
        r = rs.fetchone()

        return (r['bank_trips_since_last_trip'],
                r['bank_trips_2weeks_count'],
                r['bank_elevators_count'],
                r['our_trips_2weeks_count'],
                r['end_time']) if r else None

    def run(self):
        with self.engine.connect() as con:
            if self._is_accelerometer_working(con):
                try:
                    ratio_data = self.get_trip_ratio_data(con)
                    if ratio_data is not None:
                        bank_trips_since_last_trip, bank_trips_2weeks_count, bank_elevators_count,\
                            our_trips_2weeks_count, end_time = ratio_data
                        # 'bank_trips' includes the trips that *this* car has done, but it's only used when that's zero.

                        if self.last_state >= StoppageState.STOPPED_C90 and self._is_trip_happening():
                            # We've recovered from a stoppage.
                            self._update_state(StoppageState.OK)
                            self._set_last_trip(None)
                            self._log_resumed_event(common_constants.EVENT_SUBTYPE_BANK)
                            logger.info("A trip happened, so the state is changing back to OK")
                        else:
                            # We use the grand sum of all bank_trips here because we don't want to do the
                            # self-learning algorithm until we've had a while to collect data.
                            not_enough_bank_trips = bank_trips_2weeks_count < constants.MINIMUM_SELFLEARNING_BANK_TRIPS
                            not_enough_trips = our_trips_2weeks_count < constants.MINIMUM_SELFLEARNING_SELF_TRIPS

                            shutdown_result = None
                            if not_enough_bank_trips or not_enough_trips:
                                confidences = self._get_confidences_for_elevators(bank_elevators_count)
                                shutdown_result = self.default_detection(bank_trips_since_last_trip, confidences)
                            else:
                                # Use 2 here because bank size is inherently included in the ratio calculation.
                                confidences = self._get_confidences_for_elevators(2)
                                shutdown_result = self.self_learning_detection(bank_trips_2weeks_count, our_trips_2weeks_count,
                                                         bank_trips_since_last_trip, confidences)

                            if shutdown_result and shutdown_result.is_shutdown:
                                self._update_state(shutdown_result.confidence)
                                self._log_stoppage_event(shutdown_result.confidence, common_constants.EVENT_SUBTYPE_BANK)
                                self._set_last_trip(end_time)
                except ProgrammingError as ex:
                    logger.error("Exception in bank stoppage.run: {}".format(ex))
