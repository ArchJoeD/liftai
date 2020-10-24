import os
import unittest
from time import sleep
from unittest import TestCase

import gpio.battery as battery
import gpio.constants as constants
import gpio.leds as leds

from utilities.logging import create_rotating_log


class BatteryTesting(TestCase):
    """
    This must be run manually when there's a change to the low level GPIO code or a new hardware board.
    """
    logger = create_rotating_log("test_gpio")

    @classmethod
    def setUpClass(cls):
        print("Setting up for ACTUAL HARDWARE TEST.  This can only be run on the ACTUAL HARDWARE BOARD!")
        os.system("sudo systemctl stop gpio.service")

    def test_actual_gpio(self):
        b = battery.BatteryManager(self.logger)
        self.assertTrue(b._on_external_power())
        self.assertTrue(b.check_outputs())

    def test_actual_leds(self):
        ledMgr = leds.LEDManager()
        colors = (constants.LEDS_RED, constants.LEDS_OFF,
                  constants.LEDS_GREEN, constants.LEDS_OFF,
                  constants.LEDS_BLUE, constants.LEDS_OFF,
                  constants.LEDS_CYAN, constants.LEDS_OFF,
                  constants.LEDS_WHITE, constants.LEDS_OFF
        )
        for color in colors:
            ledMgr.light_leds(color)
            sleep(1)

if __name__ == "__main__":
    unittest.main()

