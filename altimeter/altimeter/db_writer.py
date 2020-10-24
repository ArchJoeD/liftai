from queue import Queue, Empty
from threading import Thread, Event

from utilities.db_utilities import session_scope


class AltimDbWriter(Thread):
    def __init__(self):
        self._queue = Queue()
        self._event = Event()
        super().__init__()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self._event.set()
        self.join()

    def write_record(self, altim_record):
        self._queue.put_nowait(altim_record)

    def run(self):
        with session_scope() as session:
            while not self._event.is_set():
                try:
                    record = self._queue.get(timeout=1)
                    session.add(record)
                    session.commit()
                except Empty:
                    pass
