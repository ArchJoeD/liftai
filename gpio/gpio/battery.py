#!/usr/bin/env python3
#  Python program to handle power failures, sending notificaitons and shutting off the system in a controlled manner.

import subprocess
from time import sleep

import gpio.constants as constants
from gpio.import_gpio import GPIO
from notifications.notifications import Notification, NotificationTopic
from utilities.common_constants import TIME_SCALE_FACTOR
from utilities.liftai_services import LiftAIServices
from utilities.db_utilities import Trip
from utilities.floor_detection import can_use_floor_data


class BatteryManager:
    notification = Notification()

    def __init__(self, logger):
        self.status = None
        self.logger = logger
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(constants.PIN_DISCONNECT_BATTERY, GPIO.OUT)
        # Pull up the signal in case this accidently runs on a device without the circuitry.
        GPIO.setup(constants.PIN_EXTERNAL_POWER, GPIO.IN)

    def _check_initial_setup(self):
        if self.status is None:
            if self._on_external_power():
                self.logger.debug("We're starting up normally with external power")
                self.status = constants.STATUS_EXTERNAL_POWER
            else:
                self.logger.info("We're starting up already on battery power, shutting down soon")
                self.status = constants.STATUS_ON_BATTERY
                self.countdown = 1       # We don't really know how much time we have if we just started up on battery!

    def _on_external_power(self):
        if GPIO.input(constants.PIN_EXTERNAL_POWER) == 1:
            return True
        else:
            return False

    def _shutdown_now(self):
        GPIO.output(constants.PIN_DISCONNECT_BATTERY, 1)
        sleep(1 * TIME_SCALE_FACTOR)
        # Oops, we're still running and didn't shut down.  External power must have returned.
        GPIO.output(constants.PIN_DISCONNECT_BATTERY, 0)

    def check_outputs(self):
        # This allows a caller to verify that we can control the output GPIO
        try:
            GPIO.output(constants.PIN_DISCONNECT_BATTERY, 0)
        except:
            return False
        return True

    def _stop_all_services(self):
        services_list = LiftAIServices.get_list()
        for s in services_list:
            if s != "gpio":
                self.logger.debug("   stopping {0}".format(s))
                subprocess.run(['sudo', '/bin/systemctl', 'stop', s])

    def _start_all_services(self):
        #  Use start and not restart because if it's already running, we don't need to do anything.
        services_list = LiftAIServices.get_list()
        for s in services_list:
            if s != "gpio":
                self.logger.debug("   starting {0}".format(s))
                subprocess.run(['sudo', '/bin/systemctl', 'start', s])

    def manage_battery(self, session):
        self._check_initial_setup()
        if self.status == constants.STATUS_EXTERNAL_POWER:
            if not self._on_external_power():
                self.status = constants.STATUS_ON_BATTERY
                self.countdown = constants.INITIAL_COUNTDOWN

                self.logger.info("We just lost external power, switching over to battery, sending notifications")
                self.notification.send(
                    NotificationTopic.POWER_EVENT,
                    notif_data=self._get_power_loss_data(session),
                    include_last_trip=True
                )
        else:
            # We're on battery, counting down until we shutdown.
            self.countdown -= 1
            if self._on_external_power():
                self.status = constants.STATUS_EXTERNAL_POWER
                self.countdown = 0
                self.logger.info("We just regained external power before having to shut down, sending notifications")
                self.notification.send(
                    NotificationTopic.POWER_EVENT,
                    notif_data={"state": "ON"}
                )
            elif self.countdown <= 0:
                self.logger.info("We've waited long enough for power to restore, shutting down the system")
                sleep(2 * TIME_SCALE_FACTOR)    # Give the log message time to get written out.
                self._stop_all_services()
                sleep(2 * TIME_SCALE_FACTOR)    # Wait some more just to be safe.
                self._shutdown_now()
                self.logger.info("External power restored at the LAST second, starting everything back up")
                self._start_all_services()
                self.status = constants.STATUS_EXTERNAL_POWER

    def get_battery_status(self):
        return {constants.BATTERY_STATUS_KEY: self.status}

    @classmethod
    def _get_power_loss_data(cls, session):
        if can_use_floor_data(session):
            landing_number = Trip.get_latest_landing_number(session)

            if landing_number is not None:
                return {"landing_number": landing_number, "state": "OFF"}

        return {"state": "OFF"}