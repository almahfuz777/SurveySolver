import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from surveys.models import Question, Survey, SurveyVersion


class Submission(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = 'in_progress', 'In progress'
        COMPLETED = 'completed', 'Completed'

    class Source(models.TextChoices):
        DIRECT = 'direct', 'Direct link'
        DISCOVER = 'discover', 'Survey discover'
        INVITATION = 'invitation', 'Respondent invitation'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(Survey, on_delete=models.PROTECT, related_name='submissions')
    version = models.ForeignKey(
        SurveyVersion,
        on_delete=models.PROTECT,
        related_name='submissions',
    )
    respondent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='survey_submissions',
        blank=True,
        null=True,
    )
    session_key_hash = models.CharField(max_length=64, db_index=True)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.DIRECT)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
        db_index=True,
    )
    presentation = models.JSONField(default=dict)
    identity_mode_snapshot = models.CharField(
        max_length=16,
        choices=Survey.IdentityMode.choices,
        default=Survey.IdentityMode.ANONYMOUS,
    )
    identity_data = models.JSONField(default=dict, blank=True)
    identity_consent_at = models.DateTimeField(blank=True, null=True)
    is_eligible = models.BooleanField(default=True)
    eligibility_data = models.JSONField(default=dict, blank=True)
    eligibility_checked_at = models.DateTimeField(blank=True, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ('-started_at',)
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(status='in_progress', completed_at__isnull=True)
                    | models.Q(status='completed', completed_at__isnull=False)
                ),
                name='responses_submission_status_timestamp_valid',
            ),
            models.UniqueConstraint(
                fields=('survey', 'respondent'),
                condition=models.Q(status='completed', respondent__isnull=False),
                name='responses_one_completed_per_user_survey',
            ),
            models.UniqueConstraint(
                fields=('survey', 'session_key_hash'),
                condition=models.Q(status='completed'),
                name='responses_one_completed_per_session_survey',
            ),
        ]

    def clean(self):
        if self.version_id and self.survey_id and self.version.survey_id != self.survey_id:
            raise ValidationError('The response version must belong to the survey.')
        has_consent = self.identity_consent_at is not None
        has_identity = bool(self.identity_data)
        identified = self.identity_mode_snapshot == Survey.IdentityMode.IDENTIFIED
        if identified and (not has_consent or not has_identity):
            raise ValidationError(
                'Identified responses require explicit consent and identity data.'
            )
        if not identified and (has_consent or has_identity):
            raise ValidationError(
                'Anonymous responses cannot contain creator-visible identity data.'
            )

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if self.pk:
            previous_status = (
                type(self).objects.filter(pk=self.pk).values_list('status', flat=True).first()
            )
            if previous_status == self.Status.COMPLETED:
                raise ValidationError('Completed submissions are immutable.')
        self.full_clean()
        result = super().save(*args, **kwargs)
        if creating:
            SurveyVersion.objects.filter(
                pk=self.version_id,
                has_response_history=False,
            ).update(has_response_history=True)
        return result

    def __str__(self):
        return f'{self.survey.title} response {self.id}'


class Answer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        Submission,
        on_delete=models.CASCADE,
        related_name='answers',
    )
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name='answers')
    value = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = (
            'question__identity__section_identity__order',
            'question__identity__order',
        )
        constraints = [
            models.UniqueConstraint(
                fields=('submission', 'question'),
                name='responses_one_answer_per_question',
            ),
        ]

    def clean(self):
        if (
            self.submission_id
            and self.question_id
            and self.question.section.version_id != self.submission.version_id
        ):
            raise ValidationError('The answer question must belong to the presented version.')
        if self.submission_id and self.submission.status == Submission.Status.COMPLETED:
            raise ValidationError('Completed answers are immutable.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.submission.status == Submission.Status.COMPLETED:
            raise ValidationError('Completed answers are immutable.')
        return super().delete(*args, **kwargs)


class ResponseAuditEvent(models.Model):
    class Action(models.TextChoices):
        DELETED = 'deleted', 'Permanently deleted'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(
        Survey,
        on_delete=models.SET_NULL,
        related_name='response_audit_events',
        blank=True,
        null=True,
    )
    submission_id = models.UUIDField(db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='response_audit_events',
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.get_action_display()} · {self.submission_id}'
