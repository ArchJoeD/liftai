#! /usr/bin/python3

import logging
from decimal import Decimal

from sqlalchemy.sql import func

import elisha.constants as constants
from notifications.notifications import Notification, NotificationTopic
import utilities.common_constants as common_constants
from utilities.db_utilities import Problem

logger = logging.getLogger(__name__)


class Shutdown:
    notif = None

    def __init__(self):
        self.notif = Notification()

    def process_event(self, session, event, state_info):
        shutdown_state = state_info[common_constants.PROB_TYPE_SHUTDOWN]
        self._fix_legacy_state_issues(shutdown_state)

        logger.debug(
            "Shutdown event: subtype={0}, confidence={1}, source={2}".format(
                event.event_subtype, event.confidence, event.source
            )
        )

        notification_confidence = (
            round(float(event.confidence), 2)
            if event.confidence > 99
            else int(event.confidence)
        )

        self.notif.send(
            NotificationTopic.SHUTDOWN_CONFIDENCE,
            notif_data={
                "shutdown_subtype": event.event_subtype,
                "confidence": notification_confidence,
            },
            include_last_trip=True if notification_confidence > 0 else False,
        )

        open_problem_id = shutdown_state[common_constants.PROB_OPEN_PROBLEM_ID]
        if open_problem_id < 0:
            # No open problem exists
            if event.confidence == 0:
                logger.info(
                    "Got an extra 0 confidence, which is normal with multiple sources, do nothing"
                )
                return state_info

            # Create a problem
            problem = Problem(
                started_at=event.occurred_at,
                problem_type=common_constants.PROB_TYPE_SHUTDOWN,
                customer_info=constants.SHUTDOWN_PROBLEM_TEXT,
                confidence=event.confidence,
                details=common_constants.PROB_DETAILS_SYSTEM,
                events=[],
            )
            session.add(problem)
            session.flush()

            open_problem_id = problem.id
            shutdown_state[common_constants.PROB_OPEN_PROBLEM_ID] = open_problem_id
            logger.info(
                "Got the first shutdown event with confidence {0}, created problem {1}".format(
                    event.confidence, open_problem_id
                )
            )

        if event.confidence == 0:
            # This is the end of a shutdown problem.
            if (
                shutdown_state[common_constants.PROB_SHUTDOWN_STATUS]
                != common_constants.PROB_SHUTDOWN_RUNNING
            ):
                shutdown_state[
                    common_constants.PROB_SHUTDOWN_STATUS
                ] = common_constants.PROB_SHUTDOWN_RUNNING
                logger.info("shutdown ended at {0}".format(str(event.occurred_at)))
            else:
                logger.info(
                    "under-the-radar shutdown problem ended at {0}".format(
                        str(event.occurred_at)
                    )
                )

            try:
                session.query(Problem).filter(Problem.id == open_problem_id).update(
                    {
                        Problem.ended_at: event.occurred_at,
                        Problem.updated_at: func.now(),
                    },
                    synchronize_session="fetch",
                )
                session.flush()
            except Exception as ex:
                logger.error("Problem when trying to update problems to end shutdown")
                logger.error("...The exception was: {0}".format(str(ex)))
                raise

            # Reset the shutdown state
            shutdown_state[common_constants.PROB_SHUTDOWN_CONFIDENCE] = 0
            shutdown_state[common_constants.PROB_OPEN_PROBLEM_ID] = -1
        else:
            combined_confidence = self._compute_shutdown_confidence_combination(
                session, open_problem_id
            )
            new_status = Shutdown._convert_confidence_to_shutdown_level(
                combined_confidence
            )

            if new_status != shutdown_state[common_constants.PROB_SHUTDOWN_STATUS]:
                logger.info(
                    "Changed shutdown state: problem id={0}, status={1}, combined_confidence={2}".format(
                        open_problem_id, new_status, combined_confidence
                    )
                )

                shutdown_state[common_constants.PROB_SHUTDOWN_STATUS] = new_status

            shutdown_state[
                common_constants.PROB_SHUTDOWN_CONFIDENCE
            ] = combined_confidence

            session.query(Problem).filter(
                Problem.id == shutdown_state[common_constants.PROB_OPEN_PROBLEM_ID]
            ).update(
                {
                    Problem.events: func.array_cat(Problem.events, [event.id]),
                    Problem.confidence: combined_confidence,
                    Problem.updated_at: func.now(),
                },
                synchronize_session="fetch",
            )

        return state_info

    def _compute_shutdown_confidence_combination(self, session, problem_id):
        events = self._get_latest_event_of_each_type(session, problem_id)
        confidence = 0
        for event in events:
            logger.debug(
                "Computing combined confidence for {0} and {1} with subtype {2}".format(
                    confidence, event["confidence"], event["event_subtype"]
                )
            )
            confidence = self._compute_combined_confidence(
                confidence, event["confidence"]
            )
        logger.debug("combined confidence is {0}".format(confidence))
        return confidence

    def _get_latest_event_of_each_type(self, session, problem_id):
        latest_of_each_subtype_query = """
        -- Select the most recent event of each subtype after the start of the first shutdown event, if any. Return the
        -- subtype and confidence level.
        WITH problem AS (
            SELECT started_at FROM problems WHERE id = %s
        )
        SELECT event_subtype, confidence
        FROM (
            SELECT
              ROW_NUMBER() OVER (PARTITION BY event_subtype ORDER BY id DESC) AS r,
              e.*
            FROM
              events e, problem
            WHERE e.event_type = '%s'
        ) grouped_events
        WHERE grouped_events.r < 2;
        """

        try:
            return session.execute(
                latest_of_each_subtype_query
                % (problem_id, common_constants.EVENT_TYPE_SHUTDOWN)
            )
        except Exception as ex:
            logger.error(
                "Exception in _get_latest_event_of_each_type(): {0}".format(str(ex))
            )
            raise

    def _compute_combined_confidence(self, current_confidence, event_confidence):
        # MATH: Use piece-wise linear approximation since events aren't independent and confidences are just estimates.
        x = min(current_confidence, event_confidence)
        y = max(current_confidence, event_confidence)
        if x < 20:  # Very low confidence numbers mean "I have no idea."
            return round(Decimal(y), 0)
        if y - x < 100 - y:  # One number doesn't overshadow the other
            return round(Decimal(y + min(x / 2, (100 - y) / 2)), 2)
        if (y - x) / 2 < 100 - y:
            return round(
                Decimal(y + min(x / 4, (100 - y) / 4)), 2
            )  # One number doesn't *totally* overshadow the other
        else:
            return round(Decimal(y + min(x / 8, (100 - y) / 8)), 2)

    def _fix_legacy_state_issues(self, shutdown_state):
        if common_constants.PROB_OPEN_PROBLEM_ID not in shutdown_state:
            shutdown_state[common_constants.PROB_OPEN_PROBLEM_ID] = -1
            logger.info("Fixed a legacy problem ID value")
        if (
            shutdown_state[common_constants.PROB_SHUTDOWN_STATUS]
            == common_constants.PROB_SHUTDOWN_OLD_SHUTDOWN_STATE
        ):
            shutdown_state[
                common_constants.PROB_SHUTDOWN_STATUS
            ] = Shutdown._convert_confidence_to_shutdown_level(
                shutdown_state[common_constants.PROB_SHUTDOWN_CONFIDENCE]
            )
            logger.info(
                "Fixed a legacy state value, setting to {0}".format(
                    shutdown_state[common_constants.PROB_SHUTDOWN_STATUS]
                )
            )

    # Returns the default state for the shutdown detector in JSON format.
    @staticmethod
    def get_default_state():
        return {
            common_constants.PROB_TYPE_SHUTDOWN: {
                common_constants.PROB_SHUTDOWN_STATUS: common_constants.PROB_SHUTDOWN_RUNNING,
                common_constants.PROB_SHUTDOWN_CONFIDENCE: 0,
                common_constants.PROB_OPEN_PROBLEM_ID: -1,
            }
        }

    @staticmethod
    def _convert_confidence_to_shutdown_level(confidence):
        if confidence < 50:
            return common_constants.PROB_SHUTDOWN_RUNNING
        if confidence < 99:
            return common_constants.PROB_SHUTDOWN_WATCH
        return common_constants.PROB_SHUTDOWN_WARNING
