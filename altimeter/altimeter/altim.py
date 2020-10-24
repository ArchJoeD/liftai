#!/usr/bin/env python3

import fcntl
import io
import logging
from datetime import datetime, timedelta
from time import sleep

import altimeter.constants as constants
from altimeter.db_writer import AltimDbWriter
import utilities.common_constants as common_constants
from utilities.db_utilities import AltimeterData

logger = logging.getLogger("altimeter")


class AltimeterProcessor:
    altim_avg = None
    sample_timestamp = None

    def set_up_altimeter(self):
        if constants.ALTIMETER_SAMPLE_PERIOD < constants.ICP_DELAY_WRITE_TO_READ:
            # The sampling period must be AT LEAST as long as the delay to read a sample.
            # It should actually be significantly longer or we will have to delay extra for
            # the next sample, adding jitter to the sampling rate.
            raise Exception(
                "ALTIMETER_SAMPLE_PERIOD must be less than ICP_DELAY_WRITE_TO_READ"
            )

        self.fw = io.open(constants.I2C_DEVICE, "wb", buffering=0)
        self.fr = io.open(constants.I2C_DEVICE, "rb", buffering=0)
        fcntl.ioctl(self.fr, constants.I2C_SLV, constants.I2C_ADDRESS)
        fcntl.ioctl(self.fw, constants.I2C_SLV, constants.I2C_ADDRESS)
        self.fw.write(constants.ICP_SOFT_RESET)
        sleep(constants.ICP_SOFT_RESET_DELAY)
        self.fw.write(constants.ICP_READ_ID_REG)  # Read ID register
        sleep(constants.ICP_DELAY_WRITE_TO_READ)
        # Check the hardware chip ID value as a sanity check.
        id_bytes = self.fr.read(constants.ICP_ID_READ_BYTES)

        # Get started on the first altimeter reading
        sleep(constants.ICP_DELAY_WRITE_TO_READ)
        self.fw.write(constants.ICP_TAKE_LOW_NOISE_MEASUREMENT)
        # The hardware will capture the sample at this point in time.
        self.sample_timestamp = datetime.now() + timedelta(
            seconds=constants.ICP_DELAY_WRITE_TO_READ
        )
        # Do the full sleep now so that there are no restrictions on when to first call take_altimeter_reading
        sleep(constants.ICP_DELAY_WRITE_TO_READ)
        # We should kick off the next sample at this point in time.
        self.next_sample_time = datetime.now() + timedelta(
            milliseconds=constants.ALTIMETER_SAMPLE_PERIOD
        )
        return (
            int.from_bytes(id_bytes, "big") & constants.ICP_ID_BITS
            == constants.ICP_ID_REG_VALUE
        )

    def take_altimeter_reading(self, writer: AltimDbWriter):
        """
        Data format we requested before this call: junk, P1, CRC, P2, P3, CRC, T1, T2, CRC
        Everything from here down is hardcoded numbers based on the ICP-10100 altimeter chip
        documentation: ICP-101xx-v1.2.pdf
        """
        data = self.fr.read(9)  # read 9 bytes.
        raw_pressure = (data[4] << 16) + (data[0] << 8) + data[1]
        altitude = constants.ALTIMETER_READABILITY_VALUE - (
            raw_pressure * common_constants.ALTIMETER_SCALE_FACTOR
        )

        record = AltimeterData(
            timestamp=self.sample_timestamp,
            altitude_x16=altitude,
        )
        writer.write_record(record)

        # Get started on the next altimeter reading.
        # We must ensure that we wait at least ICP_DELAY_WRITE_TO_READ seconds before calling this method again!!
        self.fw.write(constants.ICP_TAKE_LOW_NOISE_MEASUREMENT)
        # The hardware will capture the next sample at this point in time.
        self.sample_timestamp = datetime.now() + timedelta(
            seconds=constants.ICP_DELAY_WRITE_TO_READ
        )

    def record_altimeter_sample(self, writer):
        self.take_altimeter_reading(writer)  # This takes a variable amount of time.
        # We must wait a minimum amount of time for the altimeter to do the reading.
        time_to_sleep = max(
            constants.ICP_DELAY_WRITE_TO_READ,
            (self.next_sample_time - datetime.now()).total_seconds(),
        )
        if time_to_sleep == constants.ICP_DELAY_WRITE_TO_READ:
            if self.next_sample_time > datetime.now():
                logger.debug(
                    "Altimeter sampled too late, leaving only {0} seconds to get next sample".format(
                        round(
                            (self.next_sample_time - datetime.now()).total_seconds(), 3
                        )
                    )
                )
            else:
                logger.debug(
                    "Significant altimeter delay, {0} seconds".format(
                        round(
                            (datetime.now() - self.next_sample_time).total_seconds(), 3
                        )
                    )
                )
            # If we overran in time, start from now, not fixed time after last one.
            self.next_sample_time = datetime.now() + timedelta(
                milliseconds=constants.ALTIMETER_SAMPLE_PERIOD
            )
        else:
            # Next is fixed time after the last one.
            self.next_sample_time += timedelta(
                milliseconds=constants.ALTIMETER_SAMPLE_PERIOD
            )
        sleep(time_to_sleep)
