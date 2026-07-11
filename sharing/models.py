import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


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
