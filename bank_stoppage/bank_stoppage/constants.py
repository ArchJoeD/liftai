# Constants used by the bank based stoppage detector.
PROCESSING_SLEEP_INTERVAL = 89      # Use a number that will keep processes from getting synchronized together.
DELAY_MINUTES = 3

# If we don't have any values, use extremely high values
CONFIDENCE_DEFAULTS = {'90': 500, '95': 600, '99': 700}

MINIMUM_SELFLEARNING_SELF_TRIPS = 100
MINIMUM_SELFLEARNING_BANK_TRIPS = 400

# This is a three-fold thing, we have our threshold, followed by the number of
# elevators, then an index for 90, 95 and 99 confidence levels.
# So for two elevators, in the LO threshold we would get a 23, 30 and 40 for
# our confidence levels.
CONFIDENCE_TABLE = {
    "DF": {
        2: (25, 50, 80),
        3: (35, 65, 100),
        4: (38, 70, 110),
        5: (40, 80, 120),
        6: (45, 85, 130),
        7: (50, 90, 135),
        8: (55, 93, 140),
    },
    "LO": {
        2: (15, 30, 60),
        3: (20, 35, 70),
        4: (25, 45, 80),
        5: (27, 50, 90),
        6: (30, 55, 95),
        7: (33, 60, 100),
        8: (35, 70, 110),
    },
    "HI": {
        2: (60, 100,   180),
        3: (70, 110,   200),
        4: (80, 120,   240),
        5: (90, 130,  280),
        6: (100, 140,  300),
        7: (110, 150, 320),
        8: (120, 160, 350),
    },
    "VI": {
        2: (200, 350, 600),
        3: (250, 400, 650),
        4: (300, 430, 700),
        5: (350, 475, 750),
        6: (400, 500, 800),
        7: (450, 550, 850),
        8: (500, 600, 900)
    }
}
