#!/usr/bin/env python3
#  Python program to control LEDs

import gpio.constants as constants
from gpio.import_gpio import GPIO


class LEDManager:

    def __init__(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(constants.PIN_LED_RED, GPIO.OUT)
        GPIO.setup(constants.PIN_LED_GREEN, GPIO.OUT)
        GPIO.setup(constants.PIN_LED_BLUE, GPIO.OUT)
        self.blink_status = True

    def light_leds(self, led_settings):
        GPIO.output(constants.PIN_LED_RED, led_settings[constants.LED_RED])
        GPIO.output(constants.PIN_LED_GREEN, led_settings[constants.LED_GREEN])
        GPIO.output(constants.PIN_LED_BLUE, led_settings[constants.LED_BLUE])

    def convert_status_to_leds(self, car_status, battery_status):
        # Status values in priority order:
        #   blinking: Live Look in progress
        #   CYAN: connectivity loss
        #   RED: shutdown or anomaly
        #   BLUE: manufacturing test (we get shut down during mfg test, so this is handled elsewhere)
        #   GREEN: normal
        if constants.CAR_STATUS_ROA_WATCH_KEY in car_status and car_status[constants.CAR_STATUS_ROA_WATCH_KEY]:
            self.blink_status = not self.blink_status
            if not self.blink_status:
                return constants.LEDS_OFF
        else:
            self.blink_status = True
        if constants.CAR_STATUS_NOT_CONNECTED_KEY in car_status and car_status[constants.CAR_STATUS_NOT_CONNECTED_KEY]:
            return constants.LEDS_CYAN
        elif constants.CAR_STATUS_PROBLEMS_KEY in car_status and car_status[constants.CAR_STATUS_PROBLEMS_KEY]:
            return constants.LEDS_RED
        else:
            return constants.LEDS_GREEN
