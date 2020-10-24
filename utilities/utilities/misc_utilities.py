from sqlalchemy import text

import utilities.common_constants as common_constants

latest_of_each_type_query = """
-- Select the most recent event of each gap type.
SELECT event_type, event_subtype, occurred_at
FROM ( SELECT ROW_NUMBER() OVER (PARTITION BY event_type ORDER BY id DESC) AS r,
       e.* FROM events e WHERE e.event_type IN (:altimeter_data_gap, :accelerometer_data_gap) )
grouped_events WHERE grouped_events.r < 2;
"""


class MiscUtilities:
    @staticmethod
    def get_sensor_gap_status(engine, logger):
        """
        This utility returns the status of whether we are in a gap or not for both the accelerometer and altimeter.
        :param engine: SQLAlchemy engine
        :param logger: The loggers we use in the project.
        :return:    the altimeter and accelerometer status as a boolean (is it currently running?)
        """
        altim_result = True
        accel_result = True
        with engine.connect() as con:
            rows = con.execute(
                text(latest_of_each_type_query),
                altimeter_data_gap=common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP,
                accelerometer_data_gap=common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP,
            )
        for row in rows:
            if row["event_subtype"] == common_constants.EVENT_SUBTYPE_GAP_START:
                result = False
            elif row["event_subtype"] == common_constants.EVENT_SUBTYPE_GAP_END:
                result = True
            else:
                logger.error(
                    "Invalid event subtype for altimeter or accel data gap: {0}".format(
                        row["event_subtype"]
                    )
                )
                result = True  # Just continue on.
            if row["event_type"] == common_constants.EVENT_TYPE_ALTIMETER_DATA_GAP:
                altim_result = result
            elif (
                row["event_type"] == common_constants.EVENT_TYPE_ACCELEROMETER_DATA_GAP
            ):
                accel_result = result
            else:
                logger.error("Internal event type error: {0}".format(row["event_type"]))
        return altim_result, accel_result
