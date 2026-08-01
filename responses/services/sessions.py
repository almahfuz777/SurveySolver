"""Tying an anonymous browser session to the version it is answering."""

from django.core.signing import salted_hmac


from surveys.models import (
    Survey,
    SurveyVersion,
)
from surveys.presentation import build_submission_presentation

from .errors import ResponseUnavailable


def hash_session_key(session_key):
    return salted_hmac('responses.session', session_key, algorithm='sha256').hexdigest()


def current_published_version(survey, invitation_access=False):
    if survey.status != Survey.Status.PUBLISHED:
        raise ResponseUnavailable('This survey is not accepting responses.')
    if survey.visibility == Survey.Visibility.INVITATION_ONLY and not invitation_access:
        raise ResponseUnavailable('This survey requires an invitation.')
    try:
        return survey.versions.get(status=SurveyVersion.Status.PUBLISHED)
    except SurveyVersion.DoesNotExist as error:
        raise ResponseUnavailable('This survey is not accepting responses.') from error


def build_presentation(version):
    return build_submission_presentation(version)
