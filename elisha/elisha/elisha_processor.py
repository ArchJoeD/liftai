#! /usr/bin/python3

import os
import pickle
import logging

import elisha.shutdown as shutdown
import elisha.vibration as vibration
import elisha.anomaly as anomaly
import elisha.constants as constants
import utilities.common_constants as common_constants
from utilities.db_utilities import Event

logger = logging.getLogger(__name__)


class ElishaProcessor:
    test_tool_no_more_events = None        # Allows test methods to know when all events are definitely processed.
    last_event_id = None
    state_info = None

    def __init__(self):
        self.shutdown = shutdown.Shutdown()
        self.vibration = vibration.Vibration()
        self.anomaly = anomaly.Anomaly()

    def setup(self, session):
        self._setup_switch_dictionary()
        self.last_event_id = -1
        self.test_tool_no_more_events = False

        # Start out with default values and overwrite them with whatever is in storage.
        self.storage_last_event = os.path.join(
            common_constants.STORAGE_FOLDER, "elisha_last_event.pkl"
        )
        self.storage_state_info = os.path.join(
            common_constants.STORAGE_FOLDER, "elisha_state_info.pkl"
        )
        self._restore_last_event_id(session)
        self._restore_state_info()

    def _setup_switch_dictionary(self):
        self.switch = {
            common_constants.EVENT_TYPE_SHUTDOWN: self.shutdown.process_event,
            common_constants.EVENT_TYPE_VIBRATION: self.vibration.process_event,
            common_constants.EVENT_TYPE_ANOMALY: self.anomaly.process_event,
        }

    def process_data(self, session):
        events = self._get_batch_of_data(session)
        last_event_id = self.last_event_id
        try:
            self.test_tool_no_more_events = True
            for event in events:
                last_event_id = (
                    event.id
                )  # Keep track of the last id we tried to process.
                self._process_next_event(session, event)
                self.test_tool_no_more_events = False
        except Exception as ex:
            logger.error(
                "Exception processing a batch of data at event id {0}, {1}".format(
                    last_event_id, str(ex)
                )
            )
            self._log_state_info()
            self.test_tool_no_more_events = False
            raise
        finally:
            # Don't process this event again if this causes an exception (but do process it if we had a power failure).
            self._save_last_event_id(last_event_id)

    def _get_batch_of_data(self, session):
        return (
            session.query(Event)
            .filter(Event.id > self.last_event_id)
            .order_by(Event.id.asc())
            .limit(constants.PROCESS_BATCH_SIZE)
            .all()
        )

    def _process_next_event(self, session, event):
        state_info = self.switch.get(event.event_type, self._unknown_event_type)(
            session, event, self.state_info
        )
        if state_info is not None:
            self._log_state_info()
            self._save_state_info(state_info)
        else:
            logger.error(
                "All event processors need to return the updated state_info value, got nothing back"
            )

    def _unknown_event_type(self, session, event, state_info):
        logger.debug(
            "Unknown event: {0}, {1}, state_info={2}".format(
                event.event_type, event.event_subtype, state_info
            )
        )
        return state_info

    def _log_state_info(self):
        logger.debug("state info: {0}".format(str(self.state_info)))

    def _save_last_event_id(self, id):
        self.last_event_id = id
        with open(self.storage_last_event, "wb") as f:
            pickle.dump(id, f)

    def _save_state_info(self, state_info):
        self.state_info = state_info
        with open(self.storage_state_info, "wb") as f:
            pickle.dump(state_info, f)

    def _restore_last_event_id(self, session):
        success = False
        if (
            os.path.isfile(self.storage_last_event)
            and os.stat(self.storage_last_event).st_size != 0
        ):
            for i in range(0, 3):  # EN-680 fix
                try:
                    with open(self.storage_last_event, "rb") as f:
                        self.last_event_id = pickle.load(f)
                        logger.debug(
                            "restoring last event id: {0}".format(self.last_event_id)
                        )
                        success = True
                        break
                except Exception as ex:
                    logger.error(
                        "Exception getting pickle last_event_id from storage on pass {0}: {1}".format(
                            i, str(ex)
                        )
                    )
        else:
            logger.info(
                "No storage info or it's corrupted, so we write the initial default out to storage."
            )
        if success == False:
            last_event = session.query(Event.id).order_by(Event.id.desc()).first()
            self.last_event_id = last_event.id if last_event else -1

    def _restore_state_info(self):
        success = False
        if (
            os.path.isfile(self.storage_state_info)
            and os.stat(self.storage_state_info).st_size != 0
        ):
            for i in range(0, 3):  # EN-680 fix
                try:
                    with open(self.storage_state_info, "rb") as f:
                        self.state_info = pickle.load(f)
                        logger.debug(
                            "restoring state_info: {0}".format(self.state_info)
                        )
                        success = True
                        break
                except Exception as ex:
                    logger.info(
                        "Exception getting pickle last_event_id from storage (normal for 1st run) on pass {0}, writing defaults out: {1}".format(
                            i, ex
                        )
                    )
        else:
            # No storage information (yet), so we write the initial defaults out to storage.
            self.state_info = {}
            self.state_info.update(self.shutdown.get_default_state())
            self.state_info.update(self.vibration.get_default_state())
            self.state_info.update(self.anomaly.get_default_state())
            logger.info(
                "No storage for state_info yet, writing default to storage: {0}".format(
                    self.state_info
                )
            )
            with open(self.storage_state_info, "wb") as f:
                pickle.dump(self.state_info, f)
                success = True
        if success == False:
            raise Exception("Failed to load state_info from file")
