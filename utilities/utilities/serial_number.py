import subprocess
import utilities.common_constants as common_constants

class SerialNumber:

    @staticmethod
    def get():
        bashCommand = "cat {0} | sed -z 's/\\n//'".format(common_constants.HOSTNAME_FILE)
        return subprocess.check_output(['bash', '-c', bashCommand]).decode("utf-8")
