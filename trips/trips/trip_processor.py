import os
import sys
import json
import logging
import csv
import pickle
from datetime import datetime, timedelta
from collections import namedtuple, deque
import itertools
from functools import reduce

import pytz
from scipy import stats
import numpy as np
from scipy.signal import welch
from sqlalchemy import text

import trips.constants as constants
import utilities.common_constants as common_constants
from utilities.db_utilities import Acceleration, Trip


# We need X values for the linear regression, so we just use 1, 2, 3, 4...
fake_altim_x_axis_values = [*range(constants.ALTIM_WINDOW_LEN)]

logger = logging.getLogger(__name__)


def reducer(acc, cur):
    acc[0].append(cur.x)
    acc[1].append(cur.y)
    acc[2].append(cur.z)
    return acc


sensor_fetch_sql = """
-- Get interleaved accelerometer and altimeter data
SELECT
  timestamp,
  NULL as x_data,
  NULL as y_data,
  NULL as z_data,
  altitude_x16
FROM altimeter_data
WHERE timestamp >= :last_timestamp AND timestamp < NOW() - INTERVAL '1 second'
UNION
SELECT
  timestamp,
  x_data,
  y_data,
  z_data,
  NULL as altitude_x_16
FROM accelerometer_data
-- Avoid fetching data from less than 1 sec ago to avoid possible missed sample.
-- The altim vs accel clocks can be slightly different.
WHERE timestamp > :last_timestamp AND timestamp < NOW() - INTERVAL '1 second'
AND z_data IS NOT NULL  -- migrating from old system to new system, existing data can be null
ORDER BY timestamp ASC
LIMIT 2000;      -- avoid cases of fetching massive backlog.
"""

# Used for holding accelerometer samples
AccelSample = namedtuple("AccelSample", ["timestamp", "x", "y", "z", "altim"])

# Used for holding chartable data
ResultData = namedtuple("ResultData", ["timestamp", "z", "altitude"])

TripData = namedtuple(
    "TripData",
    ["prelim_sot", "prelim_eot", "midpoint", "rough_start_accel", "rough_end_accel"],
)

AltimDetectedStart = namedtuple(
    "AltimDetectedStart", ["direction", "start_timestamp", "starting_elevation"]
)

AltimDetectedEnd = namedtuple("AltimDetectedEnd", ["end_timestamp", "ending_elevation"])

AltimeterReset = namedtuple("AltimeterReset", [])

InsufficientAccelSamples = namedtuple("InsufficientAccelSamples", [])

IncrSavePoint = namedtuple("IncrSavePoint", [])

RecordMissedTrip = namedtuple("RecordMissedTrip", ["elevation_change", "trip_start"])


class TripBoundsNotFoundException(Exception):
    pass


class TripProcessor:
    session = None
    last_timestamp = None
    result_data = None

    # This is a fixed length FIFO buffer for linear regression.
    altim_window = None
    # This FIFO needs to hold more samples than the longest possible trip.
    accel_data = None

    # MARK: State Variables
    altim_detected_trip_in_progress = None
    trip_direction = None
    # We need accel data beyond the end of the altimeter declared trip
    # because the ending acceleration will probably go beyond it.
    extra_accel_samples_needed_count = 0
    # The altimeter processing sends this flag to the accelerometer processing
    altim_detected_trip_end = False
    # Keep the most recent altimeter reading around for the accelerometer FIFO
    last_altim_value = None

    trip_starting_elevation = None
    trip_ending_elevation = None
    altim_trip_start_timestamp = None
    altim_trip_end_timestamp = None
    save_point_counter = None
    # END MARK: State Variables

    last_timestamp_path = None
    chart_file_path = None

    def __init__(self, session):
        self.session = session
        # This is used for producing a readable output csv file.
        self.result_data = []
        self.last_timestamp_path = os.path.join(
            common_constants.STORAGE_FOLDER, "trips_last_timestamp.pkl"
        )
        self.chart_file_path = os.path.join(
            common_constants.STORAGE_FOLDER, "last_trip.csv"
        )
        self.altim_window = deque(maxlen=constants.ALTIM_WINDOW_LEN)
        self.accel_data = deque(maxlen=constants.ACCEL_WINDOW_LEN)

        self.altim_detected_trip_in_progress = False
        self.trip_direction = None
        self.altim_trip_start_timestamp = None
        self.altim_trip_end_timestamp = None
        self.save_point_counter = 0
        self.last_timestamp = self._get_last_timestamp_processed(
            self.last_timestamp_path
        )
        # If we're so far behind in processing data that we've already discarded the accel data, start at a sane point.
        if datetime.now() - self.last_timestamp > timedelta(
            minutes=common_constants.MAX_MINUTES_OF_ACCEL_DATA_IN_DB
        ):
            self.last_timestamp = datetime.now() - timedelta(
                minutes=(common_constants.MAX_MINUTES_OF_ACCEL_DATA_IN_DB - 5)
            )
        self.last_altim_value = 0  # (start with anything but None)

    @staticmethod
    def _sensor_window_sum(sensor_win, start_idx, end_idx, col_name):
        """
        sensor_win is a list of named tuple with a column named col_name
        This is NOT inclusive of end_idx.
        """
        result = 0.0
        for k in range(start_idx, end_idx):
            result += getattr(sensor_win[k], col_name)
        return result

    @staticmethod
    def _find_acceleration_start_and_end(buffer, window_start, window_end, accel_total):
        """
        Find the smallest start and end indexes of the window that contains nearly all of the
        total acceleration in the overall window.
        """
        # Do all the calculations as positive acceleration.
        sign = np.sign(accel_total)

        # Each side of the window can only be reduced by half of the total threshold.
        half_threshold = 1 - (1 - constants.ACCEL_PERCENT_THRESH) / 2
        start_threshold = accel_total * half_threshold * sign
        end_threshold = accel_total * constants.ACCEL_PERCENT_THRESH * sign

        logger.debug(
            "Looking for acceleration in {0} to {1} with max value {2}...".format(
                window_start, window_end, end_threshold
            )
        )
        # Look for the start of the window...
        index = window_start
        best_idx_so_far = window_start
        while index < window_end:
            # We don't use abs() here to avoid going in the wrong direction.
            window_sum = (
                TripProcessor._sensor_window_sum(buffer, index, window_end, "z") * sign
            )
            if window_sum >= start_threshold:
                best_idx_so_far = index
            index += 1
        acc_start = best_idx_so_far

        # Look for the end of the window...
        index = window_end
        best_idx_so_far = window_end
        while index > acc_start:
            # We don't use abs() here to avoid going in the wrong direction.
            window_sum = (
                TripProcessor._sensor_window_sum(buffer, acc_start, index, "z") * sign
            )
            if window_sum >= end_threshold:
                best_idx_so_far = index
            index -= 1
        acc_end = best_idx_so_far

        logger.debug(
            "...found acceleration index range of {0} to {1}".format(acc_start, acc_end)
        )
        return acc_start, acc_end

    @staticmethod
    def _write_out_chart_data(chart_data):
        file = os.path.join(common_constants.STORAGE_FOLDER, constants.CSV_FILE_NAME)
        with open(file, "w", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_NONE)
            for result_row in chart_data:
                writer.writerow(result_row)

    @staticmethod
    def _get_vibration_for_sample_interval(lst, col, start_index, end_index):
        # FFTs need an even number of samples, so adjust it to an even number.
        adjusted_end_index = start_index + ((end_index - start_index) & 0xFFFFFE)
        sample_array = [
            getattr(row, col) for row in lst[start_index:adjusted_end_index]
        ]
        nparray = np.array(sample_array)
        freqs, power_spectral_density = welch(
            nparray,
            fs=constants.MILLISEC_PER_SEC / constants.ACCEL_SAMPLE_PERIOD,
            nperseg=len(nparray),
        )

        bins = [0.0] * len(constants.fft_bin_boundaries)
        bin_id = 0
        for i in range(len(freqs)):
            if freqs[i] > constants.fft_bin_boundaries[bin_id]:
                bins[bin_id] = round(bins[bin_id])
                bin_id += 1
            bins[bin_id] += power_spectral_density[i]

        bins[bin_id] = round(bins[bin_id])
        return bins

    def _save_last_timestamp(self):
        with open(self.last_timestamp_path, "wb") as f:
            pickle.dump(self.last_timestamp, f)

    @staticmethod
    def _get_last_timestamp_processed(last_timestamp_path):
        # Default to now if we don't know how far back to go
        last_timestamp = datetime.now()

        if (
            os.path.isfile(last_timestamp_path)
            and os.stat(last_timestamp_path).st_size != 0
        ):
            for i in range(0, 3):  # EN-680 fix
                try:
                    with open(last_timestamp_path, "rb") as f:
                        last_timestamp = pickle.load(f)
                        logger.debug(
                            "restoring last timestamp: {0}".format(last_timestamp)
                        )
                        break
                except Exception as ex:
                    logger.error(
                        "Exception getting pickle last timestamp from storage on pass {0}: {1}".format(
                            i, str(ex)
                        )
                    )
        else:
            logger.info(
                "No storage info or it's corrupted, so we write the initial default out to storage."
            )

        return last_timestamp

    def _record_missed_trip(self, elevation_change, trip_start):
        if abs(elevation_change) < constants.MIN_TRIP_ELEVATION:
            logger.debug(
                "Not enough elevation change to report a missed trip, {0} at {1}".format(
                    elevation_change, trip_start
                )
            )
            return

        details = {common_constants.EVENT_DETAILS_ELEVATION_CHANGE: elevation_change}
        query = (
            "INSERT INTO events (occurred_at, detected_at, source, event_type, event_subtype, details) "
            "VALUES (:occurred_at, :detected_at, :source, :event_type, :event_subtype, :details)"
        )
        params = {
            "occurred_at": trip_start,
            "detected_at": datetime.now(),
            "source": common_constants.EVENT_SOURCE_TRIP_PROCESSOR,
            "event_type": common_constants.EVENT_TYPE_ELEVATION,
            "event_subtype": common_constants.EVENT_SUBTYPE_MISSING_TRIP,
            "details": json.dumps(details),
        }
        self.session.execute(text(query), params)
        self.session.commit()

    def look_for_trips(self):
        batch_of_data = self._get_next_batch_of_data()

        for row in batch_of_data:
            self.last_timestamp = row.timestamp

            if self._is_altim_row(row):
                self.last_altim_value = row.altitude_x16

            self._add_row_to_result_data(row)

            try:
                self.process_action(self._process_row(row))
            except TripBoundsNotFoundException as e:
                logger.error(e)
                # This seems confusing but all it means is we want to retry the row if the exception occurs
                # It will not except again on a second call because of resetting of state of the trip_end_detected
                self.process_action(self._process_row(row))

            if not self.altim_detected_trip_in_progress:
                # We should only save the last timestamp if we're not currently processing a trip.
                # If this stops during a trip, we should start back up processing the time before that trip started.
                self.process_action(IncrSavePoint())
                if self.save_point_counter >= constants.SAVE_POINT_COUNT:
                    self._save_last_timestamp()

    def process_action(self, action):
        if (
            __debug__
            and action is not None
            and not (
                isinstance(action, InsufficientAccelSamples)
                or isinstance(action, IncrSavePoint)
            )
        ):
            print("Processing action: {action}".format(action=action))

        # Explicit none check is needed for empty namedtuples
        if action is not None:
            if isinstance(action, AltimDetectedStart):
                logger.debug(
                    "Altimeter start of trip found, {0}. direction = {1}".format(
                        self.last_timestamp, action.direction
                    )
                )
                self.altim_detected_trip_in_progress = True
                self.trip_direction = action.direction
                self.altim_trip_start_timestamp = action.start_timestamp
                self.trip_starting_elevation = action.starting_elevation

            elif isinstance(action, AltimDetectedEnd):
                self.altim_detected_trip_in_progress = False

                elevation_change = (
                    action.ending_elevation - self.trip_starting_elevation
                )
                # An odd situation can happen where air pressure briefly goes up right before a trip
                # down.  adbd83fe is one example.  The direction should be the elevation change dir.
                actual_direction = np.sign(elevation_change)
                if actual_direction != self.trip_direction:
                    logger.info("Unusual situation: trip ended in the other direction")
                    self.trip_direction = actual_direction

                logger.debug(
                    "Altimeter end of trip found, {0}, elev diff = {1}".format(
                        self.last_timestamp, elevation_change
                    )
                )

                self.altim_trip_end_timestamp = action.end_timestamp

                # Signal to the accelerometer section to start looking for the trip...
                self.altim_detected_trip_end = True

                # ...and wait roughtly this many samples beyond the trip.
                self.extra_accel_samples_needed_count = constants.TRIP_END_COUNT_THRESH
                self.trip_ending_elevation = action.ending_elevation

            elif isinstance(action, AltimeterReset):
                self.altim_detected_trip_in_progress = False

            elif isinstance(action, InsufficientAccelSamples):
                if self.extra_accel_samples_needed_count > 0:
                    self.extra_accel_samples_needed_count = (
                        self.extra_accel_samples_needed_count - 1
                    )

                if self.extra_accel_samples_needed_count == 0:
                    # Now that we have enough data beyond the trip, process the trip data.
                    self.altim_detected_trip_end = False
                    self.process_action(self._process_accel_data())

            elif isinstance(action, TripData):
                self._process_and_save_trip_data(action)

                # Remove the old trip and start capturing the next one.
                self.result_data = []

            elif isinstance(action, IncrSavePoint):
                self.save_point_counter = self.save_point_counter + 1

            elif isinstance(action, RecordMissedTrip):
                self._record_missed_trip(action.elevation_change, action.trip_start)

    def _get_next_batch_of_data(self):
        return self.session.execute(
            text(sensor_fetch_sql), {"last_timestamp": self.last_timestamp}
        ).fetchall()

    @staticmethod
    def _get_vibration_json(x_psd, y_psd, z_psd):
        """
        Convert various vibration data into JSON for machine learning consumption, not user facing.
        psd = power spectral density, similar to FFT
        """
        result = {
            "x_psd": TripProcessor._convert_one_axis_vibration_to_json(x_psd),
            "y_psd": TripProcessor._convert_one_axis_vibration_to_json(y_psd),
            "z_psd": TripProcessor._convert_one_axis_vibration_to_json(z_psd),
        }

        return result

    @staticmethod
    def _convert_one_axis_vibration_to_json(axis_vib):
        result = {}
        bin_number = 0
        for f in axis_vib:
            result["f{0}".format(bin_number)] = f
            bin_number += 1
        return result

    @staticmethod
    def _convert_to_fpm(sum_of_raw_accel):
        return round(
            (constants.GRAVITY_MPS2 / constants.DEFAULT_GRAVITY)
            * constants.MPS_TO_FPM_CONVERSION
            * (constants.ACCEL_SAMPLE_PERIOD / constants.MILLISEC_PER_SEC)
            * sum_of_raw_accel,
            2,
        )

    @staticmethod
    def _convert_to_sum_of_raw_accel(speed_fpm):
        return round(
            (speed_fpm / constants.MPS_TO_FPM_CONVERSION)
            * (constants.DEFAULT_GRAVITY / constants.GRAVITY_MPS2)
            * (constants.MILLISEC_PER_SEC / constants.ACCEL_SAMPLE_PERIOD),
            2,
        )

    @staticmethod
    def _convert_raw_accel_to_milligs(raw_accel):
        return raw_accel * (1000.0 / constants.DEFAULT_GRAVITY)

    @staticmethod
    def _convert_milligs_to_raw_accel(millig):
        return millig * (constants.DEFAULT_GRAVITY / 1000.0)

    @staticmethod
    def _convert_raw_accel_slope_to_meters_per_sec_cubed(raw_accel_slope):
        return (
            raw_accel_slope
            * (constants.GRAVITY_MPS2 / constants.DEFAULT_GRAVITY)
            * (1000 / common_constants.ACCELEROMETER_SAMPLING_PERIOD)
        )

    @staticmethod
    def _convert_meters_per_sec_cubed_to_raw_accel_slope(jerk):
        return (
            jerk
            * (constants.DEFAULT_GRAVITY / constants.GRAVITY_MPS2)
            * (common_constants.ACCELEROMETER_SAMPLING_PERIOD / 1000)
        )

    def _get_peak2peak_vibration(self, start_index, end_index):
        """
        Compute peak-to-peak vibration data (milli-g units) for customer facing vibration values.
        """
        vib_x = []
        vib_y = []
        vib_z = []
        # Use small, fixed size windows to filter out very low frequencies
        # Use lots of overlap to avoid missing peaks.
        for window_start in range(
            start_index, end_index + 1, constants.P2P_VIBRATION_WINDOW_SIZE >> 2
        ):
            current_window = list(
                itertools.islice(
                    self.accel_data,
                    window_start,
                    window_start + constants.P2P_VIBRATION_WINDOW_SIZE,
                )
            )
            items_xyz = reduce(reducer, current_window, ([], [], []))
            max_x, max_y, max_z = [max(items) for items in items_xyz]
            min_x, min_y, min_z = [min(items) for items in items_xyz]
            vib_x.append(max_x - min_x)
            vib_y.append(max_y - min_y)
            vib_z.append(max_z - min_z)
        # NEII "typical" is the 95th percential of peak-to-peak range within a trip.
        typical_x = np.percentile(vib_x, 95)
        typical_y = np.percentile(vib_y, 95)
        typical_z = np.percentile(vib_z, 95)
        largest_x = max(vib_x)
        largest_y = max(vib_y)
        largest_z = max(vib_z)
        vibration = {
            "p2p_x_95": round(
                TripProcessor._convert_raw_accel_to_milligs(typical_x), 2
            ),
            "p2p_y_95": round(
                TripProcessor._convert_raw_accel_to_milligs(typical_y), 2
            ),
            "p2p_z_95": round(
                TripProcessor._convert_raw_accel_to_milligs(typical_z), 2
            ),
            "p2p_x_max": round(
                TripProcessor._convert_raw_accel_to_milligs(largest_x), 2
            ),
            "p2p_y_max": round(
                TripProcessor._convert_raw_accel_to_milligs(largest_y), 2
            ),
            "p2p_z_max": round(
                TripProcessor._convert_raw_accel_to_milligs(largest_z), 2
            ),
        }
        return vibration

    def _get_jerk(self, start_index, end_index):
        max_raw_slope = 0
        fake_x_axis_values = [*range(constants.NEII_JERK_WINDOW_SIZE)]
        # Use overlapping windows so we don't miss a jerk that spans two windows.
        # NEII compliant values would require a 10 Hz low pass filter (not implemented yet).
        for window_start in range(
            start_index, end_index + 1, (constants.NEII_JERK_WINDOW_SIZE >> 2)
        ):
            current_window = list(
                itertools.islice(
                    self.accel_data,
                    window_start,
                    window_start + constants.NEII_JERK_WINDOW_SIZE,
                )
            )
            _, _, z_values = reduce(reducer, current_window, ([], [], []))
            slope, _, _, _, _ = stats.linregress(fake_x_axis_values, z_values)
            max_raw_slope = max(max_raw_slope, abs(slope))

        jerk = TripProcessor._convert_raw_accel_slope_to_meters_per_sec_cubed(
            max_raw_slope
        )
        return {"jerk": round(jerk, 2)}

    def _save_acceleration(
        self, start_time, end_time, is_start, is_positive, vibration
    ):
        acc = Acceleration.init_with_audio(
            self.session,
            start_time=start_time.replace(tzinfo=pytz.utc),
            duration=round((end_time - start_time).total_seconds() * 1000),
            is_start_of_trip=is_start,
            is_positive=is_positive,
            vibration=vibration,
            vibration_schema=common_constants.ACCEL_VIBRATION_SCHEMA,
        )
        self.session.add(acc)
        self.session.commit()
        return acc.id

    def _save_trip(
        self,
        start_time,
        end_time,
        is_up,
        elevation_change,
        speed,
        vibration,
        starting_accel_id,
        ending_accel_id,
    ):
        trip = Trip.init_with_audio(
            self.session,
            start_accel=starting_accel_id,
            end_accel=ending_accel_id,
            start_time=start_time.replace(tzinfo=pytz.utc),
            end_time=end_time.replace(tzinfo=pytz.utc),
            is_up=is_up,
            elevation_change=elevation_change,
            elevation_processed=True,
            speed=speed,
            vibration_schema=common_constants.TRIP_VIBRATION_SCHEMA,
            vibration=vibration,
        )
        self.session.add(trip)
        self.session.commit()

    @staticmethod
    def _is_altim_row(row):
        return True if row.altitude_x16 else False

    def _add_row_to_result_data(self, row):
        if self.result_data == []:
            # We need to add a first row with initialized values in order to look back at previous row later.
            self.result_data.append(
                ResultData(
                    timestamp=row.timestamp,
                    z=0.0,
                    altitude=0.0,
                )
            )

        # Keep a running FIFO for samples before a trip happened.
        if (not self.altim_detected_trip_in_progress) and len(
            self.result_data
        ) > constants.PRE_TRIP_CHART_SAMPLES:
            self.result_data.pop(0)

        result = (
            ResultData(
                timestamp=row.timestamp,
                z=self.result_data[
                    -1
                ].z,  # Carry the previous z_data value forward from prev row
                altitude=float(row.altitude_x16),
            )
            if TripProcessor._is_altim_row(row)
            else ResultData(
                timestamp=row.timestamp,
                z=float(row.z_data),
                altitude=self.last_altim_value,
            )
        )
        self.result_data.append(result)

    def _process_altim_row(self, row):
        result = None

        self.altim_window.append((row.timestamp, row.altitude_x16))
        if len(self.altim_window) < constants.ALTIM_WINDOW_LEN:
            # Not enough data yet
            return None

        # Run a linear regression on the data.
        y_axis_values = [float(a[1]) for a in self.altim_window]
        slope, _, _, _, stderr = stats.linregress(
            fake_altim_x_axis_values, y_axis_values
        )

        if self.altim_detected_trip_in_progress:
            # Log details while we're in a trip.
            logger.debug(
                "{0},  Slope = {1},  stderr = {2}, {3}".format(
                    self.altim_window[-1][0],
                    round(slope, 2),
                    round(stderr, 2),
                    y_axis_values,
                )
            )

        # Detected start of trip
        if (
            (not self.altim_detected_trip_in_progress)
            and abs(slope) >= constants.START_TRIP_SLOPE_THRESH
            and stderr < constants.STDERR_MAX_THRESH
            # The next line is needed so that we can not transition
            # back to the start state without another action occuring first
            and self.extra_accel_samples_needed_count == 0
        ):
            result = AltimDetectedStart(
                direction=np.sign(slope),
                start_timestamp=self.altim_window[0][0],
                starting_elevation=int(self.altim_window[0][1]),
            )

        # Detected end of trip
        elif (
            self.altim_detected_trip_in_progress
            and abs(slope) < constants.END_TRIP_SLOPE_THRESH
            and stderr < constants.STDERR_MAX_THRESH
        ):
            ending_elevation = int(
                self.altim_window[-1][1]
            )  # The end of the window is the trip end delineation.
            elevation_change = ending_elevation - self.trip_starting_elevation

            if abs(elevation_change) < constants.MIN_TRIP_ELEVATION:
                logger.debug(
                    "Not enough elevation change, {0}.  This is not a trip".format(
                        elevation_change
                    )
                )
                result = AltimeterReset()
            else:
                result = AltimDetectedEnd(
                    # The trip end delineation is where the line first flattens out, which is
                    # at the START of the buffer at this point (not the end).
                    end_timestamp=self.altim_window[0][0],
                    ending_elevation=ending_elevation,
                )

        return result

    def _process_accel_row(self, row):
        # Keep a running FIFO buffer of accel samples.
        self.accel_data.append(
            AccelSample(
                timestamp=row.timestamp,
                x=float(row.x_data),
                y=float(row.y_data),
                z=float(row.z_data),
                altim=self.last_altim_value,
            )
        )

        if not self.altim_detected_trip_end:
            return None

        if self.extra_accel_samples_needed_count > 0:
            return InsufficientAccelSamples()

    def _process_accel_data(self):
        logger.debug(
            "Accel starting to parse data, start time {0}, end time {1}".format(
                self.altim_trip_start_timestamp, self.altim_trip_end_timestamp
            )
        )

        # Find the elevation midpoint of the trip, within the altimeter's start and end points.
        index = 0
        while self.accel_data[index].timestamp < self.altim_trip_start_timestamp:
            index += 1
        # The index is now at the start of the altimeter trip, now find elev midpoint.
        mid_elevation = (self.trip_starting_elevation + self.trip_ending_elevation) / 2
        midpoint = 0
        closest_elev = sys.maxsize  # start with largest possible number
        # Walk through the samples of the trip finding the closest elevation to the midpoint.
        while self.accel_data[index].timestamp <= self.altim_trip_end_timestamp:
            elev = self.accel_data[index].altim
            if abs(elev - mid_elevation) < abs(closest_elev - mid_elevation):
                closest_elev = elev
                midpoint = index
            index += 1

        logger.debug(
            "Accel: midpoint at {0}, elev midpoint= {1}".format(
                self.accel_data[midpoint].timestamp, closest_elev
            )
        )

        # Find the likely actual start of the trip (start of beginning acceleration)
        earliest_start_of_trip_time = self.altim_trip_start_timestamp - timedelta(
            milliseconds=constants.ALTIM_TO_ACCEL_TRIP_START_OFFSET
        )
        prelim_sot = 0
        while (
            prelim_sot < len(self.accel_data)
            and self.accel_data[prelim_sot].timestamp < earliest_start_of_trip_time
        ):
            prelim_sot += 1
        if prelim_sot == len(self.accel_data):
            raise TripBoundsNotFoundException(
                "Can't find start of trip time in the data from {0} to {1}, looking for {2}".format(
                    self.accel_data[0].timestamp,
                    self.accel_data[-1].timestamp,
                    earliest_start_of_trip_time,
                )
            )

        # Find the likely end of the trip
        latest_end_of_trip_time = self.altim_trip_end_timestamp + timedelta(
            milliseconds=constants.ALTIM_TO_ACCEL_TRIP_END_OFFSET
        )
        logger.debug(
            "Accel: bracketing trip from {0} to {1}".format(
                earliest_start_of_trip_time, latest_end_of_trip_time
            )
        )
        prelim_eot = 0
        while (
            prelim_eot < len(self.accel_data)
            and self.accel_data[prelim_eot].timestamp < latest_end_of_trip_time
        ):
            prelim_eot += 1
        if prelim_eot == len(self.accel_data):
            raise TripBoundsNotFoundException(
                "Can't find end of trip time in the data from {0} to {1}, looking for {2}".format(
                    self.accel_data[0].timestamp,
                    self.accel_data[-1].timestamp,
                    latest_end_of_trip_time,
                )
            )

        # Check the sum of all the Z acceleration from a point near the start of the trip to the midpoint.
        rough_start_accel = self._sensor_window_sum(
            self.accel_data, prelim_sot, midpoint, "z"
        )
        if np.sign(rough_start_accel) != self.trip_direction:
            logger.warning(
                "Trip start acceleration was in the wrong direction, {0}, direction = {1}".format(
                    rough_start_accel, self.trip_direction
                )
            )
            return RecordMissedTrip(
                elevation_change=self.trip_ending_elevation
                - self.trip_starting_elevation,
                trip_start=self.altim_trip_start_timestamp,
            )

        logger.debug(
            "Accel: starting accel rough est: {0}".format(round(rough_start_accel))
        )

        # Check the sum of all the Z acceleration from the midpoint to a point near the end of the trip.
        # We include the end point because it's part of the acceleration.  The midpoint goes with ending accel.
        rough_end_accel = self._sensor_window_sum(
            self.accel_data, midpoint, prelim_eot + 1, "z"
        )
        if np.sign(rough_end_accel) == self.trip_direction:
            logger.warning(
                "Trip end acceleration was in the wrong direction, {0}, direction = {1}".format(
                    rough_end_accel, self.trip_direction
                )
            )
            return RecordMissedTrip(
                elevation_change=self.trip_ending_elevation
                - self.trip_starting_elevation,
                trip_start=self.altim_trip_start_timestamp,
            )

        logger.debug(
            "Accel: ending accel rough est: {0}".format(round(rough_end_accel))
        )

        # Does the accelerometer think we have a trip?
        # TODO: Use the trip_direction sign instead of abs val to avoid accels in the wrong dir
        if (
            abs(rough_start_accel) < constants.ACCEL_TRIP_DETECT_THRESH
            or abs(rough_end_accel) < constants.ACCEL_TRIP_DETECT_THRESH
        ):
            logger.warning(
                "Accelerometer failed to detect a trip, total accel = {0}, {1}\n".format(
                    round(rough_start_accel), round(rough_end_accel)
                )
            )
            return RecordMissedTrip(
                elevation_change=self.trip_ending_elevation
                - self.trip_starting_elevation,
                trip_start=self.altim_trip_start_timestamp,
            )

        return TripData(
            prelim_sot=prelim_sot,
            prelim_eot=prelim_eot,
            midpoint=midpoint,
            rough_start_accel=rough_start_accel,
            rough_end_accel=rough_end_accel,
        )

    def _process_row(self, row):
        return (
            self._process_altim_row(row)
            if self._is_altim_row(row)
            else self._process_accel_row(row)
        )

    def _process_and_save_trip_data(self, trip_data):
        # Now find the exact time boundaries of the starting acceleration
        (
            starting_accel_start,
            starting_accel_end,
        ) = self._find_acceleration_start_and_end(
            self.accel_data,
            trip_data.prelim_sot,
            trip_data.midpoint,
            trip_data.rough_start_accel,
        )
        ending_accel_start, ending_accel_end = self._find_acceleration_start_and_end(
            self.accel_data,
            trip_data.midpoint,
            trip_data.prelim_eot,
            trip_data.rough_end_accel,
        )

        # Compute metrics for accelerations
        # Accelerations include the last data point.
        starting_accel_mag = self._sensor_window_sum(
            self.accel_data, starting_accel_start, starting_accel_end + 1, "z"
        )
        ending_accel_mag = self._sensor_window_sum(
            self.accel_data, ending_accel_start, ending_accel_end + 1, "z"
        )
        elevation_change = int(
            self.trip_ending_elevation - self.trip_starting_elevation
        )

        speed_fpm = TripProcessor._convert_to_fpm(
            (abs(starting_accel_mag) + abs(ending_accel_mag)) / 2
        )

        accel_data = list(self.accel_data)

        # Gather all the data and save it into the database.
        x_start_accel_values = self._get_vibration_for_sample_interval(
            accel_data, "x", starting_accel_start, starting_accel_end
        )
        y_start_accel_values = self._get_vibration_for_sample_interval(
            accel_data, "y", starting_accel_start, starting_accel_end
        )
        z_starting_accel_values = self._get_vibration_for_sample_interval(
            accel_data, "z", starting_accel_start, starting_accel_end
        )
        starting_accel_vibration_json = self._get_vibration_json(
            x_start_accel_values, y_start_accel_values, z_starting_accel_values
        )
        starting_p2p_vibration_json = self._get_peak2peak_vibration(
            starting_accel_start, starting_accel_end
        )
        starting_jerk_json = self._get_jerk(starting_accel_start, starting_accel_end)
        starting_accel_vibration_json.update(starting_p2p_vibration_json)
        starting_accel_vibration_json.update(starting_jerk_json)
        starting_accel_start_time = accel_data[starting_accel_start].timestamp
        starting_accel_end_time = accel_data[starting_accel_end].timestamp
        starting_accel_id = self._save_acceleration(
            starting_accel_start_time,
            starting_accel_end_time,
            True,
            self.trip_direction == 1,
            starting_accel_vibration_json,
        )

        x_end_accel_values = self._get_vibration_for_sample_interval(
            accel_data, "x", ending_accel_start, ending_accel_end
        )
        y_end_accel_values = self._get_vibration_for_sample_interval(
            accel_data, "y", ending_accel_start, ending_accel_end
        )
        z_ending_accel_values = self._get_vibration_for_sample_interval(
            accel_data, "z", ending_accel_start, ending_accel_end
        )
        ending_accel_vibration_json = self._get_vibration_json(
            x_end_accel_values, y_end_accel_values, z_ending_accel_values
        )
        ending_p2p_vibration_json = self._get_peak2peak_vibration(
            ending_accel_start, ending_accel_end
        )
        ending_jerk_json = self._get_jerk(ending_accel_start, ending_accel_end)
        ending_accel_vibration_json.update(ending_p2p_vibration_json)
        ending_accel_vibration_json.update(ending_jerk_json)

        ending_accel_start_time = accel_data[ending_accel_start].timestamp
        ending_accel_end_time = accel_data[ending_accel_end].timestamp
        ending_accel_id = self._save_acceleration(
            ending_accel_start_time,
            ending_accel_end_time,
            False,
            self.trip_direction == -1,
            ending_accel_vibration_json,
        )

        x_coast_values = self._get_vibration_for_sample_interval(
            accel_data, "x", starting_accel_end, ending_accel_start
        )
        y_coast_values = self._get_vibration_for_sample_interval(
            accel_data, "y", starting_accel_end, ending_accel_start
        )
        z_coast_values = self._get_vibration_for_sample_interval(
            accel_data, "z", starting_accel_end, ending_accel_start
        )
        trip_vibration_json = self._get_vibration_json(
            x_coast_values, y_coast_values, z_coast_values
        )
        trip_p2p_vibration_json = self._get_peak2peak_vibration(
            starting_accel_end, ending_accel_start
        )
        trip_vibration_json.update(trip_p2p_vibration_json)
        # Jerk values aren't valid while coasting

        # And finally, save the trip to the database.
        is_up = self.trip_direction == 1
        self._save_trip(
            starting_accel_start_time,
            ending_accel_end_time,
            is_up,
            elevation_change,
            speed_fpm,
            trip_vibration_json,
            starting_accel_id,
            ending_accel_id,
        )

        self._save_last_timestamp()

        self._write_out_chart_data(self.result_data)
