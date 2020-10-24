#!/usr/bin/env python3
import logging
import queue
from collections import namedtuple
from datetime import datetime, timedelta
from json import JSONEncoder

import numpy as np
import sounddevice as sd

from audio_recorder import constants
from utilities.db_utilities import Audio


logger = logging.getLogger(__name__)
AudioSample = namedtuple("AudioSample", ["timestamp", "samples"])


class AudioRecorder(object):
    is_recording = None
    stream = None
    audio_queue = None
    start_seconds_from_base = None
    start_dt = None

    def __init__(self):
        self.audio_queue = queue.Queue()
        self.is_recording = False

    def __enter__(self):
        self.stream = sd.InputStream(
            samplerate=constants.RECORD_SAMPLERATE,
            device=constants.RECORD_DEVICE_ID,
            channels=constants.RECORD_CHANNELS,
            callback=self._callback,
            blocksize=constants.SAMPLE_BLOCK_SIZE,
            latency=0.25,  # From testing this appears to be stable to prevent input overflows
        )
        return self

    def __exit__(self, *args):
        self.stream.close()

    def _callback(self, indata, frames, time_struct, status):
        if status:
            logger.error("Error callback from input stream, {0}".format(str(status)))
            return

        seconds_from_base = time_struct.inputBufferAdcTime

        if self.start_seconds_from_base is None:
            self.start_seconds_from_base = seconds_from_base
            self.start_dt = datetime.now()

        timestamp = self.start_dt + timedelta(
            seconds=(seconds_from_base - self.start_seconds_from_base)
        )
        self.audio_queue.put(AudioSample(timestamp=timestamp, samples=indata.copy()))

    def process_data(self, session):
        record = self.audio_queue.get()  # blocking call
        audio_array = record.samples

        audio_chunk = audio_array.ravel()

        # dot product of vector with itself = sum of square of elements
        sum_of_squares = float(np.dot(audio_chunk, audio_chunk))

        # TODO: For door detection, add FFT back in, but probably saving approx 20 seconds of data
        # fft_result = np.absolute( np.fft.fft(audio_chunk[:constants.SAMPLES_PER_FFT])[:int(constants.SAMPLES_PER_FFT/2)])
        # query = text("INSERT INTO audio (timestamp, nsamples, sum_of_squares, fft) VALUES (:timestamp, :nsamples, :sum_of_squares, :fft)")

        record = Audio(
            timestamp=record.timestamp,
            nsamples=audio_chunk.size,
            sum_of_squares=sum_of_squares,
            # fft = json.dumps(fft_result, cls=NumpyFloatArrayEncoder)
        )
        session.add(record)

    def start_record_audio(self):
        self.is_recording = True
        self.stream.start()

    def stop_record_audio(self):
        self.is_recording = False
        self.stream.stop()


class NumpyFloatArrayEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return [float(x) for x in obj.tolist()]
        return JSONEncoder.default(self, obj)
