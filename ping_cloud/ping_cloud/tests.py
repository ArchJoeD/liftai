import os
import unittest
from datetime import datetime
from time import sleep

from freezegun import freeze_time

import ping_cloud.constants as constants
import utilities.common_constants as common_constants
from ping_cloud.ping import PingCloud
from utilities.db_utilities import engine
from utilities.serial_number import SerialNumber
from utilities.test_utilities import TestUtilities


frozen_time = "2015-10-21T06:15:00+00:00"


class PingTesting(unittest.TestCase):
    testutils = TestUtilities()

    @classmethod
    def setUpClass(cls):
        print("Setting up for testing")

    def _delete_data(self):
        self.testutils.delete_trips()
        with engine.connect() as con:
            con.execute("DELETE FROM trips")
            con.execute("DELETE FROM data_to_send")

    def setUp(self):
        self._delete_data()
        config = {"type": "elevator", common_constants.CONFIG_STOPPAGE_THRESHOLD: "DF"}
        self.testutils.set_config(config)
        os.system("echo a1f2e3d4b9c_1 > {0}".format(common_constants.HOSTNAME_FILE))

    def tearDown(self):
        self._delete_data()
        os.system("rm {0}".format(common_constants.HOSTNAME_FILE))

    def test_random_seconds(self):
        pc = PingCloud()
        random_count = 0
        random_max = -10000
        random_min = 10000
        sample_size = 1000
        for _ in range(sample_size):
            random_number = pc.get_random_seconds()
            random_count += random_number
            random_max = max(random_max, random_number)
            random_min = min(random_min, random_number)
        self.assertTrue( abs(random_count/sample_size - constants.DEFAULT_SECONDS_BETWEEN_PINGS) < 100,
                         "Random number average is bad, {0}".format(random_count/sample_size))
        self.assertTrue( random_max <= constants.DEFAULT_SECONDS_BETWEEN_PINGS,
                        "Random numbers go above range, {0}".format(random_max))
        self.assertTrue(random_min >= 0,
                        "Random numbers go below range, {0}".format(random_max))

    def test_last_trip_id(self):
        pc = PingCloud()
        self.assertEqual(pc.last_trip_id, -1)
        self.testutils.insert_trip()
        last_trip = self.testutils.get_last_trip()
        pc._get_ping_payload()
        self.assertEqual(last_trip["id"], pc.last_trip_id)

    def test_ping_id(self):
        pc = PingCloud()
        ping_payload = pc._get_ping_payload()
        self.assertEqual(ping_payload['id'], SerialNumber.get())

    def test_trip_count(self):
        pc = PingCloud()
        self.testutils.insert_trip(starts_at=datetime.now(), ends_at= datetime.now())
        pc.send_ping()
        ping_payload = pc._get_ping_payload()
        self.assertEqual(ping_payload['ping_trips'], 0)
        self.testutils.insert_trip(starts_at=datetime.now(), ends_at= datetime.now())
        self.testutils.insert_trip(starts_at=datetime.now(), ends_at=datetime.now())
        self.testutils.insert_trip(starts_at=datetime.now(), ends_at=datetime.now())
        ping_payload = pc._get_ping_payload()
        self.assertEqual(ping_payload['ping_trips'], 3)
        self.testutils.insert_trip(starts_at=datetime.now(), ends_at=datetime.now())
        ping_payload = pc._get_ping_payload()
        self.assertEqual(ping_payload['ping_trips'], 1)
        self.testutils.insert_trip(starts_at=datetime.now(), ends_at=datetime.now())
        pc_after_reboot = PingCloud()
        payload_after_reboot = pc_after_reboot._get_ping_payload()
        self.assertEqual(payload_after_reboot['ping_trips'], 0, "First ping after a reboot should have zero trips, always")

    def test_door_estimate_method(self):
        last_estimate = 0
        increment = 31
        zero_door_est = PingCloud._get_door_estimate_from_trips(0)
        self.assertEqual(zero_door_est, 0, "with no trips, door estimate should be zero")
        for trips in range(1, 20000, increment):
            door_est = PingCloud._get_door_estimate_from_trips(trips)
            self.assertGreater(door_est, trips, "door estimate must be larger than trips")
            self.assertGreater(door_est, last_estimate, "door estimate must increase with multiple trips")
            self.assertLess( last_estimate - door_est, increment*4, "door estimate must not make big jumps")
            last_estimate = door_est

    @freeze_time(frozen_time)
    def test_ping(self):
        pc = PingCloud()
        self.testutils.insert_trip(starts_at=datetime.now(), ends_at=datetime.now())
        pc.send_ping()
        with engine.connect() as con:
            row = con.execute("SELECT payload, flag, resend FROM data_to_send ORDER BY id DESC LIMIT 1").fetchone()
        payload = row["payload"]
        self.assertEqual(payload["ping_trips"], 0, "never report trips on the first ping")
        self.assertEqual(payload["ping_doors"], 0, "if we don't report trips on first ping, don't report doors")
        sleep(0.1)
        self.testutils.insert_trip(starts_at=datetime.now(), ends_at=datetime.now())
        pc.send_ping()
        with engine.connect() as con:
            row = con.execute("SELECT payload, flag, resend FROM data_to_send ORDER BY id DESC LIMIT 1").fetchone()
        self.assertFalse(row["resend"])
        self.assertFalse(row["flag"])
        payload = row["payload"]
        self.assertEqual(payload["id"], SerialNumber.get())
        self.assertEqual(payload["date"], frozen_time)
        self.assertEqual(payload["type"], common_constants.MESSAGE_TYPE_PING)
        self.assertEqual(payload["ping_trips"], 1)
        self.assertGreaterEqual(payload["ping_doors"], 2)
        self.assertLess(payload["ping_doors"], 3)

if __name__ == "__main__":
    unittest.main()

