# Constants used by the trips and floors module.

BATCH_PROCESSING_SLEEP_INTERVAL = 2

MPS_TO_FPM_CONVERSION = 196.85
GRAVITY_MPS2 = 9.81
DEFAULT_GRAVITY = 16700         # TODO: We need to use actual gravity readings instead!
MILLISEC_PER_SEC = 1000         # Just to be obvious about why we multiply by 1000
# The typical distance of an altimeter point from the flat line vs the standard floor distance is very small
# so we scale it up until we get something that reaches 100 when the line is extremely noisy/unreliable
STDERR_SCALE_FACTOR = 8000
# We need altiemter data to be this linear when the trip starts and after it ends.  If this is too high, then
# having just one or two points in the correct direction triggers start/end detect.  If it's too low, then
# we miss trips that aren't super clean.  We want to err on the side of being too high.
STDERR_MAX_THRESH = 0.9

MAX_TRIP_LEN = 40               # Units of seconds

ACCEL_SAMPLE_PERIOD = 10        # Units of milliseconds
ALTIM_SAMPLE_PERIOD = 250       # Units of milliseconds
START_TRIP_SLOPE_THRESH = 0.45  # Tunable (min slope of altimeter data to detect a trip)
END_TRIP_SLOPE_THRESH = 0.1     # Tunable (max slope of altime data to detect end of trip)
ALTIM_WINDOW_LEN = 8            # Tunable (num of data points to use in getting slope of line)
MIN_TRIP_ELEVATION = 17         # Anything less is a false detect, ignore it.

# We expand the altimeter trip interval since acceleration will be beyond the altimeter's trip start and end points
ALTIM_TO_ACCEL_TRIP_START_OFFSET = 2000  # Tunable. Units of milliseconds
ALTIM_TO_ACCEL_TRIP_END_OFFSET = 2700    # Tunable. Units of milliseconds

EXTRA_WINDOW_SIZE = 1.5  # Window needs to cover more than the max trip len
ACCEL_WINDOW_LEN = int(
    EXTRA_WINDOW_SIZE * MAX_TRIP_LEN * MILLISEC_PER_SEC / ACCEL_SAMPLE_PERIOD
)
# In the actual implementation this will just be a query from the database, not a queue.

ACCEL_TRIP_DETECT_THRESH = 2000  # Tunable.  No units, very large number
# This is used for finding the start and end of an acceleration
# We look for the smallest time window that contains at least this much of the initial
# acceleration total calculation.
ACCEL_PERCENT_THRESH = 0.999     # Tunable.  No units.

# Selected for how it looks visually in the chart, that's all.
RD_ACCEL_DETECT_VALUE = 10
# Save this many samples before the start of a trip
PRE_TRIP_CHART_SAMPLES = 500

# Number of samples beyond what the altimeter thinks is the end of the trip.
# This MUST be less than the minimum time between trips.
TRIP_END_COUNT_THRESH = 240     # Units of samples

# The controls how often we save the last timestamp into a pickle file while there's no detected
# trip in progress.  Too low causes saving file too often, too high causes too far of a fallback
# after a nightly reboot or software update. The number's units are in seconds.
SAVE_POINT_COUNT = int( 60 * ALTIM_SAMPLE_PERIOD / MILLISEC_PER_SEC )

# FFT / Power Spectral Density for vibration analysis
# This defines the frequency range buckets for capturing vibration, based on a 100 Hz sampling rate.
# Each number is the upper frequency limit of that bucket, so [0.0, 1.0, 2.0] means 0, 0.0001-1, 1-2, 2 and above.
# The first bucket is 0 Hz DC which we want in a separate bucket.  The rest of the buckets are at half-octaves.
# The last bucket is a very high number to catch everything else up to the Nyquist frequency.
fft_bin_boundaries = ( 0.0, 1.0, 1.414, 2.0, 2.828, 4.0, 5.657, 8.0, 11.314, 16.0, 22.627, 32.0, 45.2544, 10000.0 )

# We look at small windows of data to get peak-to-peak vibration values.
# The vibration starts to get attenuated as the frequency goes below:
#   (sampling_frequency / window_size) * 3/4
P2P_VIBRATION_WINDOW_SIZE = 20

# NEII defines jerk as: Calculated from acceleration using the maximum slope of the running least squares best fit line
# with a 0.5 s window. acceleration using the maximum slope of the running least squares best fit line with a 0.5 s window.
# However, it should have a 10 Hz low pass filter (which we don't have as of Sept 2020).
NEII_JERK_WINDOW_SIZE = 50

CSV_FILE_NAME = 'last_trip.csv'