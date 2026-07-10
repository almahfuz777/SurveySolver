import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from responses.models import Submission
from responses.services import hash_session_key

from .models import GuestRewardClaim


BASE_COMPLETION_POINTS = 10
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
    valid = (
        not claim.is_claimed
        and not claim.is_expired
        and claim.submission.status == Submission.Status.COMPLETED
        and claim.submission.is_eligible
        and secrets.compare_digest(claim.secret_hash, _hash_secret(secret))
        and secrets.compare_digest(claim.session_key_hash, hash_session_key(session_key))
    )
    if not valid:
        return False
    session[PENDING_CLAIM_SESSION_KEY] = {
        'claim_id': str(claim.id),
        'secret': secret,
    }
    session.modified = True
    return True
