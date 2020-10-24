#!/usr/bin/env python3
#  Python program to get the status of the elevator car for the purposes of lighting the LEDs

import gpio.constants as constants

from utilities.db_utilities import engine


sql_query = """
SELECT
  '{0}' as type,
  COUNT(*) as count
FROM problems
WHERE ended_at IS NULL
UNION ALL
SELECT
  '{1}' AS type,
  COUNT(*) AS count
FROM roa_watch_requests WHERE request_time > NOW() - INTERVAL '2 HOURS'
UNION ALL
SELECT
  '{2}' AS type,
  COUNT(*) AS count
FROM data_to_send WHERE timestamp > NOW() - INTERVAL '2 HOURS' AND success=TRUE;
""".format(constants.CAR_STATUS_PROBLEMS_KEY, constants.CAR_STATUS_ROA_WATCH_KEY,constants.CAR_STATUS_NOT_CONNECTED_KEY)


class CarStatus:

    def __init__(self, logger):
        self.logger = logger

    def get_car_status(self):
        rows = self._get_data()
        return self._process_car_status(rows)

    def _process_car_status(self, rows):
        result = {}
        if rows is not None:
            for r in rows:
                if r[0] == constants.CAR_STATUS_PROBLEMS_KEY:
                    result[constants.CAR_STATUS_PROBLEMS_KEY] = r[1] != 0
                elif r[0] == constants.CAR_STATUS_ROA_WATCH_KEY:
                    result[constants.CAR_STATUS_ROA_WATCH_KEY] = r[1] != 0
                elif r[0] == constants.CAR_STATUS_NOT_CONNECTED_KEY:
                    # We only care if nothing got sent.
                    result[constants.CAR_STATUS_NOT_CONNECTED_KEY] = r[1] == 0
                else:
                    self.logger.error("SQL results don't match what we expected: {0} with value of {1}".format(r[0],r[1]))
        else:
            self.logger.error("Failed to fetch problem, car, roa, system notif data from database")
            raise Exception("GPIO CarStatus failed to fetch problem, car, roa, system notif data from database")
        return result

    def _get_data(self):
        with engine.connect() as con:
            rows = con.execute(sql_query)
        return rows
