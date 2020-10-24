# Constants used by the anomaly detector

PROCESSING_SLEEP_INTERVAL = 17          # Units of seconds, keep unsynchronized from exact minutes/hours times
SLEEP_INTERVALS_PER_CYCLE = 3           # yeah, this is awful.  Main loop goes through this many sleep cycles.


# Releveling:
# When we detect a quiet time we should only look at data starting a few minutes after the known beginning
# and end a few minutes before the current time  People can be getting on/off the elevator before and after a
# trip.  Doors can be opening/closing.  Try to find long periods of inactivity to be sure and then use a guard interval.
QUIET_TIME_GUARD_INTERVAL = 4 * 60

RELEVELING_WINDOW_SIZE = PROCESSING_SLEEP_INTERVAL * SLEEP_INTERVALS_PER_CYCLE      # Avoid overlapping between runs.
RELEVELING_AMPLITUDE_MIN_THRESHOLD = 2500
RELEVELING_AMPLITUDE_MAX_THRESHOLD = 10000
RELEVELING_THRESHOLD = 60           # sampling rate is 100 Hz, so 100 = 1 second.

# To detect a lack of releveling (i.e. problem is gone), we need a much larger window size
LACK_OF_RELEVELING_WINDOW_SIZE = 30 * 60

# If we get this many releveling events without an event signalling the lack of releveling, then look for the
# lack of releveling now rather than waiting for 24 hours.  The purpose of this threshold is to avoid sending
# out lots of "we're not releveling" events when there are a few releveling events scattered around.
RELEVELING_THRESHOLD_FOR_LOOKING_FOR_FIX = 100


# Gap Detector:
MIN_GAP_SIZE = 2                                   # Units of seconds, more than this is considered a gap in the data

ALTIMETER_TABLE = "altimeter_data"
ACCELEROMETER_TABLE = "accelerometer_data"

STORAGE_FILE_NAME = "gap_detect_storage"

# If we get this many gap / end-of-gap transitions in a single block of time, then something is seriously wrong.
ABSOLUTE_MAX_LOOP_ITERATIONS = 20