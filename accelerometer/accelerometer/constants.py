# This interfaces to an MPU6050 accelerometer.
# See the datasheet at the website below for details on the hardware registers.
# https://www.invensense.com/products/motion-tracking/6-axis/mpu-6050/

# Address value read via the i2c_detect command
I2C_BUS_ADDRESS = 0x68

# Power management registers
POWER_MGMT_1 = 0x6b
POWER_MGMT_2 = 0x6c
SAMPLE_RATE_DIV = 0x19
CONFIG = 0x1a
FIFO_ENABLE = 0x23
FIFO_COUNT = 0x72
FIFO_RW = 0x74
INT_ENABLE = 0x38
INT_STATUS = 0x3a
USER_CTRL = 0x6a

# We read blocks of 6 bytes (1 two-byte sample of 3 axes)
ACCEL_DATA_READ_BLOCK_SIZE = 6
MAX_BURST_READ = 32

# Number of initial samples we take in order to get a first guess of gravity.
GRAVITY_ESTIMATION_SAMPLES = 500
GRAVITY_UPDATE_FREQUENCY = 100
GRAVITY_UPDATE_MAX_ACCEL = 1000.0
GRAVITY_UPDATE_MIN_SAMPLES = 3000
# 1=critcally damped, 0=no updates, 0.5=overdamped,   use overdamping to limit noise
GRAVITY_UPDATE_DAMPING = 0.3

SANITY_Q_LEN = 3000      # A bunch of extreme Z-axis values means someone tilted the device or accelerometer mess up.
SANITY_LEVEL = 8000      # A Z-axis absolute value greater than this should be rare.
MAX_SANITY_COUNT = SANITY_Q_LEN>>2      # More than this many Z-axis values > SANITY_LEVEL means insanity.

READ_WAIT_TIMEOUT_COUNT = 100

# These values are associated with tracking the accelerometer clock.
# This is the maximum difference in time between the timestamps coming in from the accelerometer and the
# current RPi internal time.  We make slight adjustments to the timestamps to keep them fairly close to
# the actual real time.
MAX_CLOCK_DRIFT = 600                   # Units of milliseconds
# There's a delay within the chip, the I2C bus, and queueing, really just our estimate
ACCELEROMETER_TIME_OFFSET = 200         # Units of milliseconds
# When we get a FIFO overflow, we lose about 3 seconds of data, so add this to the
# timestamp so we don't allocate the gap to future samples in tiny CLOCK_ADJUSTMENT samples.
FIFO_OVERFLOW_DELAY = 2900              # Units of milliseconds
CLOCK_ADJUSTMENT = 1                    # Units of milliseconds

# How many times to fetch data from the HW before writing it to the database.
MAIN_LOOP_COUNT = 14
