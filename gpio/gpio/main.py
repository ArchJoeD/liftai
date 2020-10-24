from time import sleep
import logging
import gpio.battery as battery
import gpio.car_status as car_status
import gpio.leds as leds
import gpio.constants as constants

from utilities import device_configuration as device_configuration
from utilities.logging import create_rotating_log
from utilities.db_utilities import session_scope

def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = create_rotating_log("gpio")
    logger.debug("--- Starting GPIO app")

    has_battery_backup = device_configuration.DeviceConfiguration.has_battery_backup()
    has_leds = device_configuration.DeviceConfiguration.has_three_color_led()

    try:
        batteryMgr = battery.BatteryManager(logger)
        car = car_status.CarStatus(logger)
        led_mgr = leds.LEDManager()
        while(True):
            if has_battery_backup:
                with session_scope() as session:
                    batteryMgr.manage_battery(session)
                battery_status = batteryMgr.get_battery_status()
            else:
                battery_status = {}
            if has_leds:
                led_color = led_mgr.convert_status_to_leds(car.get_car_status(), battery_status)
                led_mgr.light_leds(led_color)
            sleep(constants.PROCESSING_SLEEP_INTERVAL)
    except Exception as ex:
        logger.error("Exception in gpio: %s" % str(ex))
        raise

if __name__ == "__main__":
    main()
