from os import getloadavg
from datetime import timedelta
from collections import namedtuple

from sqlalchemy.sql import text

from utilities import common_constants
from utilities.serial_number import SerialNumber
from utilities.db_utilities import Problem, Event


vibration_sql = """
-- First, collect up the two types of accleration data (starting and ending accelerations)
-- This is the point where we convert p2p names to ptp.
SELECT
  CASE
    WHEN is_start_of_trip = True THEN 'start_accel'
    ELSE 'end_accel'
  END as type,
  max((vibration->>'jerk')::NUMERIC(10,2)) as max_jerk,
  ROUND(avg((vibration->>'jerk')::NUMERIC(10,2)), 2) as avg_jerk,
  ROUND(avg((vibration->>'p2p_x_95')::NUMERIC(10,2)), 2) as ptp_x_95,  -- Notice ptp vs p2p
  ROUND(avg((vibration->>'p2p_y_95')::NUMERIC(10,2)), 2) as ptp_y_95,
  ROUND(avg((vibration->>'p2p_z_95')::NUMERIC(10,2)), 2) as ptp_z_95,
  max((vibration->>'p2p_x_max')::NUMERIC(10,2)) as ptp_x_max,
  max((vibration->>'p2p_y_max')::NUMERIC(10,2)) as ptp_y_max,
  max((vibration->>'p2p_z_max')::NUMERIC(10,2)) as ptp_z_max
FROM accelerations
WHERE start_time >= :hour_start AND start_time < :hour_end
GROUP BY is_start_of_trip
-- Then add in the trip data
UNION
SELECT
  'trip' as type,
  NULL as max_jerk,
  NULL as avg_jerk,
  ROUND(avg((vibration->>'p2p_x_95')::NUMERIC(10,2)), 2) as ptp_x_95,  -- Notice ptp vs p2p
  ROUND(avg((vibration->>'p2p_y_95')::NUMERIC(10,2)), 2) as ptp_y_95,
  ROUND(avg((vibration->>'p2p_z_95')::NUMERIC(10,2)), 2) as ptp_z_95,
  max((vibration->>'p2p_x_max')::NUMERIC(10,2)) as ptp_x_max,
  max((vibration->>'p2p_y_max')::NUMERIC(10,2)) as ptp_y_max,
  max((vibration->>'p2p_z_max')::NUMERIC(10,2)) as ptp_z_max
FROM trips
WHERE start_time >= :hour_start AND start_time < :hour_end
GROUP BY type;
"""

trip_stats_sql = """
SELECT
  CAST( ROUND(CAST(SUM(EXTRACT(EPOCH FROM t.end_time) - EXTRACT(EPOCH FROM t.start_time)) / (60 * 60) AS NUMERIC), 2) AS FLOAT) as duty_cycle,
  CAST( ROUND(CAST(MAX(EXTRACT(EPOCH FROM t.end_time) - EXTRACT(EPOCH FROM t.start_time)) AS NUMERIC), 1) AS FLOAT) as max_trip_duration,
  CAST( ROUND(CAST(MIN(EXTRACT(EPOCH FROM t.end_time) - EXTRACT(EPOCH FROM t.start_time)) AS NUMERIC), 1) AS FLOAT) as min_trip_duration,
  CAST( ROUND(AVG(CAST(t.audio->>'noise' AS NUMERIC)), 4) AS FLOAT) as trip_noise,
  CAST( ROUND(AVG(CAST(a1.audio->>'noise' AS NUMERIC)), 4) AS FLOAT) as start_accel_noise,
  CAST( ROUND(AVG(CAST(a2.audio->>'noise' as NUMERIC)), 4) AS FLOAT) as end_accel_noise,
  ROUND(MAX(t.speed)) as max_speed,
  ROUND(MIN(t.speed)) as min_speed,
  ROUND(AVG(t.speed)) as avg_speed
FROM trips t
JOIN accelerations a1 ON t.start_accel = a1.id
JOIN accelerations a2 ON t.end_accel = a2.id
WHERE t.start_time >= :start_time AND t.start_time < :end_time;
"""

# These must have the same names as the SQL statement fields.
vibration_fields = [
    "max_jerk",
    "avg_jerk",
    "ptp_x_95",
    "ptp_x_max",
    "ptp_y_95",
    "ptp_y_max",
    "ptp_z_95",
    "ptp_z_max",
]
# Two character encoding
vibration_prefix_map = {"start_accel": "s_", "end_accel": "e_", "trip": "t_"}

RelevelingStatusData = namedtuple(
    "RelevelingStatusData", ["start_detected", "end_detected", "count"]
)


def select_relevelings(query):
    return query.filter(
        Problem.problem_type == common_constants.PROB_TYPE_ANOMALY,
        Problem.problem_subtype == common_constants.PROB_SUBTYPE_RELEVELING,
    )


class StatusData:
    @staticmethod
    def get_hourly_report_payload(session, report_start_time_utc):
        report_end_time = report_start_time_utc + timedelta(hours=1)

        row = session.execute(
            text(trip_stats_sql),
            {
                "start_time": report_start_time_utc,
                "end_time": report_end_time,
            },
        ).first()

        payload = {
            "type": common_constants.MESSAGE_TYPE_HOURLY_REPORT,
            "id": SerialNumber.get(),
            "date": report_start_time_utc.isoformat(),
            "max_speed": row["max_speed"],
            "min_speed": row["min_speed"],
            "avg_speed": row["avg_speed"],
            "duty_cycle": row["duty_cycle"] or 0,
            "system": StatusData._get_system_data(),
            "uptime": StatusData._get_uptime_one_hour(session, report_start_time_utc),
        }

        vibration_data = StatusData._get_vibration_data(session, report_start_time_utc)
        if vibration_data:
            payload["vibration"] = vibration_data

        if (
            row["max_trip_duration"] is not None
            and row["min_trip_duration"] is not None
        ):
            payload["max_trip_duration"] = row["max_trip_duration"]
            payload["min_trip_duration"] = row["min_trip_duration"]

        if (
            row["trip_noise"] is not None
            and row["start_accel_noise"] is not None
            and row["end_accel_noise"] is not None
        ):
            payload["trip_noise"] = row["trip_noise"]
            payload["start_accel_noise"] = row["start_accel_noise"]
            payload["end_accel_noise"] = row["end_accel_noise"]

        releveling_data = StatusData._get_releveling_data(
            session, report_start_time_utc, report_end_time
        )

        if releveling_data:
            payload["releveling"] = releveling_data._asdict()

        return payload

    @staticmethod
    def _get_vibration_data(session, start_time):
        rows = StatusData._run_vibration_sql_query(
            session, start_time, start_time + timedelta(hours=1)
        )

        vjson = {}
        for row in rows:
            if row["type"] not in vibration_prefix_map:
                raise Exception("Bad vibration row type, {0}".format(row["type"]))
            prefix = vibration_prefix_map[row["type"]]

            for field in vibration_fields:
                if field in row and row[field]:
                    # Convert Decimal to float so it can be serialized to json
                    vjson[prefix + field] = round(float(row[field]), 2)

        return vjson if vjson else None

    @staticmethod
    def _run_vibration_sql_query(session, start_time, end_time):
        tripv_query_str = text(vibration_sql)
        return session.execute(
            tripv_query_str,
            {"hour_start": start_time, "hour_end": end_time},
        ).fetchall()

    @staticmethod
    def _get_releveling_data(session, start_dt, end_dt):
        open_releveling_problem = select_relevelings(
            session.query(Problem.created_at)
            .filter(Problem.ended_at == None)
            .order_by(Problem.created_at.desc())
        ).first()

        closed_releveling_problem = select_relevelings(
            session.query(Problem)
            .filter(Problem.ended_at >= start_dt)
            .order_by(Problem.ended_at.desc())
        ).first()

        releveling_start_detected = bool(
            open_releveling_problem
            and open_releveling_problem.created_at
            and open_releveling_problem.created_at >= start_dt
        )
        releveling_end_detected = bool(closed_releveling_problem)

        if not (open_releveling_problem or releveling_end_detected):
            return None

        num_relevelings = (
            session.query(Event)
            .filter(
                Event.event_type == common_constants.EVENT_TYPE_ANOMALY,
                Event.event_subtype == common_constants.EVENT_SUBTYPE_RELEVELING,
                Event.occurred_at >= start_dt,
                Event.occurred_at < end_dt,
            )
            .count()
        )

        return RelevelingStatusData(
            start_detected=releveling_start_detected,
            end_detected=releveling_end_detected,
            count=num_relevelings,
        )

    @staticmethod
    def _get_uptime_one_hour(session, start_of_hour):
        start_of_hour_no_tz = start_of_hour.replace(tzinfo=None)
        query_str = text(
            "SELECT started_at, ended_at, confidence FROM problems "
            "WHERE problem_type = :prob_type "
            "AND (ended_at >= :date OR ended_at is NULL) "
            "AND confidence >= 98.00"
        )
        stoppages = session.execute(
            query_str,
            {
                "prob_type": common_constants.PROB_TYPE_SHUTDOWN,
                "date": start_of_hour_no_tz,
            },
        ).fetchall()
        downtime = timedelta(seconds=0)
        for stoppage in stoppages:
            start_time = stoppage["started_at"]
            end_time = stoppage["ended_at"]
            if start_time is None:
                raise Exception("start_time of stoppage is NULL")
            if start_time < start_of_hour_no_tz:
                start_time = start_of_hour_no_tz
            if end_time is None:
                # If the stoppage hasn't ended, it's still in progress
                end_time = start_of_hour_no_tz + timedelta(hours=1)
            downtime = downtime + (end_time - start_time)
        uptime = round(1 - downtime.total_seconds() / (60 * 60), 2)
        return uptime

    @staticmethod
    def _get_system_data():
        return {
            "load_avg": getloadavg()[-1],
        }
