import unittest
from datetime import datetime
from unittest.mock import ANY, MagicMock, patch
from time import time

import numpy as np
from freezegun import freeze_time

from audio_recorder.audio_rec import AudioRecorder, constants
from utilities.db_utilities import Audio, Session


@patch("sounddevice.InputStream", autospec=True)
class AudioRecorderTesting(unittest.TestCase):
    @staticmethod
    def _delete_data(session):
        session.query(Audio).delete()

    def setUp(self):
        self.session = Session()
        self._delete_data(self.session)

    def tearDown(self):
        self._delete_data(self.session)
        self.session.rollback()
        self.session.close()

    def generate_audio_block(self, scale_factor, ar):
        """
        Generate random audio data and give it to the audio recorder.
        Returns the total sum of squares noise level for the block for comparison.
        """
        unscaled_data = np.random.random_sample((constants.SAMPLE_BLOCK_SIZE, 1))
        scaled_data = unscaled_data * scale_factor
        ar._callback(scaled_data, None, MagicMock(inputBufferAdcTime=0), None)
        vector = scaled_data.ravel()
        total_noise = float(np.dot(vector, vector))
        return total_noise

    def verify_audio_db_row(self, session, expected_noise):
        """
        Compare the latest audio block in the database against the expected noise level.
        """
        record = (
            session.query(Audio.nsamples, Audio.sum_of_squares)
            .order_by(Audio.id.desc())
            .first()
        )
        self.assertEqual(
            record.nsamples,
            constants.SAMPLE_BLOCK_SIZE,
            "Need to modify tests to adapt to varying block size",
        )
        # Scale the values to be within a given range for comparison with a fixed precision.
        ratio = record.sum_of_squares / expected_noise
        self.assertAlmostEqual(ratio, 1.0, places=2)

    def test_start_stop_close_stream(self, input_stream):
        with AudioRecorder() as ar:
            input_stream().start.assert_not_called()
            input_stream().stop.assert_not_called()
            ar.start_record_audio()
            input_stream().start.assert_called_with()
            input_stream().stop.assert_not_called()
            ar.stop_record_audio()
            input_stream().stop.assert_called_with()
        input_stream().close.assert_called_with()

    def test_blocks_of_audio(self, input_stream):
        """
        Tests that we're able to process blocks one-by-one.
        """
        with AudioRecorder() as ar:
            ar.start_record_audio()
            # Test accuracy across a very wide range of values using powers of 10.
            scale_factor = 0.000001
            for _ in range(12):
                total_noise = self.generate_audio_block(scale_factor, ar)
                ar.process_data(self.session)
                self.verify_audio_db_row(self.session, total_noise)
                scale_factor *= 10.0

    def test_multiple_input_blocks_of_audio(self, input_stream):
        """
        Tests that if multiple blocks get queued up, we process those correctly.
        """
        with AudioRecorder() as ar:
            ar.start_record_audio()
            scale_factor = 0.01
            noise_levels = []
            for i in range(3):
                noise_levels.append(self.generate_audio_block(scale_factor, ar))
                scale_factor *= 10.0
            for i in range(3):
                ar.process_data(self.session)
                self.verify_audio_db_row(self.session, noise_levels[i])

    @freeze_time(datetime.now())
    @patch("audio_recorder.audio_rec.Audio", dict)
    def test_time_tracking_works_as_expected(self, input_stream):
        with AudioRecorder() as ar:
            ar.start_record_audio()
            start = time()

            self.assertEqual(ar.start_seconds_from_base, None)
            ar._callback(np.array([]), None, MagicMock(inputBufferAdcTime=10), None)
            ar._callback(np.array([]), None, MagicMock(inputBufferAdcTime=20), None)
            self.assertEqual(ar.start_seconds_from_base, 10)

            session = MagicMock()
            ar.process_data(session)

            session.add.assert_called_with(
                dict(
                    sum_of_squares=ANY,
                    nsamples=ANY,
                    timestamp=datetime.fromtimestamp(start),
                )
            )

            ar.process_data(session)
            session.add.assert_called_with(
                dict(
                    sum_of_squares=ANY,
                    nsamples=ANY,
                    timestamp=datetime.fromtimestamp(start + 10),
                )
            )


if __name__ == "__main__":
    unittest.main()
