import os
import unittest
from unittest import TestCase
from unittest.mock import Mock, patch
from subprocess import PIPE, Popen

import gpio.constants as constants
import gpio.car_status as car_status
import gpio.leds as leds
import utilities.common_constants as common_constants
from gpio.battery import BatteryManager
from gpio.import_gpio import is_real_device
from utilities.liftai_services import LiftAIServices
from utilities.logging import create_rotating_log
from utilities import device_configuration as device_configuration
from notifications.notifications import NotificationTopic

def check_services():
    # Return true if all services are running, false if all stopped, None if anything else
    # This is only used for testing.
    all_running = True
    all_stopped = True
    services_list = LiftAIServices.get_list()
    for s in services_list:
        with Popen(["/bin/systemctl", "status", s], stdin=PIPE, stdout=PIPE) as p:
            for _ in range(100):
                line = p.stdout.readline()
                if not line and p.returncode is not None:
                    all_running = False
                    break
                if b"active (running)" in line:
                    all_stopped = False
                    break
    if all_running == all_stopped:
        return None
    return all_running


class BatteryTesting(TestCase):
    logger = create_rotating_log("test_gpio")

    @classmethod
    def setUpClass(cls):
        print("Setting up for testing, NOTE THAT THESE TESTS STOP THE EXISTING SYSTEM AND ARE DESTRUCTIVE...")
        os.system("sudo systemctl stop gpio.service")

    def setUp(self):
        self.bmgr = BatteryManager(self.logger)
        self.bmgr._on_external_power = Mock()
        self.bmgr._shutdown_now = Mock()
        self.bmgr._stop_all_services = Mock()
        self.bmgr._start_all_services = Mock()

    def tearDown(self):
        self.bmgr = None

    def test_gpio_smoke_test(self):
        self.bmgr._on_external_power.return_value = True
        self.bmgr._check_initial_setup()
        self.assertTrue(self.bmgr.status == constants.STATUS_EXTERNAL_POWER)
        self.assertTrue(self.bmgr.logger == self.logger)

    def test_gpio_starting_on_battery(self):
        self.bmgr._on_external_power.return_value = False
        self.bmgr._check_initial_setup()
        self.assertTrue(self.bmgr.countdown == constants.START_ON_BATTERY_COUNTDOWN)
        self.assertTrue(self.bmgr.status == constants.STATUS_ON_BATTERY)
        while self.bmgr.countdown > 0:
            self.bmgr.manage_battery(Mock())
        self.bmgr._shutdown_now.assert_called_once_with()
        self.bmgr._on_external_power.return_value = True
        self.bmgr.manage_battery(Mock())
        self.assertTrue(self.bmgr.status == constants.STATUS_EXTERNAL_POWER)

    def test_gpio_starting_on_external_power(self):
        self.bmgr._on_external_power.return_value = True
        self.bmgr.manage_battery(Mock())
        self.assertTrue(self.bmgr.status == constants.STATUS_EXTERNAL_POWER)
        self.bmgr._shutdown_now.assert_not_called()
        self.bmgr._stop_all_services.assert_not_called()
        self.bmgr._start_all_services.assert_not_called()
        self.bmgr._on_external_power.return_value = False
        self.bmgr.manage_battery(Mock())
        sanity_counter = 10000
        while sanity_counter > 0:
            sanity_counter -= 1
            self.bmgr.manage_battery(Mock())
            self.assertTrue(self.bmgr.status == constants.STATUS_ON_BATTERY)
            self.bmgr._shutdown_now.assert_not_called()
            self.bmgr._stop_all_services.assert_not_called()
            self.bmgr._start_all_services.assert_not_called()
            if self.bmgr.countdown == 1:
                break
        self.assertTrue(sanity_counter != 0)
        # The next call will be the actual shutdown
        self.bmgr.manage_battery(Mock())
        self.bmgr._shutdown_now.assert_called_once_with()
        self.bmgr._stop_all_services.assert_called_once_with()
        self.bmgr._start_all_services.assert_called_once_with()

    @unittest.skipIf(not is_real_device, "Can only run on a real device")
    def test_stopping_starting_services(self):
        b = BatteryManager(self.logger)
        b._stop_all_services()
        self.assertFalse(check_services())
        b._start_all_services()
        self.assertTrue(check_services())

    def test_hw_config(self):
        os.system("echo \"{\\\"battery-backup\\\": false }\" > " + common_constants.HW_CONFIG_FILE_NAME)
        self.assertFalse( device_configuration.DeviceConfiguration.has_battery_backup())
        os.system("echo \"{ }\" > " + common_constants.HW_CONFIG_FILE_NAME)
        self.assertFalse(device_configuration.DeviceConfiguration.has_battery_backup())
        os.system("echo \"{\\\"other-parameter\\\": true }\" > " + common_constants.HW_CONFIG_FILE_NAME)
        self.assertFalse(device_configuration.DeviceConfiguration.has_battery_backup())
        os.system("echo \"{\\\"battery-backup\\\": true }\" > " + common_constants.HW_CONFIG_FILE_NAME)
        self.assertTrue(device_configuration.DeviceConfiguration.has_battery_backup())
        os.system("rm {0}".format(common_constants.HW_CONFIG_FILE_NAME))
        self.assertFalse(device_configuration.DeviceConfiguration.has_battery_backup())

    def test_get_battery_status(self):
        b = BatteryManager(self.logger)
        b.status = constants.STATUS_ON_BATTERY
        status_value = b.get_battery_status()
        self.assertTrue( status_value[constants.BATTERY_STATUS_KEY] == constants.STATUS_ON_BATTERY)
        b.status = constants.STATUS_EXTERNAL_POWER
        status_value = b.get_battery_status()
        self.assertTrue(status_value[constants.BATTERY_STATUS_KEY] == constants.STATUS_EXTERNAL_POWER)


def _get_battery_manager_with_mocks():
    logger = Mock()
    batteryManager = BatteryManager(logger)
    batteryManager.status = constants.STATUS_EXTERNAL_POWER
    notification = Mock()
    batteryManager.notification = notification

    return batteryManager


@patch("gpio.battery.can_use_floor_data")
@patch("gpio.battery.Trip.get_latest_landing_number")
class PowerOffNotificationTestCase(unittest.TestCase):

    @patch('gpio.battery.BatteryManager._get_power_loss_data')
    def test_get_notification_data_has_standard_info(
        self,_get_power_loss_data, get_latest_landing_number, can_use_floor_data
    ):
        get_latest_landing_number.return_value = None
        can_use_floor_data.return_value = False
        session = Mock()

        battery_manager = _get_battery_manager_with_mocks()
        battery_manager.manage_battery(session)

        battery_manager.notification.send.assert_called_once_with(
            NotificationTopic.POWER_EVENT,
            notif_data=_get_power_loss_data(session),
            include_last_trip=True
        )

    def test_get_notification_data_does_not_include_landing_info_if_floor_data_isnt_ready(
        self, get_latest_landing_number, can_use_floor_data
    ):
        get_latest_landing_number.return_value = None
        can_use_floor_data.return_value = False
        session = Mock()

        result = BatteryManager._get_power_loss_data(session)
        self.assertEqual(result, {"state": "OFF"})

    def test_get_notification_data_does_not_include_landing_info_if_not_available(
        self, get_latest_landing_number, can_use_floor_data
    ):
        get_latest_landing_number.return_value = None
        can_use_floor_data.return_value = True
        session = Mock()

        result = BatteryManager._get_power_loss_data(session)
        self.assertEqual(result, {"state": "OFF"})

    def test_get_notification_data_includes_landing_info_if_available(
        self, get_latest_landing_number, can_use_floor_data
    ):
        expected_landing = 1
        get_latest_landing_number.return_value = expected_landing
        can_use_floor_data.return_value = True
        session = Mock()

        result = BatteryManager._get_power_loss_data(session)
        self.assertEqual(result, {"landing_number": expected_landing, "state": "OFF"})


class CarStatusTesting(TestCase):
    logger = create_rotating_log("test_gpio")

    def test_get_car_status(self):
        cstatus = car_status.CarStatus(self.logger)
        ledMgr = leds.LEDManager()
        #  Normal situation
        self._assert_led_outcome(ledMgr, cstatus, False, False, False, constants.LEDS_GREEN)
        #  and it stays that way
        self._assert_led_outcome(ledMgr, cstatus, False, False, False, constants.LEDS_GREEN)
        #  shutdown or anomaly
        self._assert_led_outcome(ledMgr, cstatus, True, False, False, constants.LEDS_RED)
        self._assert_led_outcome(ledMgr, cstatus, True, False, False, constants.LEDS_RED)
        self._assert_led_outcome(ledMgr, cstatus, True, False, False, constants.LEDS_RED)
        #  connectivity loss
        self._assert_led_outcome(ledMgr, cstatus, False, False, True, constants.LEDS_CYAN)
        self._assert_led_outcome(ledMgr, cstatus, False, False, True, constants.LEDS_CYAN)
        #  connectivity loss overrides shutdown or anomaly
        self._assert_led_outcome(ledMgr, cstatus, True, False, True, constants.LEDS_CYAN)
        #  roa watch in normal conditions
        self._assert_led_outcome(ledMgr, cstatus, False, True, False, constants.LEDS_OFF)
        self._assert_led_outcome(ledMgr, cstatus, False, True, False, constants.LEDS_GREEN)
        self._assert_led_outcome(ledMgr, cstatus, False, True, False, constants.LEDS_OFF)
        self._assert_led_outcome(ledMgr, cstatus, False, True, False, constants.LEDS_GREEN)
        self._assert_led_outcome(ledMgr, cstatus, False, True, False, constants.LEDS_OFF)
        self._assert_led_outcome(ledMgr, cstatus, False, True, False, constants.LEDS_GREEN)
        # roa watch --> another state always turns the LED back on
        self._assert_led_outcome(ledMgr, cstatus, True, False, False, constants.LEDS_RED)
        self._assert_led_outcome(ledMgr, cstatus, True, True, False, constants.LEDS_OFF)
        self._assert_led_outcome(ledMgr, cstatus, True, False, False, constants.LEDS_RED)
        self._assert_led_outcome(ledMgr, cstatus, True, False, False, constants.LEDS_RED)
        self._assert_led_outcome(ledMgr, cstatus, False, True, False, constants.LEDS_OFF)
        self._assert_led_outcome(ledMgr, cstatus, False, True, False, constants.LEDS_GREEN)
        #  And run through a couple more just to be sure
        self._assert_led_outcome(ledMgr, cstatus, True, False, True, constants.LEDS_CYAN)
        self._assert_led_outcome(ledMgr, cstatus, False, False, False, constants.LEDS_GREEN)

    def _assert_led_outcome(self, ledMgr, carStatus, problems, roa, disconnected, expected_leds):
        b_problems = 1 if problems else 0
        b_roa = 1 if roa else 0
        b_disconnected = 0 if disconnected else 1
        db_rows = [(constants.CAR_STATUS_PROBLEMS_KEY, b_problems),
                   (constants.CAR_STATUS_ROA_WATCH_KEY, b_roa),
                   (constants.CAR_STATUS_NOT_CONNECTED_KEY, b_disconnected)]
        curr_car_status = carStatus._process_car_status(db_rows)
        actual_leds = ledMgr.convert_status_to_leds(curr_car_status, {'no battery status yet': True})
        self.assertTrue(actual_leds == expected_leds, "With data {0} ended up with LEDS {1} and not {2}".format(db_rows, actual_leds, expected_leds))


if __name__ == "__main__":
    unittest.main()
    