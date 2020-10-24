from queue import Queue, Empty
from threading import Thread, Event

from accelerometer.accel import SMBusAccelerometer
from accelerometer.constants import GRAVITY_UPDATE_FREQUENCY
from accelerometer.models import AccelerometerData
from utilities.db_utilities import session_scope


class AccelDbWriter(Thread):
    def __init__(self, accelerometer: SMBusAccelerometer):
        self._queue = Queue()
        self._event = Event()
        self._accelerometer = accelerometer
        super().__init__()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self._event.set()
        self.join()

    def write_records(self, accel_records):
        self._queue.put_nowait(accel_records)

    def run(self):
        gravity_update_counter = 0

        with session_scope() as session:
            while not self._event.is_set():
                try:
                    records = self._queue.get(timeout=1)
                    session.bulk_insert_mappings(AccelerometerData, records)

                    # Every now and then recalculate gravity.
                    gravity_update_counter += 1
                    if gravity_update_counter > GRAVITY_UPDATE_FREQUENCY:
                        self._accelerometer.update_gravity(session)
                        gravity_update_counter = 0

                    session.commit()
                except Empty:
                    pass
