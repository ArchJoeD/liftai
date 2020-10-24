
# For altimeter info, see the document: ICP-101xx-v1.2.pdf
# Some info on accessing I2C devices that don't have registers: https://www.raspberrypi.org/forums/viewtopic.php?t=84966
I2C_DEVICE = "/dev/i2c-1"
I2C_ADDRESS = 0x63
I2C_SLV=0x0703

ICP_SOFT_RESET = b'\x80\x5D'
ICP_READ_ID_REG = b'\xEF\xC8'
ICP_TAKE_LOW_NOISE_MEASUREMENT = b'\x58\xE0'        # Pressure first, then temperature

ICP_ID_REG_VALUE = 49
ICP_ID_BITS = 0x3F
ICP_ID_READ_BYTES = 3
ICP_SOFT_RESET_DELAY = 0.01         # Safe number of seconds to wait after a soft reset (actually 170 usec)
ICP_DELAY_WRITE_TO_READ = 0.095     # Safe number of seconds (min) after writing before reading (0.0945 guaranteed)

ALTIMETER_FILTER_LEN = 3
ALTIMETER_SAMPLE_PERIOD = 250       # Number of milliseconds between samples.

# Shift the altim output to be somewhat more readable and with hope that 0 is somewhat close to sea level.
ALTIMETER_READABILITY_VALUE = 45250
