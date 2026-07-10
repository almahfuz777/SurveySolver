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
        DISCOVERY = 'discovery', 'Survey discovery'

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
        ]

    def clean(self):
        if self.version_id and self.survey_id and self.version.survey_id != self.survey_id:
            raise ValidationError('The response version must belong to the survey.')

    def save(self, *args, **kwargs):
        if self.pk:
            previous_status = (
                type(self).objects.filter(pk=self.pk).values_list('status', flat=True).first()
            )
            if previous_status == self.Status.COMPLETED:
                raise ValidationError('Completed submissions are immutable.')
        self.full_clean()
        return super().save(*args, **kwargs)

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
        ordering = ('question__section__order', 'question__order')
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
