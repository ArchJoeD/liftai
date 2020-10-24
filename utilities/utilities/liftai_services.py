
# TODO: Expand this to provide a mapping between service names, our applications, associated log file names, whatever.

class LiftAIServices:
    services_list = [
        "accelerometer",
        "altimeter",
        "anomalydetector",
        "audiorecorder",
        "bankstoppage",
        "datasender",
        "elevation",
        "elisha",
        "escalatorstoppage",
        "floordetector",
        "gpio",
        "lowusestoppage",
        "pingcloud",
        "reportgenerator",
        "roawatch",
        "standalonestoppage",
        "trips",
        "vibration",
    ]

    @staticmethod
    def get_list():
        return LiftAIServices.services_list
