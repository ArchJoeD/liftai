from utilities import common_constants
from utilities.db_utilities import Trip, FloorMap
from utilities.device_configuration import DeviceConfiguration


def can_use_floor_data(session):
    """
    Helps apps decide if the floor data is safe to trust

    Returns true if the device is configured with a floor count AND
    has a floor map and EITHER the floor map has as many floors registered as the floor count OR
    we have passed the calculated threshold of trips based on the number of floors.

    Otherwise returns false

    The calculated threshold of trips only takes into account trips since the most recent floor map was started
    """
    floor_count = DeviceConfiguration.get_floor_count()

    if floor_count is None:
        return False

    floor_map = FloorMap.get_lastest_map(session)

    if not floor_map:
        return False

    if floor_map.num_floors == floor_count:
        return True

    num_trips = Trip.filter_trips_after(
        session.query(Trip), floor_map.start_time
    ).count()

    min_trips_to_trust_floor_data = (
        floor_count * common_constants.MIN_TRIPS_PER_FLOOR_TO_TRUST_DATA
    )

    return num_trips >= min_trips_to_trust_floor_data

