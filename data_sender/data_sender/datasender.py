import json
import os
import logging
import subprocess
import zlib
import time
import urllib.parse
from datetime import datetime
from subprocess import PIPE, Popen

import requests

from data_sender import constants
from utilities import common_constants, device_configuration
from utilities.db_utilities import session_scope, BankTrip, DataToSend, RoaWatchRequest
from utilities.wpa_supplicant_manager import WPASupplicantManager


logger = logging.getLogger("data_sender")
datasent_logger = logging.getLogger("datasent")
datareceived_logger = logging.getLogger("datareceived")


class LiftAIDataSender:
    @staticmethod
    def is_running_zerotier():
        try:
            with Popen(
                ["/bin/systemctl", "status", "zerotier-one"], stdin=PIPE, stdout=PIPE
            ) as p:
                for _ in range(100):
                    line = p.stdout.readline()
                    if not line and p.returncode is not None:
                        return False
                    if b"active (running)" in line:
                        return True
                return False
        except Exception as e:
            logger.exception("is_running_zerotier() got an exception: ({0})".format(e))
            return False

    def __init__(self, dsn):
        self.dsn = dsn
        self.bRunning = True

    def post_data(self, url, payload):
        with requests.Session() as s:
            data = json.dumps(payload).encode()
            headers = {
                "Content-Type": "application/json",
                "Content-Encoding": "gzip",
                "Content-Length": str(len(data)),
            }
            gzip_data = zlib.compress(data)
            req = requests.Request(
                method="POST", url=url, headers=headers, data=gzip_data
            )
            prepped = req.prepare()
            response = s.send(prepped, timeout=180)
            response.raise_for_status()  # Raise HTTPError for anything other than a 200 response
            return response

    def send_data(self, session, url_base):
        rows = (
            session.query(DataToSend)
            .filter(DataToSend.flag == False)
            .order_by(DataToSend.timestamp.asc())
            .limit(4)
        )
        for row in rows:

            try:  # send HTTP POST
                url = urllib.parse.urljoin(url_base, row.endpoint)
                response = self.post_data(url, row.payload)
            except Exception as e:
                if (
                    "ConnectionError" not in str(e)
                    and "HTTPError" not in str(e)
                    and "Failed to establish a new connection" not in str(e)
                ):
                    logger.error(
                        "HTTP post got an unexpected exception, raising it... {0}".format(
                            e
                        )
                    )
                    raise e

                # Network connection problem of some sort.
                if not row.resend:
                    logger.debug("Failed to send non-essential message")
                    datasent_logger.debug(
                        "Failed to send non-essential payload: {0}".format(
                            json.dumps(row.payload)
                        )
                    )
                    self._mark_as_done(session, row, False)
                else:
                    logger.info("Failed to send msg which must be sent later.")

                time.sleep(constants.FAILURE_EXTRA_SLEEP_SECONDS)
                continue

            # 200 response here
            payload_string = json.dumps(row.payload)
            datasent_log_text = "endpoint: {0},  status: {1},   payload {2}".format(
                row.endpoint, response.status_code, payload_string
            )

            # Notifications are higher importance than everything else.
            if row.endpoint == common_constants.NOTIFICATION_ENDPOINT:
                datasent_logger.info(datasent_log_text)
            else:
                datasent_logger.debug(datasent_log_text)
            datareceived_log_text = "endpoint - {0}, response {1}".format(
                row.endpoint, response.text
            )
            datareceived_logger.debug(datareceived_log_text)

            try:
                response_text = (
                    response.text
                    if not (response.text is "" or response.text is None)
                    else "{}"
                )
                response_data = json.loads(response_text)
                self._process_response_commands(session, response_data, row.timestamp)
            except:
                logger.error("Bad json received from cloud: ", response.text)
                time.sleep(constants.FAILURE_EXTRA_SLEEP_SECONDS)

            self._mark_as_done(session, row, True)
            time.sleep(constants.SLEEP_BETWEEN_POST_SECONDS)

    def run_forever(self):
        upload_url = (
            os.environ[constants.URL_ENV_VAR_NAME]
            if constants.URL_ENV_VAR_NAME in os.environ
            else constants.DEFAULT_UPLOAD_URL_BASE
        )
        url_base = urllib.parse.urljoin(upload_url, constants.API_VERSION)
        logger.debug("Using URL: {0}".format(url_base))

        try:
            while self.bRunning:
                with session_scope() as session:
                    self.send_data(session, url_base)
                time.sleep(constants.SLEEP_BETWEEN_LOOP_SECONDS)
            self._graceful_shutdown()

        except Exception as e:
            logger.exception("Exception data_sender loop: {0}".format(e))
            self._graceful_shutdown()
            raise e

    def _mark_as_done(self, session, row, success):
        row.flag = True
        row.success = success
        session.commit()

    # OS Sends us a signal to terminate.
    def stop(self, signum, frame):
        self.bRunning = False

    def _graceful_shutdown(self):
        # When stopping, always make it clear this was not a power failure in the elevator.
        reboot_info_file = open(constants.REBOOT_INFO, "w")
        reboot_info_file.write("exception in data_sender main")
        reboot_info_file.close()

    def _manage_wifi(self, rsp_json):
        logger.info("Backend passed WiFi parameter.")
        wifi_blob = rsp_json["config"]["wifi"]
        try:
            wifi_enabled = wifi_blob["enabled"]
            wifi_ssid = wifi_blob.get("ssid", None)
            wifi_password = wifi_blob.get("pw", None)
        except Exception as e:
            msg = "Malformed WiFi configuration JSON response from server: {}".format(e)
            logger.error(msg)
        else:
            wpa = WPASupplicantManager()
            if wifi_enabled:
                logger.info("Enabling WiFi.")
                wpa.enable_wifi(wifi_ssid, wifi_password)
            else:
                logger.info("Disabling WiFi.")
                wpa.disable_wifi()

    def _process_response_commands(self, session, rsp_json, ping_datetime):
        if "cmd" in rsp_json.keys():
            cmds = rsp_json["cmd"]
            for key in cmds:
                if key == "ssh":
                    bRun = False
                    if cmds["ssh"] == "EN" and not self.is_running_zerotier():
                        ssh_cmd = "start"
                        ssh_cmd2 = "enable"
                        bRun = True
                    elif cmds["ssh"] == "DN" and self.is_running_zerotier():
                        ssh_cmd = "stop"
                        ssh_cmd2 = "disable"
                        bRun = True

                    if bRun:
                        # This runs fast, we can wait for it to finish.
                        subprocess.run(
                            ["sudo", "/bin/systemctl", ssh_cmd, "zerotier-one"]
                        )
                        subprocess.run(
                            ["sudo", "/bin/systemctl", ssh_cmd2, "zerotier-one"]
                        )

                        if ssh_cmd2 == "disable":
                            subprocess.run(
                                ["sudo", "rm", "/var/lib/zerotier-one/identity.secret"]
                            )
                            subprocess.run(
                                ["sudo", "rm", "/var/lib/zerotier-one/identity.public"]
                            )

                if key == "roaWatch":
                    if cmds["roaWatch"]:
                        roa_watch_request = RoaWatchRequest(
                            request_time=datetime.now(),
                            enabled=True,
                        )
                        session.add(roa_watch_request)
                    else:
                        # Disable all records, although we could just disable the ones in the last N minutes.
                        session.query(RoaWatchRequest).update({
                            RoaWatchRequest.enabled: False
                        })

                    session.commit()

        if all(key in rsp_json.keys() for key in ("bankTrips", "bankElevators")):
            bank_trip = BankTrip(
                timestamp=ping_datetime,
                bank_trips=rsp_json["bankTrips"],
                bank_elevators=rsp_json["bankElevators"],
            )
            session.add(bank_trip)
            session.commit()

        if rsp_json.get("config", False):
            is_dict = type(rsp_json["config"]) == dict
            has_wifi = rsp_json["config"].get("wifi", False)
            if is_dict and has_wifi:
                self._manage_wifi(rsp_json)

            try:
                config = rsp_json["config"]
                device_configuration.DeviceConfiguration.update_config_file(config)

            except Exception as e:
                logger.error(
                    "Unable to write configuration data to {}, {}".format(
                        common_constants.CONFIG_FILE_NAME, e
                    )
                )
