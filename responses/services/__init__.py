"""Respondent-side response handling: eligibility, progress and completion.

The submodules group these by capability; this package is their public surface.
"""
from .answers import normalize_answer
from .errors import (
    AuthenticationRequired,
    DuplicateSubmission,
    EligibilityUnknown,
    IneligibleRespondent,
    QuotaReached,
    ResponseUnavailable,
    ResponseValidationError,
)
from .progress import complete_submission, save_progress
from .sessions import build_presentation, current_published_version, hash_session_key
from .submissions import (
    can_access_submission,
    completed_response_counts,
    completed_survey_ids,
    discard_in_progress_submission,
    resumable_submissions,
    start_submission,
)


__all__ = [
    'AuthenticationRequired',
    'DuplicateSubmission',
    'EligibilityUnknown',
    'IneligibleRespondent',
    'QuotaReached',
    'ResponseUnavailable',
    'ResponseValidationError',
    'build_presentation',
    'can_access_submission',
    'complete_submission',
    'completed_response_counts',
    'completed_survey_ids',
    'current_published_version',
    'discard_in_progress_submission',
    'hash_session_key',
    'normalize_answer',
    'resumable_submissions',
    'save_progress',
    'start_submission',
]
