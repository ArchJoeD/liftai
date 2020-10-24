import os
import pickle
from abc import ABC, abstractmethod
from datetime import datetime
from sqlalchemy.sql import text

from utilities import common_constants
from utilities.device_configuration import DeviceConfiguration
from utilities.db_utilities import engine, Session


class StoppageState:
    OK = 0
    STOPPED_C90 = 90
    STOPPED_C95 = 95
    STOPPED_C99 = 99


class StoppageProcessor(ABC):
    name = 'stoppage_processor'
    parms_table_name = None
    engine = engine

    def __init__(self, logger):
        self.logger = logger

        self.session = Session()

        self.storage_last_state = self._get_last_state_fname()
        self.storage_last_trip = self._get_last_trip_fname()
        self.storage_current_stopped_time = self._get_current_stopped_time_fname()

        # Restore state, stoppage id, stoppage time, last trip, etc. from disk, if they exist.
        self._restore_state(StoppageState.OK)

        self._restore_current_stopped_timestamp()

        self._restore_trip(None)


    def _restore_state(self, default):
        self.last_state = self._restore_value(self.storage_last_state, default)

    def _restore_trip(self, default):
        self.last_trip = self._restore_value(self.storage_last_trip, default)

    def _restore_current_stopped_timestamp(self):
        last_state_not_okay = self.last_state != StoppageState.OK
        if last_state_not_okay:
            curr_stopped_time = self._restore_value(self.storage_current_stopped_time, datetime.now())
            if curr_stopped_time:
                self.current_stopped_timestamp = curr_stopped_time
            else:
                self.logger.error("No value for current stopped time: We had no saved value")
        else:
            self.logger.debug("No value for current stopped time: The status was OK")

    def _restore_value(self, storage_location, default):
        return_value = default
        if os.path.isfile(storage_location) and os.stat(storage_location).st_size != 0:
            for _ in range(0,3):                    # EN-680 fix
                try:
                    with open(storage_location, 'rb') as f:
                        return_value = pickle.load(f)
                        self.logger.debug("Loaded {0} as {1}".format(storage_location, self.last_trip))
                        break
                except Exception as ex:
                    self.logger.debug("Failed fetching from file {0}: {1}".format(storage_location, str(ex)))
        return return_value

    def _get_threshold_config(self):
        config_data = DeviceConfiguration.get_config_data()

        return config_data.get(common_constants.CONFIG_STOPPAGE_THRESHOLD, common_constants.CONFIG_STOPPAGE_DEFAULT)

    def _update_state(self, new_state):
        self.last_state = new_state
        try:
            with open(self.storage_last_state, 'wb') as f:
                pickle.dump(new_state, f)
                self.logger.debug("Saved state to disk as {0}".format(new_state))
        except Exception as ex:
            self.logger.error("Exception writing last state to permanent storage: " + str(ex))

    def _update_current_stopped_timestamp(self, ts):
        self.current_stopped_timestamp = ts
        try:
            with open(self.storage_current_stopped_time, 'wb') as f:
                pickle.dump(ts, f)
                self.logger.debug("Saved current stopped timestamp to disk as {0}".format(ts))
        except Exception as ex:
            self.logger.error("Exception processing stoppage (update_stopped_timestamp)", ex)

    def _is_trip_happening(self):
        if self.last_trip is None:
            return self._has_trip_ever_started()
        return self._has_trip_started_after_time(self.last_trip)

    def _has_trip_ever_started(self):
        # Begin at prehistoric times and see if any trips have ever happened.
        time = datetime.strptime('2000-01-01 00:00:00', '%Y-%m-%d %H:%M:%S')
        return self._has_trip_started_after_time(time)

    def _has_trip_started_after_time(self, time):
        new_time = time
        if isinstance(time, datetime):
            new_time = int(time.strftime("%s"))

        with engine.connect() as con:
            try:
                query_str = text("SELECT count(*) AS trip_count "
                                 "FROM trips "
                                 "WHERE start_time > to_timestamp(:time)")
                rs = con.execute(query_str, time=new_time)
                r = rs.fetchone()

                return r['trip_count'] > 0 if r is not None else False

            except Exception as ex:
                msg = "{}: Exception happened in _is_trip_started_after_time: {}".format(self.name, ex)
                self.logger.error(msg)
                raise Exception(msg)
        return False

    def _set_last_trip(self, last_trip):
        self.last_trip = last_trip
        try:
            with open(self.storage_last_trip, 'wb') as f:
                pickle.dump(self.last_trip, f)
                self.logger.debug("Saved last_trip timestamp to disk as {0}".format(last_trip))
        except Exception as ex:
            self.logger.error("{}: Exception writing last_trip to permanent storage: {}".format(self.name, ex))

    def _is_accelerometer_working(self, con):
        seconds_since_last_accel_value = con.execute("SELECT EXTRACT(EPOCH FROM NOW() - timestamp) "
                    "FROM accelerometer_data ORDER BY id DESC LIMIT 1;").fetchone()[0]
        # Set the threshold fairly high to avoid cases where the accel app is merely restarting.
        return seconds_since_last_accel_value < 180

    def _get_last_state_fname(self):
        return os.path.join(common_constants.STORAGE_FOLDER,
                            '{}_last_state.pkl'.format(self.name))

    def _get_last_trip_fname(self):
        return os.path.join(common_constants.STORAGE_FOLDER,
                            '{}_last_trip.pkl'.format(self.name))

    def _get_current_stopped_time_fname(self):
        return os.path.join(common_constants.STORAGE_FOLDER,
                            '{}_current_stopped_time.pkl'.format(self.name))

    def _log_event(self, source, event_type, event_subtype, confidence, occurred_at, detected_at):
        self.logger.debug("Creating event from {0} of type {1} and subtype {2} with confidence {3}, occurred at {4}, "
                      "detected at {5}".format(source, event_type, event_subtype, confidence, occurred_at, detected_at))
        with engine.connect() as con:
            trans = con.begin()
            try:
                query_str = text("INSERT INTO events(occurred_at, detected_at, source, event_type,"
                                 "                   event_subtype, confidence)"
                                 "     VALUES (:occurred, :detected, :source,"
                                 "             :et, :est, :conf)")
                con.execute(query_str, occurred=occurred_at, detected=detected_at, source=source,
                            et=event_type, est=event_subtype, conf=confidence)
                trans.commit()
            except Exception as ex:
                trans.rollback()
                msg = "{}: Exception, failed to create event in superclass _log_event in class {}".format(self.name, ex)
                self.logger.error(msg)
                raise Exception(msg)


    def _log_resumed_event(self, subtype):
        return self._log_stoppage_event(0, subtype)

    def _log_stoppage_event(self, probability, subtype):
        detected_at = datetime.now()
        occurred_at = detected_at
        if self.last_trip and probability > 0:
            self.logger.debug("_log_stoppage_event is changing occurred_at from {0} to {1}".format(occurred_at, self.last_trip))
            occurred_at = self.last_trip
        else:
            self.logger.debug("_log_stoppage_event is using current time for detected_at and occurred_at, {0}".format(detected_at))
        return self._log_event(self.name,
                        common_constants.EVENT_TYPE_SHUTDOWN,
                        subtype,
                        probability,
                        occurred_at,
                        detected_at)

    @abstractmethod
    def run(self):
        pass
