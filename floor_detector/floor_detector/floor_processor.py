import logging
from datetime import datetime
import json

from sqlalchemy.sql import text

import floor_detector.constants as constants
from notifications.notifications import Notification, NotificationTopic
from utilities import common_constants
from utilities.db_utilities import engine, session_scope, FloorMap
from utilities.device_configuration import DeviceConfiguration

FLOOR_SCHEMA = common_constants.FLOORS_JSON_SCHEMA
FLOOR_LANDING = common_constants.FLOORS_JSON_LANDING_NUM
FLOOR_ELEVATION = common_constants.FLOORS_JSON_ELEVATION
FLOOR_CUMULATIVE_ERR = common_constants.FLOORS_JSON_CUMULATIVE_ERR
FLOOR_LAST_UPDATED = common_constants.FLOORS_JSON_LAST_UPDATED
ELEVATION_RESET = common_constants.EVENT_SUBTYPE_ELEVATION_RESET
MISSING_TRIP = common_constants.EVENT_SUBTYPE_MISSING_TRIP

sql_process_trips_and_events = """
SELECT
    :missing_trip_subtype as type,
    occurred_at,
    id,
    CAST(details->>'elevation change' AS INTEGER) as elevation_change
FROM events
WHERE
    event_type = :event_type
    AND event_subtype = :missing_trip_subtype
    AND occurred_at > :starting_time
UNION ALL
SELECT
    'elevation reset' as type,
    occurred_at,
    id,
    0 as elevation_change
FROM events
WHERE
    event_type = :event_type
    AND event_subtype = :elevation_reset_subtype
    AND occurred_at > :starting_time
UNION ALL
SELECT
    'trip' as type,
    start_time as occurred_at,
    id,
    elevation_change as elevation_change
FROM trips
WHERE elevation_processed = TRUE
    AND ending_floor IS NULL
    AND start_time > :starting_time
ORDER BY occurred_at ASC
"""

logger = logging.getLogger(__name__)


class FloorProcessor:
    last_update = None
    logger = None

    def __init__(self):
        self.last_update = self._get_last_update_timestamp()
        if not self.last_update:
            self._create_new_map(datetime.now().isoformat(), "initial")
        self.elevation = self._get_last_elevation()

    def process_trips(self):
        """
        This reads events and trips from the database and assigns a floor to the
        next trip, if possible.
        :return:
        """
        if not self._get_floor_count():
            # If we don't have a count of the number of floors we can't do floor detect.
            return

        for item in self._get_events_and_trips():

            if item["type"] == ELEVATION_RESET:
                logger.info("Elevation reset at {0}".format(item["occurred_at"]))
                self._create_new_map(item["occurred_at"], "elevation_reset")

            if item["type"] == MISSING_TRIP:
                logger.info(
                    "Missed trip elevation change of {0}".format(
                        item["elevation_change"]
                    )
                )

            # A missed trip is where we know the elevation change, but no details to create a trip.
            if item["type"] in ("trip", MISSING_TRIP) and item["elevation_change"]:
                # If the elevation change is null, ignore the trip
                tentative_elevation = self.elevation + item["elevation_change"]
                closest_floor, floors = self._get_closest_floor(tentative_elevation)
                est_error = (
                    (tentative_elevation - floors[closest_floor][FLOOR_ELEVATION])
                    if closest_floor is not None
                    else None
                )

                if (
                    est_error is not None
                    and abs(est_error) <= constants.MAX_FLOOR_ERROR
                ):
                    if item["type"] == "trip":
                        self._update_trip(item["id"], closest_floor, est_error)
                    floors[closest_floor][FLOOR_CUMULATIVE_ERR] += est_error
                    self._update_floors_and_map(
                        floors,
                        item["occurred_at"],
                        # Use floor elevation and not tentative elevation here.
                        floors[closest_floor][FLOOR_ELEVATION],
                    )
                    # Already updated the map's last elevation
                else:
                    logger.info(
                        "Found possible new floor at {0}".format(tentative_elevation)
                    )
                    new_floor = self._create_new_floor(
                        tentative_elevation, update_time=item["occurred_at"]
                    )

                    if new_floor:
                        self._add_floor_recompute_landings(new_floor)
                        # The first trip to a new floor has an error of 0
                        if item["type"] == "trip":
                            self._update_trip(item["id"], list(new_floor.keys())[0], 0)
                        self._update_last_elevation(tentative_elevation)

            self._set_last_update_timestamp(item["occurred_at"])

    def _get_events_and_trips(self):
        """
        Get all the trips that have been processed with elevation,
        missing trip events (which have an associated elevation change),
        and elevation reset events (create a new map).  These are sorted
        in ascending time order.
        :return: The trips and events in asc order
        """
        with engine.connect() as con:
            return con.execute(
                text(sql_process_trips_and_events),
                event_type=common_constants.EVENT_TYPE_ELEVATION,
                missing_trip_subtype=MISSING_TRIP,
                starting_time=self.last_update,
                elevation_reset_subtype=ELEVATION_RESET,
            ).fetchall()

    def _get_last_elevation(self):
        with session_scope() as session:
            floor_map = FloorMap.get_lastest_map(
                session, columns=[FloorMap.last_elevation]
            )
            return floor_map.last_elevation if floor_map else None

    def _update_last_elevation(self, elevation):
        self.elevation = elevation
        query = text(
            "UPDATE floor_maps set last_elevation = :elevation "
            "WHERE id IN (SELECT max(id) FROM floor_maps)"
        )
        with engine.connect() as con:
            con.execute(query, elevation=self.elevation)

    def _get_last_update_timestamp(self):
        with session_scope() as session:
            floor_map = FloorMap.get_lastest_map(
                session, columns=[FloorMap.last_update]
            )
            return floor_map.last_update.replace(tzinfo=None) if floor_map else None

    def _set_last_update_timestamp(self, update_time):
        query = text(
            "UPDATE floor_maps SET last_update = :last_update "
            "WHERE id IN (SELECT max(id) FROM floor_maps)"
        )
        with engine.connect() as con:
            con.execute(query, last_update=update_time)
        self.last_update = update_time

    def _create_new_map(self, start_time, reason):
        # Might as well start with elevation set to 0, no absolute reference
        query = text(
            "INSERT INTO floor_maps (start_time, last_update, last_elevation, floors) "
            "VALUES (:init_time, :init_time, 0, '{}')"
        )
        with engine.connect() as con:
            con.execute(query, init_time=start_time)
        self.elevation = 0
        self._set_last_update_timestamp(start_time)
        Notification.send(NotificationTopic.FLOOR_MAP_CREATED, {"reason": reason})

    def _get_closest_floor(self, tentative_elevation):
        # Return index into closest floor along with the whole set of floors.
        floors = self._get_floors()
        if floors == {}:
            return None, floors
        closest_floor = min(
            floors, key=lambda k: abs(floors[k][FLOOR_ELEVATION] - tentative_elevation)
        )
        return closest_floor, floors

    def _update_trip(self, trip_id, ending_floor, est_error):
        query = text(
            "UPDATE trips SET ending_floor = :ending_floor, "
            "floor_map_id = :floor_map_id, floor_estimated_error = :est_error "
            "WHERE id = :trip_id"
        )
        with session_scope() as session:
            floor_map = FloorMap.get_lastest_map(session, columns=[FloorMap.id])
            floor_map_id = floor_map.id if floor_map else None

            session.execute(
                query,
                {
                    "ending_floor": ending_floor,
                    "floor_map_id": floor_map_id,
                    "est_error": est_error,
                    "trip_id": trip_id,
                },
            )

    def _update_floors_and_map(
        self, updated_floors, map_update_time, maps_last_elevation
    ):
        # elevation is a separate arg because we probably don't want to assume
        # that we want to use this floor's elevation as the map's last elevation
        query = text(
            "UPDATE floor_maps SET floors = :floors, "
            "last_elevation = :elevation, last_update = :map_update_time "
            "WHERE id IN (SELECT max(id) FROM floor_maps)"
        )
        with engine.connect() as con:
            con.execute(
                query,
                floors=json.dumps(updated_floors),
                elevation=maps_last_elevation,
                map_update_time=map_update_time,
            )
        # Always keeping the "cached" version up to date.
        self.elevation = maps_last_elevation

    def _add_floor_recompute_landings(self, floor):
        floors = self._get_floors()
        floors.update(floor)
        elevations_ids = sorted(
            (floor[FLOOR_ELEVATION], floor_id) for floor_id, floor in floors.items()
        )
        landing_number = 0
        for elev in elevations_ids:
            floors[elev[1]][FLOOR_LANDING] = landing_number
            landing_number += 1
        self._set_floors(floors)

    def _get_floors(self):
        with session_scope() as session:
            floor_map = FloorMap.get_lastest_map(session, columns=[FloorMap.floors])
            return floor_map.floors if floor_map else {}

    def _set_floors(self, floors):
        # Don't set last_update on map here.
        query = text(
            "UPDATE floor_maps SET floors = :floors "
            "WHERE id IN (SELECT max(id) FROM floor_maps)"
        )
        with engine.connect() as con:
            con.execute(query, floors=json.dumps(floors))

    def _create_new_floor(self, elevation, update_time):
        """
        Create a new floor with the given elevation unless we already have
        the configured number of floors.  In that case, the map is
        misaligned.
        :param elevation: integer elevation relative to when the map started.
        :return: Updated floors or None if we created a new map.
        """
        floors = self._get_floors()
        # JSONB int key issue: https://stackoverflow.com/a/1451857
        # This is the only place we look at floor IDs as integers.
        # If no keys exist yet, start with 0 + 1 (reason for using [0])
        int_keys = [0] + [int(str_id) for str_id in floors.keys()]
        new_int_id = max(int_keys) + 1
        if new_int_id <= self._get_floor_count():
            return {
                str(new_int_id): {
                    FLOOR_SCHEMA: common_constants.FLOORS_CURRENT_SCHEMA,
                    FLOOR_LANDING: -1,
                    FLOOR_ELEVATION: elevation,
                    FLOOR_CUMULATIVE_ERR: 0,
                    FLOOR_LAST_UPDATED: update_time.isoformat(),
                }
            }
        else:
            logger.error("Map misalignment: too many floors")
            self._create_new_map(datetime.now(), "misalignment")
            return None

    def _get_floor_count(self):
        return DeviceConfiguration.get_floor_count(logger)
