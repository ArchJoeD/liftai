# If we have a gap in the accelerometer data of this long or more, then we switch over to
# an alternative method of determining changes in elevation.
MAX_ALLOWED_ACCELEROMETER_GAP = 15  # Units of seconds

# We expect the altimeter app and elevation app to get us within this close to the predicted
# elevation of a floor.  (tunable parameter)
# TODO: Change this to be dynamic based on floor distances of this elevator.
MAX_FLOOR_ERROR = (
    16  # No units (whatever altimeter app produces), only used for relative changes
)
MIN_FLOOR_SEPARATION = 20

# This checks for the case where a floor's elevation number has a bias and
# needs to be adjusted.  We make only very small adjustments to avoid
# oscillation or over-correction. (tunable parameter)
MAX_FLOOR_ACCUMULATED_ERROR = 75
# We increment or decrement the elevation by this much (tunable parameter)
FLOOR_LEVEL_ADJUST = 1

DELAY_BETWEEN_EXECUTIONS = 15  # Units of seconds
MAX_TRIPS_TO_PROCESS = 4

STORAGE_FILE_NAME = "floor_detector"

LAST_TRIP_ID = "last_trip_id"
LAST_ALTIMETER_ID = "last_altimeter_id"
LAST_ACCELEROMETER_ID = "last_accelerometer_id"
