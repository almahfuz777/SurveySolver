"""Deciding whether a respondent may take a survey, and recording why."""
from datetime import date

from django.utils import timezone

from accounts.services import research_profile_snapshot
from surveys.models import (
    Survey,
    SurveyEligibilityCriteria,
)
from surveys.targeting import (
    missing_attributes,
    profile_values,
    targeted_attributes,
    values_match,
)

from ..models import Submission
from .errors import (
    AuthenticationRequired,
    EligibilityUnknown,
    IneligibleRespondent,
    QuotaReached,
    ResponseValidationError,
)


def _validated_identity(survey, user, consent):
    """The account details an identified survey shares, once the respondent has agreed.

    The respondent cannot edit these: the point of an identified response is that the researcher
    receives the real account behind it, so the values are read from the account itself.
    """
    if survey.identity_mode == Survey.IdentityMode.ANONYMOUS:
        return {}, None
    if not (user and user.is_authenticated):
        raise AuthenticationRequired('Identified surveys are open to account holders only.')
    if not consent:
        raise ResponseValidationError(
            {'identity_consent': 'Confirm you agree to share your details before starting.'}
        )
    identity = {
        'name': user.get_full_name() or user.email,
        'email': user.email,
    }
    if survey.identity_scope == Survey.IdentityScope.PROFILE:
        # Snapshotted now, so the creator keeps what was actually consented to even if the
        # respondent edits their profile afterwards.
        identity['profile'] = research_profile_snapshot(user.profile)
    return identity, timezone.now()


def _ensure_account_access(survey, user):
    """Guests may not touch an account-only survey, however far along they already are.

    Checked at every step rather than only at the start, because a creator can turn the setting on
    while a guest is mid-response.
    """
    if survey.requires_account_to_respond and not (user and user.is_authenticated):
        raise AuthenticationRequired('This survey is open to account holders only.')


def _validated_eligibility(survey, user, screener_data):
    """Check the respondent against every criterion the survey sets.

    ``screener_data`` carries the answers collected on the landing page, already normalised to
    respondent attributes. A signed-in respondent's stored profile supplies the rest.
    """
    try:
        criteria = survey.eligibility_criteria
    except SurveyEligibilityCriteria.DoesNotExist:
        return {'targeted': False}, timezone.now()
    if not criteria.is_targeted:
        return {'targeted': False}, timezone.now()

    values = profile_values(user.profile) if user and user.is_authenticated else {}
    values.update(screener_data or {})
    if missing_attributes(criteria, values):
        raise EligibilityUnknown('Answer the eligibility questions to continue.')
    if not values_match(criteria, values):
        raise IneligibleRespondent('You do not meet this study’s eligibility requirements.')

    snapshot = {
        attribute: (
            values[attribute].isoformat()
            if isinstance(values[attribute], date)
            else values[attribute]
        )
        for attribute in targeted_attributes(criteria)
    }
    snapshot['targeted'] = True
    return snapshot, timezone.now()


def _ensure_quota_available(survey, version):
    if survey.response_limit is None:
        return
    completed = survey.submissions.filter(status=Submission.Status.COMPLETED).count()
    if completed >= survey.response_limit:
        raise QuotaReached('This survey has reached its response limit.')
