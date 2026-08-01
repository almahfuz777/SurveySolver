"""Finishing a response and settling what it earns, as one transaction.

Completion and reward are a single outcome for the respondent, so they commit
together rather than being sequenced by the calling view.
"""
from django.db import transaction

from rewards.claims import create_guest_claim
from rewards.policy import BASE_COMPLETION_POINTS
from rewards.services import award_survey_completion

from .services import complete_submission


@transaction.atomic
def finish_submission(submission_id, user, session_key, data):
    """Complete a submission and award or reserve its points.

    Signed-in respondents are credited immediately. Guests instead get a claim
    they can redeem later, so returns ``(submission, claim, claim_secret)`` with
    the last two set only for guests.
    """
    submission = complete_submission(submission_id, user, session_key, data)
    if user.is_authenticated:
        award_survey_completion(user, submission, BASE_COMPLETION_POINTS)
        return submission, None, None
    claim, claim_secret = create_guest_claim(submission.id, session_key)
    return submission, claim, claim_secret
