#!/usr/bin/env python3
#  Python program to detect all elevator activity and send as notifications.  Shut off after timeout.

import logging
from datetime import datetime, timedelta
from itertools import chain

from pytz import utc
from sqlalchemy.orm import load_only

import roawatch.constants as roa_constants

from notifications.notifications import Notification, NotificationTopic
from utilities.db_utilities import get_landing_floor_for_trip, Trip
from utilities.func_utilities import pairwise
from utilities.floor_detection import can_use_floor_data


logger = logging.getLogger(__name__)


class Watcher:
    n = Notification()

    def __init__(self):
        self.last_trip_id = -1
        self.starting_time = datetime.now()
        self._advance_heartbeat_expiration_time()

    def reset(self, session):
        self._advance_heartbeat_expiration_time()

        # Get the last trip up to date before starting to watch for trips.
        trip = session.query(Trip).order_by(Trip.id.desc()).first()

        if trip:
            self.last_trip_id = trip.id

    def check_for_trips(self, session):
        """
        Check for trips looks for trips that have happened since the watcher started
        that it has not yet processed.

        When a trip is found it updates the last_trip_id, sends a notification
        with information about the trip, and resets the heartbeat timeout

        Lastly it updates the heartbeat timeout
        """
        last_and_current_trip_pairs = self._get_last_and_current_trip_pairs(session)
        floor_data_usable = can_use_floor_data(session)

        for last_trip, current_trip in last_and_current_trip_pairs:
            # Delay processing for up to a minute if the ending_floor is missing
            if current_trip.ending_floor is None and (
                datetime.now(utc) - current_trip.end_time
            ) < timedelta(minutes=1):
                break

            self.last_trip_id = current_trip.id
            direction = "up" if current_trip.is_up else "down"
            duration = current_trip.end_time - current_trip.start_time
            start_floor = (
                get_landing_floor_for_trip(session, last_trip)
                if last_trip and floor_data_usable
                else None
            )
            end_floor = (
                get_landing_floor_for_trip(session, current_trip)
                if floor_data_usable
                else None
            )

            self._advance_heartbeat_expiration_time()

            notif_data = {
                "subtype": roa_constants.ROA_SUBTYPE_TRIP,
                "direction": direction,
                "duration": duration.seconds,
                "start_floor": start_floor,
                "end_floor": end_floor,
            }

            self.n.send(
                NotificationTopic.ROA_EVENT,
                notif_data=notif_data,
            )

        self._send_heartbeat_notification_if_expired()

    def _get_last_and_current_trip_pairs(self, session):
        """
        Fetches and returns trips in pairs since the last run

        [(t1, t2), (t2, t3), ...]
        """
        base_trips_query = session.query(Trip).options(
            load_only(
                Trip.id, Trip.is_up, Trip.start_time, Trip.end_time, Trip.ending_floor,
            )
        )

        trips_since_last_run = (
            base_trips_query.filter(
                Trip.id > self.last_trip_id, Trip.start_time > self.starting_time
            )
            .order_by(Trip.id)
            .all()
        )

        if not len(trips_since_last_run):
            return []

        previous_trip_since_last_run = (
            base_trips_query.filter(Trip.id < trips_since_last_run[0].id)
            .order_by(Trip.id.desc())
            .first()
        )

        return pairwise(chain([previous_trip_since_last_run], trips_since_last_run))

    def _advance_heartbeat_expiration_time(self):
        self.heartbeat_time = datetime.now() + timedelta(
            minutes=roa_constants.MINUTES_BETWEEN_HEARTBEATS
        )

    def _send_heartbeat_notification_if_expired(self):
        if datetime.now() > self.heartbeat_time:
            logger.info(
                "No activity for {0} minutes, sending heartbeat notification".format(
                    roa_constants.MINUTES_BETWEEN_HEARTBEATS
                )
            )
            self._advance_heartbeat_expiration_time()

            self.n.send(
                NotificationTopic.ROA_EVENT,
                notif_data={
                    "subtype": roa_constants.ROA_SUBTYPE_HEARTBEAT,
                    "heartbeat_interval": roa_constants.MINUTES_BETWEEN_HEARTBEATS,
                },
            )
