import uuid

from django.conf import settings
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
