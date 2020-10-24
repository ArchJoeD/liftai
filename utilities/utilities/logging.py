import logging
import os
from logging.handlers import RotatingFileHandler

from utilities import common_constants


def create_rotating_log(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if __debug__:
        log_folder = '/tmp/'
    else:
        log_folder = common_constants.LOG_FILES_FOLDER
    log_filename = os.path.join(log_folder, "{}.log".format(name))
    rh = RotatingFileHandler(log_filename, maxBytes=10*1024*1024,
                             backupCount=5)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    rh.setFormatter(formatter)
    logger.addHandler(rh)

    return logger
