from contextlib import contextmanager
from datetime import datetime, timedelta

import pytz
from sqlalchemy import (
    ARRAY,
    Boolean,
    create_engine,
    Column,
    Integer,
    Numeric,
    Float,
    String,
    types,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION
from sqlalchemy.dialects.postgresql.json import JSON, JSONB
from sqlalchemy.orm import sessionmaker, load_only
from sqlalchemy.sql import func

from utilities import common_constants


engine = create_engine(common_constants.DB_CONNECTION)
Session = sessionmaker(bind=engine)


@contextmanager
def session_scope():
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class UTCDateTime(types.TypeDecorator):

    impl = types.DateTime

    def process_bind_param(self, value, engine):
        return value

    def process_result_value(self, value, engine):
        if value is not None:
            return value.replace(tzinfo=pytz.utc)


Base = declarative_base()


class Problem(Base):
    __tablename__ = "problems"

    id = Column(Integer, primary_key=True)
    created_at = Column(UTCDateTime)
    updated_at = Column(UTCDateTime)
    started_at = Column(UTCDateTime)
    ended_at = Column(UTCDateTime)
    problem_type = Column(String)
    problem_subtype = Column(String)
    customer_info = Column(String)
    confidence = Column(Numeric(4, 2))
    events = Column(ARRAY(Integer))
    details = Column(JSONB)
    chart_info = Column(JSONB)


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    event_type = Column(String)
    event_subtype = Column(String)
    detected_at = Column(UTCDateTime)
    occurred_at = Column(UTCDateTime)
    confidence = Column(Numeric(4, 2))
    source = Column(String)
    details = Column(JSONB)
    chart_info = Column(JSONB)


class Audio(Base):
    __tablename__ = "audio"

    id = Column(Integer, primary_key=True)
    timestamp = Column(UTCDateTime)
    nsamples = Column(Integer)
    sum_of_squares = Column(Float)
    fft = Column(JSONB)

    @classmethod
    def get_noise_for_time_period(cls, session, start_time, end_time):
        result = (
            session.query(
                (func.sum(cls.sum_of_squares) / func.sum(cls.nsamples)).label(
                    "mean_squared_amplitude"
                ),
            )
            .filter(cls.timestamp >= start_time)
            .filter(cls.timestamp < end_time)
        ).first()

        return result.mean_squared_amplitude if result else None


class Acceleration(Base):
    __tablename__ = "accelerations"

    id = Column(Integer, primary_key=True)
    start_time = Column(UTCDateTime)
    duration = Column(Integer)  # This is in milliseconds
    magnitude = Column(Integer)
    is_start_of_trip = Column(Boolean)
    is_positive = Column(Boolean)
    vibration_schema = Column(Integer)
    vibration = Column(JSONB)
    audio = Column(JSONB)

    @classmethod
    def init_with_audio(cls, session, *args, **kwargs):
        if ("audio" not in kwargs) and "start_time" in kwargs and "duration" in kwargs:
            noise = Audio.get_noise_for_time_period(
                session,
                start_time=kwargs["start_time"],
                end_time=kwargs["start_time"]
                + timedelta(milliseconds=kwargs["duration"]),
            )
            kwargs["audio"] = {common_constants.AUDIO_NOISE: noise}
        return cls(*args, **kwargs)


class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True)
    start_accel = Column(Integer)
    end_accel = Column(Integer)
    start_time = Column(UTCDateTime)
    end_time = Column(UTCDateTime)
    is_up = Column(Boolean)
    elevation_change = Column(Integer)
    ending_floor = Column(String)
    vibration_schema = Column(Integer)
    vibration = Column(JSONB)
    audio = Column(JSONB)
    elevation_processed = Column(Boolean)
    floor_estimated_error = Column(Integer)
    speed = Column(Float)

    @classmethod
    def init_with_audio(cls, session, *args, **kwargs):
        if (
            ("audio" not in kwargs)
            and "start_accel" in kwargs
            and "end_accel" in kwargs
        ):
            # The coasting time is from starting accel's end time to ending accel's start time
            start_accel = (
                session.query(Acceleration)
                .filter(Acceleration.id == kwargs["start_accel"])
                .first()
            )
            end_accel = (
                session.query(Acceleration)
                .filter(Acceleration.id == kwargs["end_accel"])
                .first()
            )
            start_time = start_accel.start_time
            end_time = end_accel.start_time + timedelta(milliseconds=end_accel.duration)
            if start_time < end_time:
                noise = Audio.get_noise_for_time_period(
                    session,
                    start_time=start_time,
                    end_time=end_time,
                )
                kwargs["audio"] = {common_constants.AUDIO_NOISE: noise}
        return cls(*args, **kwargs)

    @hybrid_property
    def duration(self):
        return self.end_time - self.start_time

    @classmethod
    def filter_trips_after(cls, query, start_dt):
        return query.filter(cls.end_time > start_dt)

    @classmethod
    def filter_trips_with_ending_floor(cls, query):
        return query.filter(cls.ending_floor != None)

    @classmethod
    def get_latest_trip_with_ending_floor(cls, query):
        return (
            cls.filter_trips_with_ending_floor(query)
            .order_by(cls.end_time.desc())
            .first()
        )

    @classmethod
    def get_latest_landing_number(cls, session):
        """
        Returns the latest landing number recorded on the device.

        Important: The caller must call `can_use_floor_data` to make sure the data is sane
        """
        trip = cls.get_latest_trip_with_ending_floor(
            session.query(cls).options(load_only(cls.end_time, cls.ending_floor))
        )

        if not trip:
            return None

        floor_map = FloorMap.get_active_map_for_datetime(session, trip.end_time)

        if not floor_map:
            return None

        return (
            floor_map.floors[trip.ending_floor][
                common_constants.FLOORS_JSON_LANDING_NUM
            ]
            + 1
        )


class FloorMap(Base):
    __tablename__ = "floor_maps"

    id = Column(Integer, primary_key=True)
    start_time = Column(UTCDateTime)
    last_update = Column(UTCDateTime)
    last_elevation = Column(Integer)
    floors = Column(JSONB)

    @classmethod
    def get_lastest_map(cls, session, columns=None):
        columns = columns if columns else [cls]
        return session.query(*columns).order_by(cls.start_time.desc()).first()

    @classmethod
    def get_active_map_for_datetime(cls, session, dt):
        return (
            session.query(cls)
            .filter(cls.start_time <= dt)
            .order_by(cls.start_time.desc())
            .first()
        )

    @property
    def num_floors(self):
        return len(self.floors)


def get_landing_floor_for_trip(session, trip):
    """
    Returns the landing number for the trip.

    Important: The caller must call `can_use_floor_data` to make sure the data is sane
    """
    if trip.ending_floor is None:
        return None

    floor_map = FloorMap.get_active_map_for_datetime(session, trip.start_time)
    if floor_map is None:
        return None

    floor_data = floor_map.floors.get(trip.ending_floor, None)

    return (
        floor_data[common_constants.FLOORS_JSON_LANDING_NUM]
        + common_constants.FLOORS_USER_TRANSLATION  # convert from 0 to 1 based numbering
        if floor_data
        else None
    )


class DataToSend(Base):
    __tablename__ = "data_to_send"

    id = Column(Integer, primary_key=True)
    timestamp = Column(UTCDateTime)
    endpoint = Column(String)
    payload = Column(JSON)
    flag = Column(Boolean)
    resend = Column(Boolean)
    success = Column(Boolean)

    @classmethod
    def track_event(cls, session, event):
        event.timestamp = event.timestamp or pytz.utc.localize(datetime.now()).replace(
            microsecond=0
        )
        event.endpoint = event.endpoint or common_constants.REPORT_ENDPOINT

        session.add(event)


class BankTrip(Base):
    __tablename__ = "bank_trips"

    id = Column(Integer, primary_key=True)
    timestamp = Column(UTCDateTime)
    bank_trips = Column(Integer)
    bank_elevators = Column(Integer)


class RoaWatchRequest(Base):
    __tablename__ = "roa_watch_requests"

    request_time = Column(UTCDateTime, primary_key=True)
    enabled = Column(Boolean)


class AltimeterData(Base):
    __tablename__ = "altimeter_data"

    id = Column(Integer, primary_key=True)
    timestamp = Column(UTCDateTime)
    altitude_x16 = Column(Integer)
    temperature = Column(DOUBLE_PRECISION)
    average_alt = Column(DOUBLE_PRECISION)
