#!/usr/bin/env python3
#  Python program to check for gaps in sensor data.

import os
from datetime import datetime, timedelta
from pathlib import Path
import logging

from sqlalchemy.sql import text

import anomaly_detector.constants as constants
import utilities.common_constants as common_constants
from utilities.db_utilities import engine
from utilities.misc_utilities import MiscUtilities


find_gaps_in_data = """
WITH data_with_sentinels AS
(                                                -- We include an N second overlap with the previous time interval
  SELECT
    :start_of_interval as timestamp,             -- One sentinel at the start of the time interval
    TRUE as sentinel
  UNION
  SELECT
    :end_of_interval as timestamp,               -- One sentinel at the end of the time interval
    TRUE as sentinel
  UNION
  SELECT
    timestamp,                                   -- Accelerometer (or altimeter) data during that interval
    FALSE as sentinel
  FROM {0}
  WHERE timestamp > :start_of_interval
    AND timestamp < :end_of_interval
),
lag_data AS
(
  SELECT
    timestamp,
    timestamp - LAG(timestamp, 1) OVER (ORDER BY timestamp ASC) as gap,
    sentinel
  FROM data_with_sentinels
)
SELECT * FROM lag_data WHERE gap >= INTERVAL :min_gap_size ORDER BY timestamp ASC LIMIT 1;  -- Find all N+ second gaps
"""
# TODO: An improvement would be to go back to the most recent timestamp before :start_of_interval to be more accurate.


logger = logging.getLogger(__name__)


class GapProcessor:
    is_sensor_running = None
    storage_filename = None

    def __init__(self):
        self.storage_filename = os.path.join(
            common_constants.STORAGE_FOLDER, constants.STORAGE_FILE_NAME
        )
        # Assume these are running until proven otherwise.
        self.is_sensor_running = {
            constants.ALTIMETER_TABLE: True,
            constants.ACCELEROMETER_TABLE: True,
        }
        self._update_gap_status()

    def detect_gaps(self):
        time_of_last_execution = self._time_of_last_execution()
        self._set_last_execution_time()
        self._check_for_gaps(constants.ALTIMETER_TABLE, time_of_last_execution)
        self._check_for_gaps(constants.ACCELEROMETER_TABLE, time_of_last_execution)

    def _check_for_gaps(self, sensor_table, time_of_last_execution):
        # Back up to the earliest possible start of a gap in the previous time interval
        next_start_timestamp = time_of_last_execution - timedelta(
            seconds=constants.MIN_GAP_SIZE
        )
        sanity_counter = constants.ABSOLUTE_MAX_LOOP_ITERATIONS
        end_of_window = datetime.now()
        while next_start_timestamp < end_of_window:
            # Handle one or more gaps in the window this way, including starting/ending a gap
            sanity_counter -= 1
            if sanity_counter <= 0:
                raise Exception(
                    "Too many gaps and end-of-gaps found in {0} table".format(
                        sensor_table
                    )
                )
            if self.is_sensor_running[sensor_table]:
                with engine.connect() as con:
                    row = con.execute(
                        text(
                            find_gaps_in_data.format(sensor_table)
                        ),  # Can't use table name in text param
                        start_of_interval=next_start_timestamp,
                        end_of_interval=end_of_window,
                        min_gap_size="{0} seconds".format(constants.MIN_GAP_SIZE),
                    ).fetchone()
                if row:
                    start_of_gap = row["timestamp"] - row["gap"]
                    logger.debug(
                        "Detected a gap in {0} data starting at {1}".format(
                            sensor_table, start_of_gap
                        )
                    )
                    self._create_event(
                        GapProcessor.get_event_type(sensor_table),
                        common_constants.EVENT_SUBTYPE_GAP_START,
                        start_of_gap,
                    )
                    self.is_sensor_running[sensor_table] = False
                    next_start_timestamp = row["timestamp"]
                if self.is_sensor_running[sensor_table]:
                    next_start_timestamp = end_of_window
            if not self.is_sensor_running[
                sensor_table
            ]:  # The above code will fall through here if it finds a gap.
                with engine.connect() as con:
                    query_string = (
                        "SELECT COUNT(*) as samples_after_gap, MIN(timestamp) as recovery_time "
                        + "FROM {0} ".format(sensor_table)
                        + "WHERE timestamp > :start_of_interval "
                        + "AND timestamp < :end_of_interval  -- stop at end of window for testing purposes"
                    )
                    row = con.execute(
                        text(query_string),
                        start_of_interval=next_start_timestamp,
                        end_of_interval=end_of_window,
                    ).fetchone()
                    if row["samples_after_gap"] > 0:
                        logger.debug(
                            "Detected end of gap in {0} starting at {1}".format(
                                sensor_table, row["recovery_time"]
                            )
                        )
                        self._create_event(
                            GapProcessor.get_event_type(sensor_table),
                            common_constants.EVENT_SUBTYPE_GAP_END,
                            row["recovery_time"],
                        )
                        self.is_sensor_running[sensor_table] = True
                        next_start_timestamp = row["recovery_time"]
                    else:
                        # We've scanned the entire window and found no data, so quit.
                        next_start_timestamp = end_of_window

    def _update_gap_status(self):
        (
            self.is_sensor_running[constants.ALTIMETER_TABLE],
            self.is_sensor_running[constants.ACCELEROMETER_TABLE],
        ) = MiscUtilities.get_sensor_gap_status(engine, logger)

    def _create_event(self, event_type, event_subtype, occurred_at):
        with engine.connect() as con:
            query_str = text(
                "INSERT INTO events (occurred_at, detected_at, source, event_type, event_subtype)"
                "     VALUES (:occurred_at, NOW(), 'GapProcessor', :event_type, :event_subtype)"
            )
            con.execute(
                query_str,
                occurred_at=occurred_at,
                event_type=event_type,
                event_subtype=event_subtype,
            )

    def _set_last_execution_time(self):
        Path(self.storage_filename).touch()

    def _time_of_last_execution(self):
        if not os.path.exists(self.storage_filename):
            logger.info("Creating storage file for timekeeping")
            self._set_last_execution_time()
        return datetime.fromtimestamp(os.path.getmtime(self.storage_filename))

    @staticmethod
    def get_event_type(sensor_table):
        if sensor_table == constants.ALTIMETER_TABLE:
            return common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP
        elif sensor_table == constants.ACCELEROMETER_TABLE:
            return common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP
        else:
            raise Exception("Unsupported sensor table type")
