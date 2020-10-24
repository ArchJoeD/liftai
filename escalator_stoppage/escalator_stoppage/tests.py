import json
import os
import unittest
import time

from sqlalchemy.sql import text

from accelerometer.models import Base
from utilities.stoppage_processor import StoppageState
from escalator_stoppage.processor import EscalatorStoppageProcessor
from utilities import common_constants
from utilities.db_utilities import engine


Base.metadata.create_all(engine)

XY_THRESHOLD = 16000
Z_THRESHOLD = 12000
SAMPLES_NEEDED = 2600


class TestEscalatorStoppage(unittest.TestCase):
    def _insert_running_data(self, over=False):
        time.sleep(0.1)  # Short delay to keep timestamps ahead of earlier data.
        with engine.connect() as con:
            qs = text(
                "INSERT INTO accelerometer_data (timestamp, z_data)"
                "VALUES (NOW(), :z)"
            )
            z = Z_THRESHOLD - 5
            if over:
                z = Z_THRESHOLD + 5
            con.execute(qs, z=[z for _ in range(SAMPLES_NEEDED)])

    def _delete_vibration_data(self):
        with engine.connect() as con:
            con.execute("TRUNCATE escalator_vibration;")

    def _verify_averages(self, on=True):
        z = Z_THRESHOLD
        with engine.connect() as con:
            avg = con.execute(
                "SELECT * FROM escalator_vibration ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        if on:
            self.assertTrue(avg["position"] >= z)
        else:
            self.assertTrue(avg["position"] < z)

    @classmethod
    def setUpClass(cls):
        print("Setting up for testing (NOTE: THESE ARE DESTRUCTIVE TESTS!!!)...")
        os.system("sudo systemctl stop accelerometer.service")

    @classmethod
    def tearDownClass(cls):
        os.system("sudo systemctl start accelerometer.service")

    def setUp(self):
        with engine.connect() as con:
            con.execute("TRUNCATE accelerometer_data;")
            con.execute("TRUNCATE escalator_vibration;")
            con.execute("TRUNCATE events;")
            con.execute("TRUNCATE problems;")
        with open(common_constants.CONFIG_FILE_NAME, "w") as cf:
            json.dump({"type": "escalator"}, cf)

    def tearDown(self):
        with engine.connect() as con:
            con.execute("TRUNCATE accelerometer_data;")
            con.execute("TRUNCATE escalator_vibration;")
            con.execute("TRUNCATE events;")
            con.execute("TRUNCATE problems;")

        for item in os.listdir(common_constants.STORAGE_FOLDER):
            if item.endswith(".pkl"):
                os.remove(os.path.join(common_constants.STORAGE_FOLDER, item))

    def test_escalator_on(self):
        self._insert_running_data(over=True)
        proc = EscalatorStoppageProcessor()
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.OK)

    def test_escalator_off(self):
        self._insert_running_data(over=False)
        proc = EscalatorStoppageProcessor()
        proc.run()
        self.assertTrue(proc.last_state == StoppageState.STOPPED_C99)

    def test_escalator_on_and_off(self):
        for i in range(3):
            print("Starting iteration {0} of escalator on and off test".format(i))
            self._insert_running_data(over=False)
            self._delete_vibration_data()
            proc = EscalatorStoppageProcessor()
            proc.run()
            self.assertTrue(proc.last_state == StoppageState.STOPPED_C99)
            self._insert_running_data(over=True)
            self._delete_vibration_data()
            proc = EscalatorStoppageProcessor()
            proc.run()
            self.assertTrue(proc.last_state == StoppageState.OK)


if __name__ == "__main__":
    unittest.main()
