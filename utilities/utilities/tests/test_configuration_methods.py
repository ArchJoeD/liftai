import json
import logging
import unittest
from unittest.mock import patch

from utilities.device_configuration import DeviceConfiguration
import utilities.common_constants as common_constants


@patch("utilities.floor_detection.DeviceConfiguration.get_hardware_config")
class TestConfigurationMethods(unittest.TestCase):
    logger = logging.getLogger(__name__)

    def setUp(self):
        with open(common_constants.CONFIG_FILE_NAME, "w") as cf:
            json.dump({"type": "elevator"}, cf)

    def test_updating_with_new_key_does_not_overwrite_old(self, get_hardware_config):
        DeviceConfiguration.update_config_file({"wifi": {"enabled": False}})
        with open(common_constants.CONFIG_FILE_NAME, "r") as cf:
            loaded = json.load(cf)
            self.assertTrue(len(loaded) > 0)
            self.assertEqual(loaded["type"], "elevator")

    def test_update_config_does_not_clobber_defaults(self, get_hardware_config):
        DeviceConfiguration.update_config_file({"type": "escalator"})
        with open(common_constants.CONFIG_FILE_NAME, "r") as cf:
            loaded = json.load(cf)
            self.assertTrue(len(loaded) > 0)
            self.assertEqual(loaded["type"], "escalator")

    def test_can_write_to_config(self, get_hardware_config):
        DeviceConfiguration.write_config_file({"test": True})
        with open(common_constants.CONFIG_FILE_NAME, "r") as cf:
            loaded = json.load(cf)
            self.assertTrue(len(loaded) > 0)
            self.assertEqual(loaded, {"test": True})

    def test_has_hw_audio_filter_no_config(self, get_hardware_config):
        get_hardware_config.return_value = None
        self.assertFalse(DeviceConfiguration.has_hardware_audio_filter())

    def test_has_hw_audio_filter_has_config_but_no_filter(self, get_hardware_config):
        get_hardware_config.return_value = {"foo": "bar"}
        self.assertFalse(DeviceConfiguration.has_hardware_audio_filter())

    def test_has_hw_audio_filter_typical_3_2_hw_config(self, get_hardware_config):
        get_hardware_config.return_value = {
            "modem": "Huawei MS2372",
            "sim": "Hologram",
            "audio": True,
            "audio-filter": True,
            "accelerometer": "MPU6050",
            "altimeter": "MPL3115A2",
            "altimeter2": "ICP-10100",
            "pushbutton": True,
            "battery-backup": True,
            "three-color-led": True,
            "rtc": True,
        }
        self.assertTrue(DeviceConfiguration.has_hardware_audio_filter())


if __name__ == "__main__":
    unittest.main()
