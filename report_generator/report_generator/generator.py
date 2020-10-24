import logging
import os
import pickle
from datetime import datetime, timedelta

import pytz

from report_generator import constants
from report_generator.status_data import StatusData
from utilities import common_constants
from utilities.db_utilities import DataToSend


logger = logging.getLogger(__name__)


class RGenerator:
    storage_file_name = None
    name_last_hourly_report = None
    saved_values = None

    def __init__(self):
        self.storage_file_name = os.path.join(
            common_constants.STORAGE_FOLDER, constants.STORAGE_FILE_NAME
        )
        self.name_last_hourly_report = "lastHourlyReport"
        self.saved_values = {}
        self._restore_last_hourly_report_time()

    # NOTE: For these algorithms to determine whether it's time to send a report, it needs to work even if the device
    #     has been down for a long time.  So if the device wakes up and it's 5 days overdue, we still want it to get
    #     sent.
    #
    # The timestamps on reports are the beginning time.

    def _is_time_for_hourly_report(self):
        last_report_time_utc = self.saved_values[self.name_last_hourly_report]
        return last_report_time_utc < pytz.utc.localize(datetime.utcnow()).replace(
            minute=0, second=0, microsecond=0
        ) - timedelta(hours=1)

    def _send_report(
        self,
        session,
        report_payload,
        report_time_utc=pytz.utc.localize(datetime.utcnow()),
        endpoint=common_constants.REPORT_ENDPOINT,
    ):
        event = DataToSend(
            timestamp=report_time_utc,
            endpoint=endpoint,
            payload=report_payload,
            flag=False,
            resend=True,
        )
        DataToSend.track_event(session, event)

    def generate_reports(self, session):
        if self._is_time_for_hourly_report():
            last_report_time = self.saved_values[self.name_last_hourly_report]
            # Make sure we're at the start of the hour with the .replace() method.
            report_starting_time_utc = (last_report_time + timedelta(hours=1)).replace(
                minute=0, second=0, microsecond=0
            )
            payload = StatusData.get_hourly_report_payload(
                session, report_starting_time_utc
            )
            if payload is not None:
                self._send_report(
                    session,
                    payload,
                    report_time_utc=pytz.utc.localize(datetime.utcnow()),
                )
                self._save_last_hourly_report_time(report_starting_time_utc)
            else:
                logger.error("generate_reports got None back for the report payload")

    def _save_last_hourly_report_time(self, timestamp):
        self._save_value(self.name_last_hourly_report, timestamp)

    def _restore_last_hourly_report_time(self):
        self._restore_value(
            self.name_last_hourly_report,
            pytz.utc.localize(datetime.utcnow()).replace(
                minute=0, second=0, microsecond=0
            )
            - timedelta(hours=1),
        )
        # Handle migrations from older unaware values.
        if self.saved_values[self.name_last_hourly_report].tzinfo is None:
            self._save_value(
                self.name_last_hourly_report,
                pytz.utc.localize(self.saved_values[self.name_last_hourly_report]),
            )

    def _save_value(self, location_name, value):
        """
        Save the value from the dictionary of saved values into storage.
        """
        self.saved_values[location_name] = value
        with open(self.storage_file_name, "wb") as f:
            pickle.dump(self.saved_values, f)

    def _restore_value(self, location_name, default):
        self.saved_values[location_name] = default
        if (
            os.path.isfile(self.storage_file_name)
            and os.stat(self.storage_file_name).st_size != 0
        ):
            try:
                with open(self.storage_file_name, "rb") as f:
                    restored_values = pickle.load(f)
                    if location_name in restored_values:
                        self.saved_values[location_name] = restored_values[
                            location_name
                        ]
                        logger.debug(
                            "restoring {0}, value is {1}".format(
                                location_name, restored_values[location_name]
                            )
                        )
                    else:
                        logger.debug(
                            "trying to restore {0} but it doesn't exist".format(
                                location_name
                            )
                        )
            except Exception as ex:
                logger.info(
                    "Exception getting pickle {0} from storage: {1}".format(
                        location_name, str(ex)
                    )
                )
        else:
            self._save_value(location_name, self.saved_values[location_name])

    def delete_storage(self):
        """
        This should only be used for testing
        """
        if os.path.isfile(self.storage_file_name):
            os.remove(self.storage_file_name)
