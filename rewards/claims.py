import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from responses.models import Submission
from responses.services import hash_session_key

from .models import GuestRewardClaim
from .policy import BASE_COMPLETION_POINTS
from .services import award_survey_completion


CLAIM_LIFETIME = timedelta(days=7)
PENDING_CLAIM_SESSION_KEY = 'pending_guest_reward_claim'
CLAIM_SECRET_SESSION_KEY = 'guest_reward_claim_secrets'


def _hash_secret(secret):
    return hashlib.sha256(secret.encode('utf-8')).hexdigest()


@transaction.atomic
def create_guest_claim(submission_id, session_key):
    submission = Submission.objects.select_for_update().select_related('survey').get(
        pk=submission_id,
    )
    if (
        submission.status != Submission.Status.COMPLETED
        or not submission.is_eligible
        or submission.respondent_id
    ):
        return None, None
    existing = GuestRewardClaim.objects.filter(submission=submission).first()
    if existing:
        return existing, None
    secret = secrets.token_urlsafe(32)
    claim = GuestRewardClaim.objects.create(
        submission=submission,
        survey=submission.survey,
        points_snapshot=BASE_COMPLETION_POINTS,
        secret_hash=_hash_secret(secret),
        session_key_hash=hash_session_key(session_key),
        expires_at=timezone.now() + CLAIM_LIFETIME,
    )
    return claim, secret


def store_claim_secret(session, claim, secret):
    secrets_by_claim = session.get(CLAIM_SECRET_SESSION_KEY, {})
    secrets_by_claim[str(claim.id)] = secret
    session[CLAIM_SECRET_SESSION_KEY] = secrets_by_claim
    session.modified = True


def claim_secret_from_session(session, claim):
    return session.get(CLAIM_SECRET_SESSION_KEY, {}).get(str(claim.id))


def prepare_pending_claim(claim, secret, session_key, session):
    valid = _claim_is_valid(claim, secret, session_key)
    if not valid:
        return False
    session[PENDING_CLAIM_SESSION_KEY] = {
        'claim_id': str(claim.id),
        'secret': secret,
        'session_key_hash': hash_session_key(session_key),
    }
    session.modified = True
    return True


def _claim_is_valid(claim, secret, session_key=None, session_hash=None):
    provided_session_hash = session_hash or hash_session_key(session_key)
    return (
        not claim.is_claimed
        and not claim.is_expired
        and claim.submission.status == Submission.Status.COMPLETED
        and claim.submission.is_eligible
        and secrets.compare_digest(claim.secret_hash, _hash_secret(secret))
        and secrets.compare_digest(claim.session_key_hash, provided_session_hash)
    )


def _clear_claim_session(session, claim_id=None):
    session.pop(PENDING_CLAIM_SESSION_KEY, None)
    if claim_id:
        secrets_by_claim = session.get(CLAIM_SECRET_SESSION_KEY, {})
        secrets_by_claim.pop(str(claim_id), None)
        session[CLAIM_SECRET_SESSION_KEY] = secrets_by_claim
    session.modified = True


@transaction.atomic
def consume_pending_claim(user, session, session_key):
    pending = session.get(PENDING_CLAIM_SESSION_KEY)
    if not pending:
        return None
    try:
        claim = (
            GuestRewardClaim.objects.select_for_update()
            .select_related('submission__survey', 'submission__version')
            .get(pk=pending.get('claim_id'))
        )
    except (GuestRewardClaim.DoesNotExist, ValidationError, ValueError, TypeError):
        _clear_claim_session(session)
        return None
    if not _claim_is_valid(
        claim,
        pending.get('secret', ''),
        session_hash=pending.get('session_key_hash', ''),
    ):
        _clear_claim_session(session, claim.id)
        return None
    transaction_record, created = award_survey_completion(
        user,
        claim.submission,
        claim.points_snapshot,
    )
    if not created:
        _clear_claim_session(session, claim.id)
        return None
    claim.claimed_at = timezone.now()
    claim.claimed_by = user
    claim.save(update_fields=('claimed_at', 'claimed_by'))
    _clear_claim_session(session, claim.id)
    return transaction_record
