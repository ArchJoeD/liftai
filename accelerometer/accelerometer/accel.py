#!/usr/bin/python

import collections
import logging
import operator
from time import sleep
from datetime import datetime, timedelta

from smbus2 import SMBus, SMBusWrapper

import accelerometer.constants as constants
import utilities.common_constants as common_constants
from accelerometer.models import AccelerometerData

logger = logging.getLogger("accelerometer")


class SMBusAccelerometer(SMBusWrapper):
    sanity_q = None
    gravity_estimate = None
    last_gravity_update_time = None
    last_timestamp = None

    def __enter__(self):
        self.bus = SMBus(bus=self.bus_number, force=self.force)
        return self

    def __init__(self, bus_number=0, auto_cleanup=True, force=False):
        super(SMBusAccelerometer, self).__init__(bus_number, auto_cleanup, force)
        self.sanity_q = collections.deque(
            constants.SANITY_Q_LEN * [0], maxlen=constants.SANITY_Q_LEN
        )
        # Start out with some value to avoid problems with immediate FIFO overflow.
        self.last_timestamp = datetime.now()

    @staticmethod
    def _convert_to_signed(value):
        if value >= 0x8000:
            return -((65535 - value) + 1)
        else:
            return value

    @classmethod
    def _convert_two_bytes_to_signed_int(cls, two_bytes):
        value = (two_bytes[0] << 8) + two_bytes[1]
        return cls._convert_to_signed(value)

    def _read_byte_register(self, register):
        return self.bus.read_byte_data(constants.I2C_BUS_ADDRESS, register)

    def _read_word_register(self, register):
        val = [0] * 2
        val[0] = self.bus.read_byte_data(constants.I2C_BUS_ADDRESS, register)
        val[1] = self.bus.read_byte_data(constants.I2C_BUS_ADDRESS, register + 1)
        return self._convert_two_bytes_to_signed_int(val)

    def _read_fifo_blocks(self, count):
        return self.bus.read_i2c_block_data(
            constants.I2C_BUS_ADDRESS, constants.FIFO_RW, count
        )

    def _write_byte(self, register, byte):
        return self.bus.write_byte_data(constants.I2C_BUS_ADDRESS, register, byte)

    def accelerometer_bus_setup(self):
        # Wake the 6050 up as it starts in sleep mode, also use a gyro based clock
        self._write_byte(constants.POWER_MGMT_1, 1)
        # Configure to sample at 100Hz
        self._write_byte(constants.SAMPLE_RATE_DIV, 0x09)
        # Configure for 44Hz low pass filter (should be below the Nyquist frequency)

        self._write_byte(constants.CONFIG, 0x03)
        # Reset FIFO
        self._write_byte(constants.USER_CTRL, 0x04)
        # Enable FIFO
        self._write_byte(constants.USER_CTRL, 0x40)
        # Turn on FIFO
        self._write_byte(constants.FIFO_ENABLE, 0x08)
        # Enable interrupts so we can read the status
        self._write_byte(constants.INT_ENABLE, 0x11)
        # Clear the FIFO overflow bit (FIFO_OFLOW_INT)
        # The bit clears to 0 after the register (INT_STATUS) has been read.
        self._read_byte_register(constants.INT_STATUS)

        # DEBUGGING SECTION
        # Now get the various registers to see what's going on with the chip.
        # print("Sample
        #
        #
        # rate divider: ", read_byte(0x19) )
        # print("CONFIG: ", read_byte(0x1a))
        # print("ACCEL_CONFIG: ", read_byte(0x1c))
        # print("FIFO_EN: ", read_byte(0x23))
        # print("INT_ENABLE: ", read_byte(0x38))
        # print("INT_STATUS: ", read_byte(0x3a))
        # print("TEMP: ", read_word_2c(0x41))
        # print("USER_CTRL: ", read_byte(0x6a))
        # print("PWR_MGMT_1: ", read_byte(0x6b))

    def read_data_from_hw(self):
        wait_counter = 0
        while True:
            # Spin waiting for enough data to fill the FIFO (if it's not already enough)
            if self._read_byte_register(constants.INT_STATUS) & 0x10 != 0:
                # The 1024 byte FIFO on the accelerometer chip overflowed, so restart it.
                logger.debug("FIFO OVERFLOW!!!")
                self.last_timestamp += timedelta(
                    milliseconds=constants.FIFO_OVERFLOW_DELAY
                )
                # Disable FIFO
                self._write_byte(constants.USER_CTRL, 0x00)
                # Reset FIFO
                self._write_byte(constants.USER_CTRL, 0x04)
                # Enable FIFO
                self._write_byte(constants.USER_CTRL, 0x40)

            bytes_ready_to_read = min(
                constants.MAX_BURST_READ, self._read_word_register(constants.FIFO_COUNT)
            )
            blocks_to_read = int(
                bytes_ready_to_read / constants.ACCEL_DATA_READ_BLOCK_SIZE
            )

            # TODO: Catch exception from ioctl on read to avoid potential infinite loop
            # Wait until we can read the max number of blocks in one burst.
            if blocks_to_read >= int(
                constants.MAX_BURST_READ / constants.ACCEL_DATA_READ_BLOCK_SIZE
            ):
                break

            wait_counter += 1
            if wait_counter > constants.READ_WAIT_TIMEOUT_COUNT:
                raise Exception(
                    "Timeout in fifo_burst_read, never got enough bytes to read"
                )
            sleep(0.1)

        fifo_blocks = []
        # Read multiple of full blocks of data to stay in sync.
        byte_count = blocks_to_read * constants.ACCEL_DATA_READ_BLOCK_SIZE
        while byte_count > 0:
            # Max burst read is 32 bytes
            fifo_blocks += self._read_fifo_blocks(
                min(constants.MAX_BURST_READ, byte_count)
            )
            byte_count -= min(constants.MAX_BURST_READ, byte_count)

        return fifo_blocks

    def detect_and_setup_vertical_axis(self):
        #  Get an initial rough guess for gravity and figure out which way is up
        count = 0
        avg = [0] * 3

        # Go through the FIFO and get the average values of each axis
        while count < constants.GRAVITY_ESTIMATION_SAMPLES:
            data_from_hw = self.read_data_from_hw()
            fc = len(data_from_hw)
            if fc == 0:  # If we don't have data to read, then wait and try again later
                sleep(0.1)
                continue
            c = 0
            while c < fc:
                avg[0] += self._convert_two_bytes_to_signed_int(
                    data_from_hw[c + 0 : c + 2]
                )
                avg[1] += self._convert_two_bytes_to_signed_int(
                    data_from_hw[c + 2 : c + 4]
                )
                avg[2] += self._convert_two_bytes_to_signed_int(
                    data_from_hw[c + 4 : c + 6]
                )
                count += 1
                c += 6

        # We want the average value for each axis, so divide by the number of samples.
        # Get at least half the samples we wanted
        if count >= constants.GRAVITY_ESTIMATION_SAMPLES / (
            constants.ACCEL_DATA_READ_BLOCK_SIZE * 2
        ):
            avg[0] /= count
            avg[1] /= count
            avg[2] /= count
        else:
            logger.critical("Unable to read enough FIFO samples")
            exit(1)

        # We use the sign to know whether up is in the positive or negative direction.
        sign = 1

        # The largest absolute value is the Z-axis, but it could be upside down.
        # Find max abs value and max index
        abs_avg = map(abs, avg)
        indexes_set = {0, 1, 2}
        index_max, abs_max_val = max(enumerate(abs_avg), key=operator.itemgetter(1))

        # real z-axis is third
        z_axis = index_max

        # we can't determine  x and y-axis
        indexes_set.remove(index_max)
        x_or_y_axis = indexes_set.pop()
        y_or_x_axis = indexes_set.pop()

        if avg[z_axis] < 0:
            sign = -1

        # set initial gravity
        self.gravity_estimate = avg[z_axis]

        # set sign and axis
        self.sign = sign
        self.x_axis = x_or_y_axis  # We don't know which is X and which is Y unless the box is positioned facing front
        self.y_axis = y_or_x_axis  # We don't know which is X and which is Y unless the box is positioned facing front
        self.z_axis = z_axis
        logger.debug(
            "Z is {0}, X is {1}, Y is {2}, sign is {3} gravity is {4}".format(
                z_axis, x_or_y_axis, y_or_x_axis, sign, self.gravity_estimate
            )
        )
        self.last_gravity_update_time = datetime.now()
        # Set the timestamp immediately before we start the algorithm (pipeline is already full, so subtract pipe len)
        self.last_timestamp = datetime.now() - timedelta(
            milliseconds=constants.ACCELEROMETER_TIME_OFFSET
        )

    def fifo_data_processor(self, fifo):
        i = 0
        xyz_data = []
        while i < len(fifo):

            # Get the values from the I2C bus data.
            sample = [0] * 3
            sample[0] = self._convert_two_bytes_to_signed_int(fifo[i + 0 : i + 2])
            sample[1] = self._convert_two_bytes_to_signed_int(fifo[i + 2 : i + 4])
            sample[2] = self._convert_two_bytes_to_signed_int(fifo[i + 4 : i + 6])
            i += 6

            # Remove gravity from the vertical axis.
            z_value = round(
                (sample[self.z_axis] - self.gravity_estimate) * self.sign, 3
            )

            # Add the data to the list of values.
            xyz_data.append(
                {
                    "timestamp": self.last_timestamp,
                    "x_data": sample[self.x_axis],
                    "y_data": sample[self.y_axis],
                    "z_data": z_value,
                }
            )

            # Move the timestamp forward by the time of one sample.
            self.last_timestamp += timedelta(
                milliseconds=common_constants.ACCELEROMETER_SAMPLING_PERIOD
            )

            # Try to stay in sync with the accelerometer chip's internal clock.  If we're drifting ahead
            # or behind the RPi clock, make small adjustments to catch up without causing large time gaps.
            # We know these have fixed time intervals between them, so don't use the timestamp
            # for any sort of integration, only for where a sequence of values basically starts or ends.
            if (self.last_timestamp - datetime.now()).total_seconds() > timedelta(
                milliseconds=(
                    constants.MAX_CLOCK_DRIFT - constants.ACCELEROMETER_TIME_OFFSET
                )
            ).total_seconds():
                self.last_timestamp -= timedelta(
                    milliseconds=constants.CLOCK_ADJUSTMENT
                )
            elif (datetime.now() - self.last_timestamp).total_seconds() > timedelta(
                milliseconds=(
                    constants.MAX_CLOCK_DRIFT + constants.ACCELEROMETER_TIME_OFFSET
                )
            ).total_seconds():
                self.last_timestamp += timedelta(
                    milliseconds=constants.CLOCK_ADJUSTMENT
                )

            # If too many accelerometer values are way out of range, then someone flipped the box upside down or HW error.
            # Restarting this application will fix most of these issues.
            if abs(z_value) <= constants.SANITY_LEVEL:
                self.sanity_q.append(0)
            else:
                self.sanity_q.append(1)

            if self.sanity_q.count(1) > constants.MAX_SANITY_COUNT:
                raise Exception(
                    "Accelerometer insanity: {0} of {1} Z-axis values were greater than {2}".format(
                        self.sanity_q.count(1),
                        constants.MAX_SANITY_COUNT,
                        constants.SANITY_LEVEL,
                    )
                )

        return xyz_data

    def update_gravity(self, session):
        result = AccelerometerData.get_gravity_info_since(
            session, self.last_gravity_update_time
        )
        if result and result.sample_points >= constants.GRAVITY_UPDATE_MIN_SAMPLES:
            self.gravity_estimate += result.gravity * constants.GRAVITY_UPDATE_DAMPING
            self.last_gravity_update_time = (
                datetime.now()
            )  # This will lag the actual time, which is fine
            logger.debug("Updating gravity to {0}".format(self.gravity_estimate))
