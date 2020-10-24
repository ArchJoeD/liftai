from os import rename, fsync, chmod
import json
from pathlib import Path

from tempfile import NamedTemporaryFile

import utilities.common_constants as common_constants


class DeviceConfiguration:
    @staticmethod
    def get_hardware_config():
        config_file_path = Path(common_constants.HW_CONFIG_FILE_NAME)
        if config_file_path.is_file():
            with open(common_constants.HW_CONFIG_FILE_NAME) as hw_config_file:
                return json.load(hw_config_file)
        return None

    @staticmethod
    def write_config_file(config):
        with NamedTemporaryFile(mode="w", prefix="config-atomic", delete=False) as fp:
            json.dump(config, fp)
            fp.flush()
            fsync(fp.fileno())

        rename(fp.name, common_constants.CONFIG_FILE_NAME)
        # TODO: Need a mechanism to apply configuration changes quickly instead of waiting for nightly reboot.
        # TODO: This involves the whole system, including how services stop when they're not being used.

    @staticmethod
    def update_config_file(updated_config):
        if updated_config is None or len(updated_config) <= 0:
            # Updated config has nothing in it. Skipping.
            return
        with open(common_constants.CONFIG_FILE_NAME, "r") as config_file:
            current_config = json.load(config_file)

        with NamedTemporaryFile(mode="w", prefix="config-atomic", delete=False) as fp:
            new_config = dict(current_config)
            new_config.update(updated_config)
            json.dump(new_config, fp)
            fp.flush()
            fsync(fp.fileno())

        rename(fp.name, common_constants.CONFIG_FILE_NAME)
        chmod(common_constants.CONFIG_FILE_NAME, 0o666)

    @staticmethod
    def get_config_data():
        config_file_path = Path(common_constants.CONFIG_FILE_NAME)
        if config_file_path.is_file():
            with open(common_constants.CONFIG_FILE_NAME) as config_file:
                return json.load(config_file)
        return DeviceConfiguration.get_default_config()

    @staticmethod
    def is_elevator(logger=None):
        try:
            config = DeviceConfiguration.get_config_data()
            actual_type = config[common_constants.CONFIG_TYPE]
            return actual_type == common_constants.CONFIG_TYPE_ELEVATOR
        except Exception as e:
            if logger is not None:
                logger.exception(
                    "Problems getting configuration when reading is_elevator, {0}".format(
                        str(e)
                    )
                )
            # Keep going since this exception is only for configuration

    @staticmethod
    def is_escalator(logger=None):
        try:
            config = DeviceConfiguration.get_config_data()
            actual_type = config[common_constants.CONFIG_TYPE]
            return actual_type == common_constants.CONFIG_TYPE_ESCALATOR

        except Exception as e:
            if logger is not None:
                logger.exception(
                    "Problems getting configuration for escalator, {0}".format(str(e))
                )
            # Keep going since this exception is only for configuration

    @staticmethod
    def has_battery_backup():
        hwconfig = DeviceConfiguration.get_hardware_config()
        if (
            hwconfig is not None
            and common_constants.HW_CONFIG_BATTERY_BACKUP in hwconfig
            and hwconfig[common_constants.HW_CONFIG_BATTERY_BACKUP] == True
        ):
            return True
        else:
            return False

    @staticmethod
    def has_three_color_led():
        hwconfig = DeviceConfiguration.get_hardware_config()
        if (
            hwconfig is not None
            and common_constants.HW_CONFIG_THREE_COLOR_LED in hwconfig
            and hwconfig[common_constants.HW_CONFIG_THREE_COLOR_LED] == True
        ):
            return True
        else:
            return False

    @staticmethod
    def has_altimeter():
        hw_config = DeviceConfiguration.get_hardware_config()
        if hw_config is None:
            return False
        if hw_config.get(common_constants.HW_CONFIG_ALTIMETER) == common_constants.HW_ALTIMETER_NAME:
            return True
        if hw_config.get(common_constants.HW_CONFIG_ALTIMETER2) == common_constants.HW_ALTIMETER_NAME:
            return True
        return False

    @staticmethod
    def has_hardware_audio_filter():
        hw_config = DeviceConfiguration.get_hardware_config()
        if (
            hw_config
            and common_constants.HW_CONFIG_AUDIO_FILTER in hw_config
            and hw_config[common_constants.HW_CONFIG_AUDIO_FILTER] == True
        ):
            return True
        return False

    @staticmethod
    def get_floor_count(logger=None):
        try:
            config = DeviceConfiguration.get_config_data()
            return config.get(common_constants.CONFIG_FLOOR_COUNT)
        except Exception as e:
            if logger is not None:
                logger.exception(
                    "Problems getting configuration when reading configured floors, {0}".format(
                        str(e)
                    )
                )
        return None

    @staticmethod
    def get_default_config():
        return {common_constants.CONFIG_TYPE: common_constants.CONFIG_TYPE_ELEVATOR}
