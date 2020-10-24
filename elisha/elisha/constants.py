# Constants used by the elisha problem detection application

PROCESSING_SLEEP_INTERVAL = 13
PROCESS_BATCH_SIZE = 50             # This should be a high number to handle bursts of events.

STATE_SHUTDOWN_PROB_ID = 'shutdown problem id'
STATE_SHUTDOWN_CONFIDENCE = 'shutdown confidence'
SHUTDOWN_PROBLEM_TEXT = 'Possible shutdown detected on this elevator'

SHUTDOWN_WATCH_CONFIDENCE_THRESHOLD = 70

RELEVELING_STATE = 'releveling state'
RELEVELING_TIME_OF_STATE_CHANGE = 'time of last state change'

RELEVELING_LOOKBACK_HOURS = 24          # How many hours ago we go back when counting releveling events.
RELEVELING_COUNT_THRESHOLD = 30         # How many relevelings need to occur in that time period to detect a problem.
RELEVELING_COUNT_MAX_CONFIDENCE = 85    # We never report more than this amount of confidence for relevelings
