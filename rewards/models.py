import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class PointTransactionQuerySet(models.QuerySet):
    def balance_for(self, user):
        return self.filter(user=user).aggregate(total=Sum('amount'))['total'] or 0


class PointTransaction(models.Model):
    class Reason(models.TextChoices):
        PROFILE_COMPLETION = 'profile_completion', 'Profile completion'
        SURVEY_COMPLETION = 'survey_completion', 'Survey completion'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='point_transactions',
    )
    amount = models.IntegerField()
    reason = models.CharField(max_length=32, choices=Reason.choices)
    idempotency_key = models.CharField(max_length=160, unique=True)
    metadata = models.JSONField(default=dict, blank=True)
    survey = models.ForeignKey(
        'surveys.Survey',
        on_delete=models.PROTECT,
        related_name='point_transactions',
        blank=True,
        null=True,
    )
    submission = models.OneToOneField(
        'responses.Submission',
        on_delete=models.SET_NULL,
        related_name='point_transaction',
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PointTransactionQuerySet.as_manager()

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(amount=0),
                name='rewards_point_transaction_nonzero',
            ),
            models.UniqueConstraint(
                fields=('user', 'survey', 'reason'),
                condition=models.Q(reason='survey_completion'),
                name='rewards_one_completion_per_user_survey',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        reason='profile_completion',
                        survey__isnull=True,
                        submission__isnull=True,
                    )
                    | models.Q(
                        reason='survey_completion',
                        survey__isnull=False,
                    )
                ),
                name='rewards_transaction_context_valid',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Point transactions are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Point transactions are immutable.')

    def __str__(self):
        return f'{self.amount} points for {self.user.email}'


class GuestRewardClaim(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.OneToOneField(
        'responses.Submission',
        on_delete=models.CASCADE,
        related_name='guest_reward_claim',
    )
    survey = models.ForeignKey(
        'surveys.Survey',
        on_delete=models.PROTECT,
        related_name='guest_reward_claims',
    )
    points_snapshot = models.PositiveIntegerField()
    secret_hash = models.CharField(max_length=64)
    session_key_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    claimed_at = models.DateTimeField(blank=True, null=True)
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='claimed_guest_rewards',
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(claimed_at__isnull=True, claimed_by__isnull=True)
                    | models.Q(claimed_at__isnull=False, claimed_by__isnull=False)
                ),
                name='rewards_claim_status_consistent',
            ),
        ]

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_claimed(self):
        return self.claimed_at is not None

    def __str__(self):
        return f'{self.points_snapshot} point claim for {self.survey.title}'


class Badge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=240)
    completion_threshold = models.PositiveIntegerField(unique=True)

    class Meta:
        ordering = ('completion_threshold',)

    def __str__(self):
        return self.name


class BadgeAward(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='badge_awards',
    )
    badge = models.ForeignKey(Badge, on_delete=models.PROTECT, related_name='awards')
    awarded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-awarded_at',)
        constraints = [
            models.UniqueConstraint(
                fields=('user', 'badge'),
                name='rewards_one_badge_award_per_user',
            ),
        ]

    def __str__(self):
        return f'{self.badge.name} awarded to {self.user.email}'
