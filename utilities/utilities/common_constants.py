import json
import os
# Constants used across multiple applications.

HOSTNAME_FILE = os.environ.get("LIFTAI_HOSTNAME_FILE", "/etc/hostname")

LOG_FILES_FOLDER = '/home/pi/liftai_logs'
DB_HOST = os.environ.get("LIFTAI_DB_HOST", "localhost:6432")
DB_CONNECTION = "postgresql://usr:pass@{host}/liftaidb".format(host=DB_HOST)
DSN = 'dbname=liftaidb user=usr password=pass host=127.0.0.1'
REPORT_ENDPOINT = 'devices/track'
PING_ENDPOINT = 'devices/ping'
NOTIFICATION_ENDPOINT = 'devices/notification'
STORAGE_FOLDER = os.environ.get("LIFTAI_STORAGE_FOLDER", "/home/pi/liftai_storage")
CRON_FILE = "/var/spool/cron/crontabs/pi"

MESSAGE_TYPE_PING = "ping"
MESSAGE_TYPE_HOURLY_REPORT = "hourly_report"

CONFIG_FILE_NAME = os.environ.get('LIFTAI_CONFIG_FILE_NAME', '/etc/liftai/config.json')
CONFIG_TYPE = 'type'
CONFIG_TYPE_ELEVATOR = 'elevator'
CONFIG_TYPE_ESCALATOR = 'escalator'
CONFIG_FLOOR_COUNT = 'floors'
CONFIG_STOPPAGE_THRESHOLD = 'stoppageThreshhold'
CONFIG_STOPPAGE_DEFAULT = 'DF'
CONFIG_STOPPAGE_LOW = 'LO'
CONFIG_STOPPAGE_HIGH = 'HI'
CONFIG_STOPPAGE_VERY_HIGH = 'VI'

HW_CONFIG_FILE_NAME = os.environ.get("LIFTAI_HW_CONFIG_FILE_NAME", "/etc/liftai/hwconfig.json")
HW_CONFIG_BATTERY_BACKUP = 'battery-backup'
HW_CONFIG_MODEM = 'modem'
HW_CONFIG_SIM = 'sim'
HW_CONFIG_AUDIO = 'audio'
HW_CONFIG_AUDIO_FILTER = 'audio-filter'
HW_CONFIG_ACCELEROMETER = 'accelerometer'
HW_CONFIG_ALTIMETER = 'altimeter'
HW_CONFIG_ALTIMETER2 = 'altimeter2'
HW_ALTIMETER_NAME = "ICP-10100"
HW_CONFIG_THREE_COLOR_LED = 'three-color-led'
HW_CONFIG_PUSHBUTTON = 'pushbutton'

STOPPAGE_SOURCE_BANK = 'bank'
STOPPAGE_SOURCE_STANDALONE = 'standalone'
STOPPAGE_SOURCE_ESCALATOR_VIBRATION = 'escalator vibration'   # WARNING: hardcoded in the global_install.sql file!

# EVENTS: Events are things found by the various detectors in the system such as sudden vibrations, feeding into Elisha.
EVENT_SOURCE_BANK_SHUTDOWN = 'bank shutdown detector'
EVENT_SOURCE_STANDALONE_SHUTDOWN = 'standalone shutdown detector'
EVENT_SOURCE_PATTERN_SHUTDOWN = 'pattern based shutdown detector'
EVENT_SOURCE_VIBRATION = 'vibration detector'
EVENT_SOURCE_ANOMALY_DETECTOR = 'anomaly detector'
EVENT_SOURCE_ELEVATION_PROCESSOR = 'ElevationProcessor'
EVENT_SOURCE_TRIP_PROCESSOR = 'TripDetectProcessor'

EVENT_TYPE_SHUTDOWN = 'shutdown'
EVENT_SUBTYPE_BANK = 'bank'
EVENT_SUBTYPE_STANDALONE = 'standalone'
EVENT_SUBTYPE_LOW_USAGE_SHUTDOWN = 'low usage'
EVENT_SUBTYPE_ESCALATOR_VIBRATION = 'escalator vibration'
EVENT_SUBTYPE_ESCALATOR_BANK = 'escalator bank'

EVENT_TYPE_VIBRATION = 'vibration'
EVENT_SUBTYPE_LOW_FREQ_HORIZONTAL = 'low frequency horizontal'
EVENT_SUBTYPE_MID_FREQ_HORIZONTAL = 'mid frequency horizontal'
EVENT_SUBTYPE_HIGH_FREQ_HORIZONTAL = 'high frequency horizontal'
EVENT_SUBTYPE_LOW_FREQ_VERTICAL = 'low frequency vertical'
EVENT_SUBTYPE_MID_FREQ_VERTICAL = 'mid frequency vertical'
EVENT_SUBTYPE_HIGH_FREQ_VERTICAL = 'high frequency vertical'

EVENT_TYPE_ANOMALY = 'anomaly'
EVENT_SUBTYPE_RELEVELING = 'possible releveling'
EVENT_SUBTYPE_VIBRATION = 'vibration'
EVENT_SUBTYPE_AMBIENT_TEMPERATURE = 'ambient temperature'

EVENT_TYPE_ACCELEROMETER_DATA_GAP = 'accelerometer data gap'
EVENT_TYPE_ALTIMETER_DATA_GAP = 'altimeter data gap'
EVENT_SUBTYPE_GAP_START = 'gap start'
EVENT_SUBTYPE_GAP_END = 'gap end'

EVENT_TYPE_ELEVATION = 'elevation'
EVENT_SUBTYPE_MISSING_TRIP = 'missing trip'
EVENT_SUBTYPE_PROCESSED_GAP = 'processed gap'
EVENT_SUBTYPE_ELEVATION_RESET = 'elevation reset'
EVENT_DETAILS_ELEVATION_CHANGE = 'elevation change'

# PROBLEMS: Problems are the output from Elisha based on the events inputs.
PROB_TYPE_SHUTDOWN = 'shutdown'
PROB_TYPE_VIBRATION = 'vibration'
PROB_TYPE_ANOMALY = 'anomaly'
PROB_SUBTYPE_RELEVELING = 'releveling'

PROB_SHUTDOWN_STATUS = 'shutdown status'
PROB_SHUTDOWN_RUNNING = 'running'
PROB_SHUTDOWN_WATCH = 'shutdown watch'
PROB_SHUTDOWN_WARNING = 'shutdown warning'
PROB_SHUTDOWN_OLD_SHUTDOWN_STATE = 'shutdown'
PROB_SHUTDOWN_CONFIDENCE = 'confidence'

PROB_VIBRATION_STATUS = 'vibration status'
PROB_VIBRATION_NORMAL = 'normal'

PROB_OPEN_PROBLEM_ID = 'open problem id'

PROB_DETAILS_SYSTEM = json.loads(os.environ.get("LIFT_AI_PROB_DETAILS_SYSTEM", '{"system":"production"}'))

# The reason for having this here is to make it clear that the scale used by the altimeter application
# has an impact on the floor detection MAX_FLOOR_ERROR.
ALTIMETER_SCALE_FACTOR = 1

MIN_TRIPS_PER_FLOOR_TO_TRUST_DATA = 20
FLOORS_JSON_SCHEMA = 'schema'
FLOORS_JSON_LANDING_NUM = 'landing'
FLOORS_JSON_ELEVATION = 'elevation'
FLOORS_JSON_CUMULATIVE_ERR = 'cumulative error'
FLOORS_JSON_LAST_UPDATED = 'last updated'
FLOORS_CURRENT_SCHEMA = 1
# The device uses 0 based numbering for landings whereas people use 1 based numbering.  So we need
# to add this to all landing numbers that we send out to users.
FLOORS_USER_TRANSLATION = 1

# Used for scaling sleep durations in testing
TIME_SCALE_FACTOR = float(os.environ.get("LIFT_AI_TIME_SCALE_FACTOR", "1"))

# We get 100 samples per second, so we need to discard accelerometer data quickly.
# This is how long it stays in the db until we delete it.
MAX_MINUTES_OF_ACCEL_DATA_IN_DB = 60

AUDIO_NOISE = "noise"
AUDIO_FFT = "fft"

TRIP_VIBRATION_SCHEMA = 2
ACCEL_VIBRATION_SCHEMA = 2

ACCELEROMETER_SAMPLING_PERIOD = 10      # Units of milliseconds