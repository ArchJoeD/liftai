#! /usr/bin/python3

import utilities.common_constants as common_constants


class Vibration:
    def process_event(self, session, event, state_info):
        vibration_state_info = state_info[common_constants.PROB_TYPE_VIBRATION]

        state_info[common_constants.PROB_TYPE_VIBRATION].update(vibration_state_info)
        return state_info

    # Returns the default state for the shutdown detector in JSON format.
    @staticmethod
    def get_default_state():
        return {
            common_constants.PROB_TYPE_VIBRATION: {
                common_constants.PROB_VIBRATION_STATUS: common_constants.PROB_VIBRATION_NORMAL
            }
        }
