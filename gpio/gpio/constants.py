
PROCESSING_SLEEP_INTERVAL = 2
GUARANTEED_MINUTES_OF_BATTERY_LIFE = 10     # The manufacturer recommends using at most 10 minutes to keep battery healthy.
INITIAL_COUNTDOWN = GUARANTEED_MINUTES_OF_BATTERY_LIFE * 60 / PROCESSING_SLEEP_INTERVAL
# If the GPIO application starts up with battery power, we want to shut down very soon since we don't know
# how much time we have left.
START_ON_BATTERY_COUNTDOWN = 1


# DICTIONARY KEYS AND VALUES
BATTERY_STATUS_KEY = 'battery status'
STATUS_EXTERNAL_POWER = 1
STATUS_ON_BATTERY = 0
CAR_STATUS_PROBLEMS_KEY = 'problems'
CAR_STATUS_NOT_CONNECTED_KEY = 'disconnected'
CAR_STATUS_ROA_WATCH_KEY = 'roa watch'


# LED COLORS
LED_RED = 'red'
LED_GREEN = 'green'
LED_BLUE = 'blue'

LEDS_RED =   {LED_RED: 1, LED_GREEN: 0, LED_BLUE: 0}
LEDS_GREEN = {LED_RED: 0, LED_GREEN: 1, LED_BLUE: 0}
LEDS_BLUE =  {LED_RED: 0, LED_GREEN: 0, LED_BLUE: 1}
LEDS_CYAN =  {LED_RED: 0, LED_GREEN: 1, LED_BLUE: 1}
LEDS_WHITE = {LED_RED: 1, LED_GREEN: 1, LED_BLUE: 1}
LEDS_OFF =   {LED_RED: 0, LED_GREEN: 0, LED_BLUE: 0}

# GPIO PINS
PIN_LED_RED   = 16
PIN_LED_GREEN = 20
PIN_LED_BLUE  = 21
PIN_DISCONNECT_BATTERY = 12     # Immediate shutoff if we have no external power, 1==shutdown... lights out
PIN_EXTERNAL_POWER = 19         # Do we have external power?  1==yes, 0==no
