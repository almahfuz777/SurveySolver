import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify

from .validators import validate_survey_image_size


def survey_banner_path(instance, filename):
    return f'surveys/{instance.id}/banner/{filename}'


def survey_thumbnail_path(instance, filename):
    return f'surveys/{instance.id}/thumbnail/{filename}'


survey_image_validators = [
    FileExtensionValidator(('jpg', 'jpeg', 'png', 'webp')),
    validate_survey_image_size,
]


class Topic(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True)
    description = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class SurveyQuerySet(models.QuerySet):
    def owned_by(self, user):
        return self.filter(owner=user)

    def discoverable(self):
        return self.filter(
            status=Survey.Status.PUBLISHED,
            visibility=Survey.Visibility.DISCOVERABLE,
        )


class Survey(models.Model):
    class Visibility(models.TextChoices):
        DISCOVERABLE = 'discoverable', 'Discoverable'
        UNLISTED = 'unlisted', 'Unlisted'
        INVITATION_ONLY = 'invitation_only', 'Invitation only'

    class IdentityMode(models.TextChoices):
        ANONYMOUS = 'anonymous', 'Anonymous to creator'
        IDENTIFIED = 'identified', 'Identified with consent'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        CLOSED = 'closed', 'Closed'
        ARCHIVED = 'archived', 'Archived'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='owned_surveys',
    )
    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, editable=False)
    summary = models.CharField(max_length=320)
    description = models.TextField(blank=True)
    topics = models.ManyToManyField(Topic, related_name='surveys', blank=True)
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.DISCOVERABLE,
    )
    identity_mode = models.CharField(
        max_length=16,
        choices=IdentityMode.choices,
        default=IdentityMode.ANONYMOUS,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    estimated_minutes = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(120)],
    )
    banner = models.ImageField(
        upload_to=survey_banner_path,
        validators=survey_image_validators,
        blank=True,
    )
    thumbnail = models.ImageField(
        upload_to=survey_thumbnail_path,
        validators=survey_image_validators,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(blank=True, null=True)
    closed_at = models.DateTimeField(blank=True, null=True)

    objects = SurveyQuerySet.as_manager()

    class Meta:
        ordering = ('-updated_at',)

    def save(self, *args, **kwargs):
        if not self.slug:
            title_slug = slugify(self.title)[:140] or 'survey'
            self.slug = f'{title_slug}-{self.id.hex[:8]}'
        return super().save(*args, **kwargs)

    def archive(self):
        if self.status != self.Status.ARCHIVED:
            self.status = self.Status.ARCHIVED
            self.save(update_fields=('status', 'updated_at'))

    def __str__(self):
        return self.title

    @property
    def draft_version(self):
        return self.versions.filter(status=SurveyVersion.Status.DRAFT).first()


class SurveyVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        RETIRED = 'retired', 'Retired'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name='versions')
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    revision = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_survey_versions',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ('-number',)
        constraints = [
            models.UniqueConstraint(
                fields=('survey', 'number'),
                name='surveys_version_number_unique',
            ),
            models.UniqueConstraint(
                fields=('survey',),
                condition=models.Q(status='draft'),
                name='surveys_one_draft_version',
            ),
        ]

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT

    def save(self, *args, **kwargs):
        if self.pk:
            previous_status = (
                type(self).objects.filter(pk=self.pk).values_list('status', flat=True).first()
            )
            if previous_status and previous_status != self.Status.DRAFT:
                raise ValidationError('Published survey versions are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if not self.is_editable:
            raise ValidationError('Published survey versions are immutable.')
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f'{self.survey.title} v{self.number}'


class Section(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(
        SurveyVersion,
        on_delete=models.CASCADE,
        related_name='sections',
    )
    title = models.CharField(max_length=160, default='Untitled section')
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ('order',)
        constraints = [
            models.UniqueConstraint(
                fields=('version', 'order'),
                name='surveys_section_order_unique',
            ),
        ]

    def __str__(self):
        return self.title

    def _ensure_editable(self):
        status = SurveyVersion.objects.values_list('status', flat=True).get(pk=self.version_id)
        if status != SurveyVersion.Status.DRAFT:
            raise ValidationError('Published survey versions are immutable.')

    def save(self, *args, **kwargs):
        self._ensure_editable()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._ensure_editable()
        return super().delete(*args, **kwargs)


class Question(models.Model):
    class Type(models.TextChoices):
        SHORT_TEXT = 'short_text', 'Short text'
        LONG_TEXT = 'long_text', 'Long text'
        NUMBER = 'number', 'Number'
        DATE = 'date', 'Date'
        SINGLE_CHOICE = 'single_choice', 'Single choice'
        MULTIPLE_CHOICE = 'multiple_choice', 'Multiple choice'
        DROPDOWN = 'dropdown', 'Dropdown'
        SCALE = 'scale', 'Scale'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='questions')
    type = models.CharField(max_length=24, choices=Type.choices)
    prompt = models.CharField(max_length=500)
    help_text = models.CharField(max_length=300, blank=True)
    required = models.BooleanField(default=False)
    order = models.PositiveIntegerField()
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ('order',)
        constraints = [
            models.UniqueConstraint(
                fields=('section', 'order'),
                name='surveys_question_order_unique',
            ),
        ]

    @property
    def accepts_choices(self):
        return self.type in {
            self.Type.SINGLE_CHOICE,
            self.Type.MULTIPLE_CHOICE,
            self.Type.DROPDOWN,
        }

    def __str__(self):
        return self.prompt

    def _ensure_editable(self):
        status = (
            Section.objects.filter(pk=self.section_id)
            .values_list('version__status', flat=True)
            .get()
        )
        if status != SurveyVersion.Status.DRAFT:
            raise ValidationError('Published survey versions are immutable.')

    def save(self, *args, **kwargs):
        self._ensure_editable()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._ensure_editable()
        return super().delete(*args, **kwargs)


class QuestionChoice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    label = models.CharField(max_length=240)
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ('order',)
        constraints = [
            models.UniqueConstraint(
                fields=('question', 'order'),
                name='surveys_choice_order_unique',
            ),
        ]

    def __str__(self):
        return self.label

    def _ensure_editable(self):
        status = (
            Question.objects.filter(pk=self.question_id)
            .values_list('section__version__status', flat=True)
            .get()
        )
        if status != SurveyVersion.Status.DRAFT:
            raise ValidationError('Published survey versions are immutable.')

    def save(self, *args, **kwargs):
        self._ensure_editable()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._ensure_editable()
        return super().delete(*args, **kwargs)
