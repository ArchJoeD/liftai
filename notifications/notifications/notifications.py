#!/usr/bin/env python3
#  Python program to create a notification and add it to the data_to_send table.
import logging
from datetime import datetime
from enum import Enum, unique

import pytz

from utilities.db_utilities import session_scope, DataToSend, Trip
from utilities.serial_number import SerialNumber


logger = logging.getLogger("notifications")


class InvalidNotificationTopic(Exception):
    def __init__(self, value):
        super().__init__(
            "{value} is not a valid NotificationTopic".format(value=value)
        )


@unique
class NotificationTopic(Enum):
    RESTART_FROM_POWER_LOSS = 0
    POWER_EVENT = 1
    SHUTDOWN_CONFIDENCE = 2
    ROA_EVENT = 3
    FLOOR_MAP_CREATED = 4

    @staticmethod
    def topic_to_string(topic):
        if topic == NotificationTopic.RESTART_FROM_POWER_LOSS:
            return "restart_from_power_loss"

        if topic == NotificationTopic.POWER_EVENT:
            return "power_event"

        if topic == NotificationTopic.SHUTDOWN_CONFIDENCE:
            return "shutdown_confidence"

        if topic == NotificationTopic.ROA_EVENT:
            return "roa_event"

        if topic == NotificationTopic.FLOOR_MAP_CREATED:
            return "floor_map_created"

        raise InvalidNotificationTopic(topic)


class Notification:
    @staticmethod
    def send(
        topic_enum,
        notif_data=None,
        include_last_trip=False,
    ):
        timestamp = datetime.utcnow().replace(microsecond=0)
        notification_type = NotificationTopic.topic_to_string(topic_enum)

        payload = {
            "id": SerialNumber.get(),
            "type": notification_type,
            "date": pytz.utc.localize(timestamp).isoformat(),
            **(notif_data or {}),
        }

        with session_scope() as session:
            if include_last_trip:
                last_trip_info = Notification._get_last_trip_info(session)
                if last_trip_info:
                    payload.update(last_trip_info)

            try:
                notification_data = DataToSend(
                    timestamp=timestamp,
                    payload=payload,
                    flag=False,
                    resend=True,
                )
                DataToSend.track_event(session, notification_data)
            except Exception as e:
                print(e)
                raise e  # Note: Do NOT send system notifications just because an exception happened!

    @staticmethod
    def _get_last_trip_info(session):
        trip_info = None
        try:
            last_trip = session.query(
                Trip.start_time,
                Trip.is_up,
                Trip.duration,
            ).order_by(Trip.id.desc()).first()

            if last_trip:
                trip_info = {
                    "last_trip_start_time": last_trip.start_time.replace(microsecond=0).isoformat(),
                    "last_trip_direction": "up" if last_trip.is_up else "down",
                    "last_trip_duration": int(last_trip.duration.total_seconds()),
                }
        except Exception:
            logger.error("Failed to get last trip", exc_info=True)
        return trip_info
