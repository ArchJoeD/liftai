import datetime

from sqlalchemy import Column, Float, BigInteger, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

from accelerometer.constants import GRAVITY_UPDATE_MAX_ACCEL


Base = declarative_base()


class AccelerometerData(Base):
    __tablename__ = "accelerometer_data"
    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    x_data = Column("x_data", Float)
    y_data = Column("y_data", Float)
    z_data = Column("z_data", Float)
    # WARNING: There's already an index created for the timestamp column in global_install.sql

    def __init__(self, timestamp, x_data, y_data, z_data):
        self.timestamp = timestamp
        self.x_data = x_data
        self.y_data = y_data
        self.z_data = z_data  # This has gravity removed

    @classmethod
    def get_gravity_info_since(cls, session, since):
        return (
            session.query(
                (func.sum(cls.z_data) / func.count(cls.z_data)).label("gravity"),
                func.count(cls.z_data).label("sample_points"),
            )
            .filter(
                func.abs(cls.z_data) < GRAVITY_UPDATE_MAX_ACCEL,
                cls.timestamp > since,
            )
            .first()
        )
