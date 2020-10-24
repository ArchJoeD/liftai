#! /usr/bin/python3
import logging
from datetime import datetime

from sqlalchemy.sql import text

from escalator_stoppage import constants
from utilities import common_constants
from utilities.stoppage_processor import StoppageState, StoppageProcessor


sql_statement = """
INSERT INTO escalator_vibration (timestamp, position)
SELECT
  NOW(),
  AVG( ABS(z_data), AVG(x_data), AVG(y_data) ) * 100
FROM accelerometer_data WHERE timestamp > NOW() - INTERVAL '120 SECONDS';
"""


logger = logging.getLogger(__name__)


class EscalatorStoppageProcessor(StoppageProcessor):
    name = "escalator_stoppage"
    parms_table_name = None

    def __init__(self):
        super().__init__(logger)

    def _update_state(self, new_state):
        new_state_is_stopped = new_state >= StoppageState.STOPPED_C90
        last_state_not_stopped = self.last_state < StoppageState.STOPPED_C90
        if last_state_not_stopped and new_state_is_stopped:
            ts = datetime.now()
            self._update_current_stopped_timestamp(ts)
        elif (
            self.last_state >= StoppageState.STOPPED_C90
            and new_state == StoppageState.OK
        ):
            ts = 0
            self._update_current_stopped_timestamp(ts)

        with self.engine.connect() as con:
            trans = con.begin()
            try:
                # When the state changes, force a new report to be sent
                con.execute(
                    "DELETE FROM data_to_send WHERE id=(SELECT MAX(id) FROM data_to_send WHERE endpoint='devices/report')"
                )
                trans.commit()
            except Exception as ex:
                trans.rollback()
                logger.error("Exception update escalator stoppage status: " + str(ex))

        return super()._update_state(new_state)

    def _start_stoppage(self, confidence):
        self._log_stoppage_event(
            confidence, common_constants.EVENT_SUBTYPE_ESCALATOR_VIBRATION
        )
        self._update_state(StoppageState.STOPPED_C99)

    def _trigger_shutdown(self, vib_xy, vib_z):
        if self.last_state < StoppageState.STOPPED_C99:
            logger.info(
                "Detecting a shutdown condition: xy = {},  z = {}".format(vib_xy, vib_z)
            )
            self._start_stoppage(StoppageState.STOPPED_C99)
        else:
            logger.debug(
                "Escalator is still too quiet and still shut down, xy = {}, z = {}".format(
                    vib_xy, vib_z
                )
            )

    def _has_resumed_from_shutdown(self, vib_xy, vib_z):
        if self.last_state >= StoppageState.STOPPED_C90:
            self._update_state(StoppageState.OK)
            self._log_resumed_event(common_constants.EVENT_SUBTYPE_ESCALATOR_VIBRATION)
            logger.error("Escalator started moving again")
        else:
            logger.debug(
                "Escalator is still running, xy = {}, z = {}".format(vib_xy, vib_z)
            )

    def run(self):
        with self.engine.connect() as con:
            try:
                con.execute(
                    sql_statement
                )  # Update the escalator vibration averages with the latest data.

                qs = text(
                    "  SELECT xy_freq_5, z_freq_5"
                    "    FROM escalator_vibration "
                    "ORDER BY timestamp DESC LIMIT 1"
                )
                rs = con.execute(qs)
                r = rs.fetchone()
                if r is not None:
                    xy = int(r["xy_freq_5"])
                    z = int(r["z_freq_5"])
                    xy_under_threshold = xy < constants.HARDCODED_XY_VIBRATION_THRESHOLD
                    z_under_threshold = z < constants.HARDCODED_Z_VIBRATION_THRESHOLD
                    if xy_under_threshold and z_under_threshold:
                        logger.debug("off")
                        # Escalator is *not* running
                    #                        self._trigger_shutdown(xy, z)
                    else:
                        logger.debug("on")
                        # Escalator is running
                #                        self._has_resumed_from_shutdown(xy, z)
                else:
                    logger.error("No vibration data in escalator_vibration table")

            except Exception as ex:
                logger.error("Exception in escalator stoppage detection: " + str(ex))
                raise Exception("Exception in escalator stoppage detection: " + str(ex))
