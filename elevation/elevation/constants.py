
PROCESSING_SLEEP_INTERVAL = 1.0     # Number of seconds

# Any gap longer than this and we can't recover the elevation.
MAX_SENSOR_GAP = 5 * 60             # Units of seconds

# We save altimter data for 4 hours, but we only go back this far to safely avoid the end of the data.
OLDEST_ALTIMETER_DATA = 225         # Units of minutes
