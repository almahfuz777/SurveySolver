import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SurveyCollaborator(models.Model):
    class Role(models.TextChoices):
        EDITOR = 'editor', 'Editor'
        VIEWER = 'viewer', 'Viewer'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(
        'surveys.Survey',
        on_delete=models.CASCADE,
        related_name='collaborators',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='survey_collaborations',
    )
    role = models.CharField(max_length=12, choices=Role.choices)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='added_survey_collaborators',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('user__email',)
        constraints = [
            models.UniqueConstraint(
                fields=('survey', 'user'),
                name='sharing_one_role_per_survey_user',
            ),
        ]

    def __str__(self):
        return f'{self.user.email} · {self.get_role_display()}'

    def clean(self):
        if self.survey_id and self.user_id and self.survey.owner_id == self.user_id:
            raise ValidationError('The survey owner cannot also be a collaborator.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CollaborationLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(
        'surveys.Survey',
        on_delete=models.CASCADE,
        related_name='collaboration_links',
    )
    role = models.CharField(max_length=12, choices=SurveyCollaborator.Role.choices)
    token_hash = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_collaboration_links',
    )
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    accepted_count = models.PositiveIntegerField(default=0)
    last_accepted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_active(self):
        return self.revoked_at is None and not self.is_expired

    def __str__(self):
        return f'{self.survey.title} · {self.get_role_display()} link'


class CollaboratorInvitation(models.Model):
    class DeliveryStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(
        'surveys.Survey',
        on_delete=models.CASCADE,
        related_name='collaborator_invitations',
    )
    email = models.EmailField()
    role = models.CharField(max_length=12, choices=SurveyCollaborator.Role.choices)
    token_hash = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_collaborator_invitations',
    )
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    accepted_at = models.DateTimeField(blank=True, null=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='accepted_collaborator_invitations',
        blank=True,
        null=True,
    )
    delivery_status = models.CharField(
        max_length=12,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
    )
    delivery_error = models.CharField(max_length=240, blank=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(accepted_at__isnull=True, accepted_by__isnull=True)
                    | models.Q(accepted_at__isnull=False, accepted_by__isnull=False)
                ),
                name='sharing_invitation_acceptance_consistent',
            ),
        ]

    @property
    def is_active(self):
        return (
            self.revoked_at is None
            and self.accepted_at is None
            and timezone.now() < self.expires_at
        )

    def save(self, *args, **kwargs):
        self.email = self.email.strip().casefold()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.email} · {self.get_role_display()} invitation'
