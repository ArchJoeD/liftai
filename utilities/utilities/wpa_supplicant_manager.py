from subprocess import PIPE, Popen
import logging

logger = logging.getLogger(__name__)

WPA_SUPPLICANT_CONFIG = '/etc/wpa_supplicant/wpa_supplicant.conf'
WPA_SUPPLICANT_BASE_CONFIG = '/etc/liftai/wpa_supplicant.conf'

class WPASupplicantManager(object):
    def _get_network_string(self):
        return """
network={{
	ssid="{}"
	psk="{}"
}}
""".format(self.ssid, self.password)

    def _run_cmd(self, cmd_list):
        try:
            p = Popen(cmd_list, stdin=PIPE, stdout=PIPE)
            # Wait for subproc to finish:
            p.communicate()[0]
            if p.returncode is not None and p.returncode != 0:
                raise Exception("Command exited unsuccessfully: {}".format(p.stderr))
        except Exception as e:
            logger.error('Error handling command: {}'.format(e))
            raise e

    def reload_wifi(self):
        try:
            # Reload WPA supplicant via cli
            self._run_cmd(['wpa_cli', '-i', 'wlan0', 'reconfigure'])
        except Exception as e:
            logger.error('Error reloading WiFi: {}'.format(e))
            return

    def enable_wifi(self, ssid, password):
        self.ssid = ssid
        self.password = password
        with open(WPA_SUPPLICANT_BASE_CONFIG) as base_conf_file:
            base_str = base_conf_file.read()
            network_str = self._get_network_string()

        with open(WPA_SUPPLICANT_CONFIG, 'w') as wpa_conf_file:
            wpa_conf_file.write(base_str + network_str)

        self.reload_wifi()

    def disable_wifi(self):
        try:
            # Copy blank file first
            self._run_cmd(['cp', WPA_SUPPLICANT_BASE_CONFIG, WPA_SUPPLICANT_CONFIG])
        except Exception as e:
            logger.error('Error disabling WiFi: {}'.format(e))

        self.reload_wifi()
