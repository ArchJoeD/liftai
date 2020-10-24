#! /usr/bin/python3

import logging

from sqlalchemy import func, text

import elisha.constants as constants
import utilities.common_constants as common_constants
from notifications.notifications import Notification, NotificationTopic
from utilities.db_utilities import Event, Problem

default_state = {
    common_constants.PROB_TYPE_ANOMALY: {
        common_constants.PROB_SUBTYPE_RELEVELING: {constants.RELEVELING_STATE: 0}
    }
}

releveling_query = """
SELECT *
FROM events
WHERE event_subtype = :subtype
  AND occurred_at >= :ocurred_at
"""

logger = logging.getLogger(__name__)


class Anomaly:
    n = Notification()

    def process_event(self, session, event, state_info):
        logger.debug(
            "Anomaly event: subtype={0},  confidence={1}, source={2}".format(
                event.event_subtype, event.confidence, event.source
            )
        )

        # Handle each type of anomaly separately
        subtype = event.event_subtype
        if subtype == common_constants.EVENT_SUBTYPE_RELEVELING:
            state_info = self._process_subtype_releveling(session, event, state_info)
        else:
            logger.error("Unhandled subtype of anomaly")
        return state_info

    def _process_subtype_releveling(self, session, event, state_info):
        problem = self._get_open_anomaly_problem(
            session, common_constants.PROB_SUBTYPE_RELEVELING
        )
        if problem:
            logger.debug(
                "Processing releveling event with open releveling problem id={0}, confidence={1}".format(
                    problem.id, problem.confidence
                )
            )
            if event.confidence == 0:
                logger.debug(
                    "Got a lack-of-releveling event, closing up releveling problem"
                )
                session.query(Problem.id == problem.id).update(
                    {
                        Problem.ended_at: event.occurred_at,
                        Problem.updated_at: func.now(),
                    },
                    synchronize_session="fetch",
                )
        else:
            logger.debug(
                "Processing releveling event, no open problems so going back through old releveling events"
            )
            lookback_hours = text(
                "NOW() - INTERVAL '{0} hours'".format(
                    constants.RELEVELING_LOOKBACK_HOURS
                )
            )
            events = (
                session.query(Event.id, Event.occurred_at, Event.confidence)
                .filter(
                    Event.event_type == common_constants.EVENT_TYPE_ANOMALY,
                    Event.event_subtype == common_constants.EVENT_SUBTYPE_RELEVELING,
                    Event.occurred_at > lookback_hours,
                )
                .order_by(Event.occurred_at.desc())
            )

            # Count the number of events in reverse chronological order
            # until we reach an event with 0 confidence to get the number of
            # relevelings and the earliest the event was detected
            count = 0
            started_at = None
            for event in events:
                if event.confidence == 0:
                    break

                count += 1
                started_at = event.occurred_at

            if count > constants.RELEVELING_COUNT_THRESHOLD:
                confidence = float(
                    min(count, constants.RELEVELING_COUNT_MAX_CONFIDENCE)
                )
                customer_info = "LiftAI detected {0} releveling events since {1}".format(
                    count, started_at
                )
                logger.info("Detected a releveling problem, count = {0}".format(count))
                session.add(
                    Problem(
                        started_at=started_at,
                        problem_type=common_constants.PROB_TYPE_ANOMALY,
                        problem_subtype=common_constants.PROB_SUBTYPE_RELEVELING,
                        confidence=confidence,
                        customer_info=customer_info,
                    )
                )
            else:
                logger.debug(
                    "Count was only {0}, so we don't open a problem... yet".format(
                        count
                    )
                )

        return state_info

    def _get_open_anomaly_problem(self, session, problem_subtype):
        return (
            session.query(Problem.id, Problem.confidence, Problem.updated_at)
            .filter(
                Problem.problem_type == common_constants.PROB_TYPE_ANOMALY,
                Problem.problem_subtype == problem_subtype,
                Problem.ended_at == None,
            )
            .order_by(Problem.id.desc())
            .first()
        )

    # Returns the default state for the anomaly detector in JSON format.
    @staticmethod
    def get_default_state():
        return default_state
