#! /usr/bin/python3
import logging
import random
import re
from datetime import datetime

import pytz

import ping_cloud.constants as constants
import utilities.common_constants as common_constants
from utilities.serial_number import SerialNumber
from utilities.db_utilities import session_scope, DataToSend


logger = logging.getLogger(__name__)


class PingCloud:
    def __init__(self):
        unique_hex_string = re.sub('_', '', SerialNumber.get())
        random.seed(int(unique_hex_string, 16))
        self.last_trip_id = -1

    def send_ping(self):
        endpoint = common_constants.PING_ENDPOINT
        payload = self._get_ping_payload()

        with session_scope() as session:
            ping = DataToSend(
                endpoint=endpoint,
                payload=payload,
                flag=False
            )
            DataToSend.track_event(session, ping)


    def _get_ping_payload(self):
        timestamp = datetime.utcnow().replace(microsecond=0)
        payload = {
            "id": SerialNumber.get(),
            "type": common_constants.MESSAGE_TYPE_PING,
            "date": pytz.utc.localize(timestamp).isoformat(),
        }

        with session_scope() as session:
            row = session.execute("SELECT max(id) as last_id, count(*) as cnt "
                              "FROM trips WHERE id > %s" % self.last_trip_id).first()

            if self.last_trip_id >= 0:
                payload["ping_trips"] = row["cnt"]
                payload["ping_doors"] = PingCloud._get_door_estimate_from_trips(row["cnt"])
            else:
                # The first time after a reboot we send 0 trips
                payload["ping_trips"] = 0
                payload["ping_doors"] = 0

            if row["last_id"] is not None:
                self.last_trip_id = row["last_id"]

        return payload


    def get_sleep_seconds(self):
        # In the future, we will have adaptive ping times based on trip traffic and other factors.
        return constants.DEFAULT_SECONDS_BETWEEN_PINGS

    def get_random_seconds(self):
        # Spread out the pings going to the cloud so early pings after routine reboots aren't closely synchronized.
        return random.randint(0, constants.DEFAULT_SECONDS_BETWEEN_PINGS)

    @staticmethod
    def _get_door_estimate_from_trips(trips):
        """
        This is a temporary method until we have a reasonably reliable door detection mechanism.
        For now, we're just estimating the number of door cycles based on trips.
        :param trips: The number of actual trips that we've detected.
        :return: An estimate of how many door cycles have happened, based on the number of trips.
        """
        return int(round( trips*2.1 + max(trips-1000, 0), 0))
