is_real_device = True

try:
    import RPi.GPIO as GPIO  # pylint: disable=unused-import
except RuntimeError as e:
    if str(e) == "This module can only be run on a Raspberry Pi!":
        is_real_device = False
        import gpio.rpi_gpio_mock as GPIO  # pylint: disable=unused-import

