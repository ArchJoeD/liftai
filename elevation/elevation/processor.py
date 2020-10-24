#!/usr/bin/env python3

import logging
import json
from datetime import timedelta

from sqlalchemy import text

import elevation.constants as constants
import utilities.common_constants as common_constants
from utilities.db_utilities import engine
from utilities.misc_utilities import MiscUtilities


# There's too much complexity trying to do this at the same time we get the most recent gap of each type to determine
# the current gap status.
sql_get_unprocessed_gap_events = """
-- Get all the unprocessed gaps (after any elevation events) that happened within the last :oldest_altimeter_data minutes.
SELECT event_type, event_subtype, occurred_at
FROM events
WHERE event_type IN (:altimeter_gap, :accelerometer_gap)
  AND occurred_at > NOW() - INTERVAL :oldest_altimeter_data     -- don't go back further than the saved data
  AND occurred_at > COALESCE((SELECT occurred_at FROM events WHERE source = :source
                                -- Don't reprocess stuff we've already finished.
                                ORDER BY id DESC LIMIT 1), NOW() - INTERVAL :oldest_altimeter_data)
ORDER BY id ASC;      -- Two events can have the same occurred at, so we need to sort by id.
"""

sql_estimate_gap_elevation_change = """
WITH gap_start AS
(
    SELECT altitude_x16
    FROM altimeter_data
    WHERE timestamp < :gap_start
    ORDER BY id DESC
    LIMIT 1
),
gap_end AS
(
    SELECT altitude_x16
    FROM altimeter_data
    WHERE timestamp > :gap_end
    ORDER BY id ASC
    LIMIT 1
)
SELECT COALESCE(e.altitude_x16 - s.altitude_x16, 0) FROM gap_end e, gap_start s;
"""

logger = logging.getLogger(__name__)


class ElevationProcessor:
    def handle_any_gaps(self):
        altim_gap_status, accel_gap_status = MiscUtilities.get_sensor_gap_status(
            engine, logger
        )
        if not (altim_gap_status and accel_gap_status):
            # We can't do anything during a gap in either sensor.
            return

        with engine.connect() as con:
            events = con.execute(
                text(sql_get_unprocessed_gap_events),
                altimeter_gap=common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP,
                accelerometer_gap=common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP,
                source=common_constants.EVENT_SOURCE_ELEVATION_PROCESSOR,
                oldest_altimeter_data="{0} minutes".format(
                    constants.OLDEST_ALTIMETER_DATA
                ),
            ).fetchall()
        gap_start = None
        altim_gap = False
        accel_gap = False
        for event in events:
            if event["event_subtype"] == common_constants.EVENT_SUBTYPE_GAP_START:
                if (
                    event["event_type"]
                    == common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP
                ):
                    logger.debug(
                        "Start of gap in altimeter data at {0}".format(
                            event["occurred_at"]
                        )
                    )
                    altim_gap = True
                else:
                    logger.debug(
                        "Start of gap in accelerometer data at {0}".format(
                            event["occurred_at"]
                        )
                    )
                    accel_gap = True
                if not (altim_gap and accel_gap):
                    # The first gap true event defines the start of overall gap.
                    gap_start = event["occurred_at"]
            elif event["event_subtype"] == common_constants.EVENT_SUBTYPE_GAP_END:
                if (
                    event["event_type"]
                    == common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP
                ):
                    altim_gap = False
                else:
                    accel_gap = False
                if not altim_gap and not accel_gap:
                    # End of overall gap, create missing trip or elevation reset event (aka create new map)
                    gap_end = event[
                        "occurred_at"
                    ]  # The last event is the end of overall gap.
                    if gap_start is None:
                        logger.debug(
                            "The start of the gap was more than {0} minutes ago, creating a new map".format(
                                constants.OLDEST_ALTIMETER_DATA
                            )
                        )
                        self._elevation_reset(gap_end)
                    else:
                        if gap_end - gap_start > timedelta(
                            minutes=constants.MAX_SENSOR_GAP
                        ):
                            logger.info(
                                "Can't recover elevation, gap too large at {0}".format(
                                    gap_end - gap_start
                                )
                            )
                            self._elevation_reset(gap_end)
                        else:
                            logger.debug(
                                "Disabled: recovering elevation change during short gap"
                            )
                            elevation_change = self._get_elevation_change(
                                gap_start, gap_end
                            )
                            # The floor processor will treat this like a trip.
                            self._missed_trips(gap_end, elevation_change)
                    # Signal to ourself that we've processed gaps up to this point in time.
                    self._processed_gaps(gap_end)
                    gap_start = None
            # It's normal to have other gap event subtypes that we don't care about or recognize.

    def _get_elevation_change(self, gap_start, gap_end):
        with engine.connect() as con:
            query_str = text(sql_estimate_gap_elevation_change)
            elev_change = con.execute(
                query_str, gap_start=gap_start, gap_end=gap_end
            ).first()
            return 0 if elev_change is None else elev_change[0]

    def _processed_gaps(self, end_of_gap):
        # We're done processing all gaps up to the point of end_of_gap
        with engine.connect() as con:
            query_str = text(
                "INSERT INTO events (occurred_at, detected_at, source, event_type, event_subtype)"
                "     VALUES (:occurred_at, NOW(), :source, :event_type, :event_subtype)"
            )
            con.execute(
                query_str,
                occurred_at=end_of_gap,
                source=common_constants.EVENT_SOURCE_ELEVATION_PROCESSOR,
                event_type=common_constants.EVENT_TYPE_ELEVATION,
                event_subtype=common_constants.EVENT_SUBTYPE_PROCESSED_GAP,
            )

    def _missed_trips(self, occurred_at, elevation_change):
        # We missed one or more trips.  The net change in elevation was elevation_change.
        # NOTE: The trip detector is now handling missed trips, so do nothing here.
        #       We're still doing _elevation_reset() here, but that's about it.
        pass

        """
        with engine.connect() as con:
            details = {
                common_constants.EVENT_DETAILS_ELEVATION_CHANGE: elevation_change
            }
            query = text(
                "INSERT INTO events (occurred_at, detected_at, source, event_type, event_subtype, details) "
                "VALUES (:occurred_at, NOW(), 'ElevationProcessor', :event_type, :event_subtype, :details)"
            )
            con.execute(
                query,
                occurred_at=occurred_at,
                event_type=common_constants.EVENT_TYPE_ELEVATION,
                event_subtype=common_constants.EVENT_SUBTYPE_MISSING_TRIP,
                details=json.dumps(details),
            )
            """

    def _elevation_reset(self, occurred_at):
        # The overall gap was too large to estimate missing trips, the elevation is unknown at this point.
        with engine.connect() as con:
            query = text(
                "INSERT INTO events (occurred_at, detected_at, source, event_type, event_subtype) "
                "VALUES (:occurred_at, NOW(), 'ElevationProcessor', :event_type, :event_subtype)"
            )
            con.execute(
                query,
                occurred_at=occurred_at,
                event_type=common_constants.EVENT_TYPE_ELEVATION,
                event_subtype=common_constants.EVENT_SUBTYPE_ELEVATION_RESET,
            )
