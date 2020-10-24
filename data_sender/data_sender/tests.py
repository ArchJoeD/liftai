import json
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import pytz

from data_sender.datasender import LiftAIDataSender
from utilities import common_constants
from utilities.db_utilities import BankTrip, DataToSend, Session


TEST_REBOOT_INFO = "/tmp/reboot_info"


class MockResponse:
    def __init__(
        self, raise_generic_exception=False, status_code=200, response_text="{}"
    ):
        self.status_code = status_code
        self.response_text = response_text
        self.raise_generic = raise_generic_exception

    def raise_for_status(self):
        if self.raise_generic:
            raise Exception("Mystery Exception!")
        elif self.status_code != 200:
            raise Exception("HTTPError: {}".format(self.status_code))

    @property
    def text(self):
        return self.response_text


def mock_post(raise_generic_exception=False, status_code=200, response_text="{}"):
    def _m(*args, **kwargs):
        return MockResponse(
            raise_generic_exception=raise_generic_exception,
            status_code=status_code,
            response_text=response_text,
        )

    return _m


@patch("data_sender.constants.REBOOT_INFO", TEST_REBOOT_INFO)
@patch("data_sender.constants.SLEEP_BETWEEN_POST_SECONDS", 0)
@patch("data_sender.constants.FAILURE_EXTRA_SLEEP_SECONDS", 0)
class TestDataSender(unittest.TestCase):
    def _insert_data_to_send(self, session, addittionalModelAttrs=None):
        modelAttrs = {
            "timestamp": datetime.now(),
            "endpoint": "devices/notification",
            "payload": {
                "notification": {
                    "type": "car",
                    "text": "This elevator is now moving again",
                }
            },
            "flag": False,
            "resend": True,
            **(addittionalModelAttrs or {})
        }

        data = DataToSend(**modelAttrs)
        session.add(data)
        session.flush()

        return data.id

    def _get_data_to_send_flag(self, session, pk):
        return session.query(DataToSend).filter(DataToSend.id == pk).first().flag

    def _delete_data(self, session):
        self.session.query(DataToSend).delete()
        self.session.query(BankTrip).delete()

    def setUp(self):
        self.session = Session()
        self._delete_data(self.session)

        with open(common_constants.CONFIG_FILE_NAME, "w") as cf:
            json.dump({"type": "elevator"}, cf)

    def tearDown(self):
        try:
            self._delete_data(self.session)
        finally:
            self.session.rollback()
            self.session.close()

        for item in os.listdir(common_constants.STORAGE_FOLDER):
            if item.endswith(".pkl"):
                os.remove(os.path.join(common_constants.STORAGE_FOLDER, item))

    @patch("requests.Session.send", mock_post())
    def test_marks_data_sent(self):
        pk = self._insert_data_to_send(self.session)
        data_sender = LiftAIDataSender({})
        data_sender.send_data(self.session, "http://google.com/")
        ds = self._get_data_to_send_flag(self.session, pk)
        self.assertEqual(ds, True)

    @patch("requests.Session.send", mock_post(status_code=400))
    def test_marks_data_sent_when_fails_and_resend_set(self):
        pk = self._insert_data_to_send(
            self.session,
            {
                "resend": False,
            },
        )
        data_sender = LiftAIDataSender({})
        data_sender.send_data(self.session, "http://google.com/")
        ds = self._get_data_to_send_flag(self.session, pk)
        self.assertEqual(ds, True)

    @patch("requests.Session.send", mock_post(status_code=400))
    def test_doesnt_mark_data_sent_on_bad_http(self):
        pk = self._insert_data_to_send(self.session)
        data_sender = LiftAIDataSender({})
        data_sender.send_data(self.session, "http://google.com/")
        ds = self._get_data_to_send_flag(self.session, pk)
        self.assertEqual(ds, False)

    @patch("requests.Session.send", mock_post(raise_generic_exception=True))
    def test_raises_on_mystery_exception(self):
        self._insert_data_to_send(self.session)
        data_sender = LiftAIDataSender({})

        with self.assertRaises(Exception):
            data_sender.send_data(self.session, "http://google.com/")

    @patch("requests.Session.send", mock_post(response_text=""))
    @patch.object(LiftAIDataSender, "_process_response_commands")
    def test_empty_response_casts_to_blank_object(self, process_response_commands):
        self._insert_data_to_send(self.session)
        data_sender = LiftAIDataSender({})
        data_sender.send_data(self.session, "http://google.com/")

        self.assertIsNotNone(process_response_commands.call_args)
        args, _ = process_response_commands.call_args
        data = args[1]
        self.assertEqual(data, {})

    @patch("requests.Session.send", mock_post(response_text=None))
    @patch.object(LiftAIDataSender, "_process_response_commands")
    def test_none_response_casts_to_blank_object(self, process_response_commands):
        self._insert_data_to_send(self.session)
        data_sender = LiftAIDataSender({})
        data_sender.send_data(self.session, "http://google.com/")

        self.assertIsNotNone(process_response_commands.call_args)
        args, _ = process_response_commands.call_args
        data = args[1]
        self.assertEqual(data, {})

    @patch("requests.Session.send", mock_post(response_text='{"test": "foo"}'))
    @patch.object(LiftAIDataSender, "_process_response_commands")
    def test_normal_response_is_serialized(self, process_response_commands):
        self._insert_data_to_send(self.session)
        data_sender = LiftAIDataSender({})
        data_sender.send_data(self.session, "http://google.com/")

        self.assertIsNotNone(process_response_commands.call_args)
        args, _ = process_response_commands.call_args
        data = args[1]
        self.assertEqual(data, {"test": "foo"})

    @patch(
        "requests.Session.send",
        mock_post(response_text='{"bankTrips": 100, "bankElevators": 2}'),
    )
    def test_bank_trips_logs_timestamp_of_ping(self):
        expected_timestamp = pytz.utc.localize(datetime.now() - timedelta(days=1))
        self._insert_data_to_send(
            self.session,
            {
                "timestamp": expected_timestamp,
            },
        )
        data_sender = LiftAIDataSender({})
        data_sender.send_data(self.session, "http://google.com/")

        bank_trip = self.session.query(BankTrip).first()
        self.assertEqual(bank_trip.timestamp, expected_timestamp)


if __name__ == "__main__":
    unittest.main()
