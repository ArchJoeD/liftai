#!/usr/bin/env python3

import logging
import os
import unittest

from gpio.import_gpio import is_real_device

# Universal test customization setup here
# by changing environment variables used by utilities.common_constants
os.environ["LIFTAI_STORAGE_FOLDER"] = "/tmp"
os.environ["LIFTAI_CONFIG_FILE_NAME"] = "/tmp/liftai_test_config_file.json"
os.environ["LIFTAI_HOSTNAME_FILE"] = "/tmp/liftai_hostname"
os.environ["LIFT_AI_PROB_DETAILS_SYSTEM"] = '{"system":"unit test source"}'
os.environ["LIFTAI_HW_CONFIG_FILE_NAME"] = "/tmp/hwconfig.json"

if not is_real_device:
    os.environ["LIFT_AI_TIME_SCALE_FACTOR"] = "0.001"

from anomaly_detector.tests import *
from anomaly_detector.tests_gap_detector import *
from audio_recorder.tests import *
from altimeter.tests import *
from bank_stoppage.tests import *
from data_sender.tests import *
from elevation.tests import *
from elisha.tests import *
from elisha.tests_anomaly import *
from elisha.shutdown_tests import *
from elisha.notif_tests import *
from floor_detector.tests import *
from gpio.tests import *
from low_use_stoppage.tests import *
from ping_cloud.tests import *
from report_generator.tests import *
from standalone_stoppage.tests import *
from utilities.tests import *
from roawatch.tests import *
from trips.tests import *


logging.disable(logging.CRITICAL)

if __name__ == "__main__":
    unittest.main()
