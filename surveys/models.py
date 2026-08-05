import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils.text import slugify

from .branching import Action, Operator
from .validators import validate_survey_image_size


def survey_banner_path(instance, filename):
    return f'surveys/{instance.id}/banner/{filename}'


def survey_thumbnail_path(instance, filename):
    return f'surveys/{instance.id}/thumbnail/{filename}'


survey_image_validators = [
    FileExtensionValidator(('jpg', 'jpeg', 'png', 'webp')),
    validate_survey_image_size,
]


def next_order(identities):
    """The order value that appends to the end of an identity queryset."""
    return (identities.aggregate(highest=models.Max('order'))['highest'] or 0) + 1


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

    def active(self):
        return self.filter(deleted_at__isnull=True)

    def discoverable(self):
        return self.filter(
            status=Survey.Status.PUBLISHED,
            visibility=Survey.Visibility.DISCOVERABLE,
            deleted_at__isnull=True,
        )

    def delete(self):
        # A plain bulk delete cascades the survey-owned identity hierarchy in one
        # collector batch and trips its PROTECT guards. Route every survey
        # through Survey.delete() instead, inside one transaction so a protected
        # survey rolls the whole selection back rather than leaving debris.
        deleted = 0
        with transaction.atomic():
            for survey in list(self):
                survey.delete()
                deleted += 1
        return deleted, {'surveys.Survey': deleted}


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

    RESPONDENT_IDENTITY_LABELS = {
        IdentityMode.ANONYMOUS: 'Anonymous',
        IdentityMode.IDENTIFIED: 'Profile shared with creator',
    }

    @property
    def respondent_identity_label(self):
        return self.RESPONDENT_IDENTITY_LABELS.get(self.identity_mode, self.get_identity_mode_display())
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
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)
    response_limit = models.PositiveIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1)],
    )

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

    def soft_delete(self):
        from django.utils import timezone

        if self.deleted_at is None:
            self.deleted_at = timezone.now()
            self.save(update_fields=('deleted_at', 'updated_at'))

    def restore(self):
        if self.deleted_at is not None:
            self.deleted_at = None
            self.save(update_fields=('deleted_at', 'updated_at'))

    def delete(self, *args, **kwargs):
        # The survey-owned identity rows form a PROTECTed hierarchy
        # (snapshot -> identity, and choice/row -> question -> section
        # identities), so a single cascade batch trips PROTECT. Tear it down
        # deterministically: drop the versions (removing every snapshot that
        # PROTECTs an identity), the survey-level branch rules, then the
        # identities leaf-first, before deleting the survey itself. Wrapped in a
        # transaction so any failure rolls the partial teardown back instead of
        # leaving the survey without its versions or identities.
        with transaction.atomic():
            self.versions.all().delete()
            self.presentation_branch_rules.all().delete()
            self.choice_identities.all().delete()
            self.matrix_row_identities.all().delete()
            self.question_identities.all().delete()
            self.section_identities.all().delete()
            return super().delete(*args, **kwargs)

    def __str__(self):
        return self.title

    @property
    def draft_version(self):
        return self.versions.filter(status=SurveyVersion.Status.DRAFT).first()


class SectionIdentity(models.Model):
    """Stable survey-owned placement and presentation state for a section."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(
        Survey,
        on_delete=models.CASCADE,
        related_name='section_identities',
    )
    order = models.PositiveIntegerField()
    randomize_questions = models.BooleanField(default=False)

    class Meta:
        ordering = ('order', 'id')


class QuestionIdentity(models.Model):
    """Stable survey-owned placement and presentation state for a question."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(
        Survey,
        on_delete=models.CASCADE,
        related_name='question_identities',
    )
    section_identity = models.ForeignKey(
        SectionIdentity,
        on_delete=models.PROTECT,
        related_name='question_identities',
    )
    order = models.PositiveIntegerField()
    required = models.BooleanField(default=False)
    randomize_choices = models.BooleanField(default=False)

    class Meta:
        ordering = ('section_identity__order', 'order', 'id')

    def clean(self):
        if (
            self.survey_id
            and self.section_identity_id
            and self.section_identity.survey_id != self.survey_id
        ):
            raise ValidationError('Question placement must belong to the same survey.')


class ChoiceIdentity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(
        Survey,
        on_delete=models.CASCADE,
        related_name='choice_identities',
    )
    question_identity = models.ForeignKey(
        QuestionIdentity,
        on_delete=models.PROTECT,
        related_name='choice_identities',
    )
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ('order', 'id')


class MatrixRowIdentity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(
        Survey,
        on_delete=models.CASCADE,
        related_name='matrix_row_identities',
    )
    question_identity = models.ForeignKey(
        QuestionIdentity,
        on_delete=models.PROTECT,
        related_name='matrix_row_identities',
    )
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ('order', 'id')


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
    title_snapshot = models.CharField(max_length=160, blank=True, default='')
    has_response_history = models.BooleanField(default=False)
    # Deprecated presentation setting retained only while historical migrations
    # and old databases are upgraded. Runtime code reads Survey.response_limit.
    response_limit = models.PositiveIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1)],
    )
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
            models.UniqueConstraint(
                fields=('survey',),
                condition=models.Q(status='published'),
                name='surveys_one_published_version',
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
    identity = models.ForeignKey(
        SectionIdentity,
        on_delete=models.PROTECT,
        related_name='snapshots',
    )
    title = models.CharField(max_length=160, default='Untitled section')
    description = models.TextField(blank=True)

    class Meta:
        ordering = ('identity__order',)

    def __str__(self):
        return self.title

    def _ensure_editable(self):
        status = SurveyVersion.objects.values_list('status', flat=True).get(pk=self.version_id)
        if status != SurveyVersion.Status.DRAFT:
            raise ValidationError('Published survey versions are immutable.')

    def save(self, *args, **kwargs):
        if not self.identity_id and self.version_id:
            self.identity = SectionIdentity.objects.create(
                survey_id=self.version.survey_id,
                order=next_order(
                    SectionIdentity.objects.filter(survey_id=self.version.survey_id)
                ),
            )
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
        RANKING = 'ranking', 'Ranking'
        LIKERT_MATRIX = 'likert_matrix', 'Likert matrix'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='questions')
    identity = models.ForeignKey(
        QuestionIdentity,
        on_delete=models.PROTECT,
        related_name='snapshots',
    )
    type = models.CharField(max_length=24, choices=Type.choices)
    prompt = models.CharField(max_length=500)
    help_text = models.CharField(max_length=300, blank=True)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ('identity__order',)

    @property
    def accepts_choices(self):
        return self.type in {
            self.Type.SINGLE_CHOICE,
            self.Type.MULTIPLE_CHOICE,
            self.Type.DROPDOWN,
            self.Type.RANKING,
            self.Type.LIKERT_MATRIX,
        }

    @property
    def uses_matrix_rows(self):
        return self.type == self.Type.LIKERT_MATRIX

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
        if not self.identity_id and self.section_id:
            section_identity = self.section.identity
            self.identity = QuestionIdentity.objects.create(
                survey_id=self.section.version.survey_id,
                section_identity=section_identity,
                order=next_order(section_identity.question_identities),
            )
        self._ensure_editable()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._ensure_editable()
        return super().delete(*args, **kwargs)


class QuestionChoice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    identity = models.ForeignKey(
        ChoiceIdentity,
        on_delete=models.PROTECT,
        related_name='snapshots',
    )
    label = models.CharField(max_length=240)

    class Meta:
        ordering = ('identity__order',)

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
        if not self.identity_id and self.question_id:
            question_identity = self.question.identity
            self.identity = ChoiceIdentity.objects.create(
                survey_id=self.question.section.version.survey_id,
                question_identity=question_identity,
                order=next_order(question_identity.choice_identities),
            )
        self._ensure_editable()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._ensure_editable()
        return super().delete(*args, **kwargs)


class MatrixRow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='matrix_rows')
    identity = models.ForeignKey(
        MatrixRowIdentity,
        on_delete=models.PROTECT,
        related_name='snapshots',
    )
    label = models.CharField(max_length=240)

    class Meta:
        ordering = ('identity__order',)

    def __str__(self):
        return self.label

    def _ensure_editable(self):
        status = Question.objects.values_list('section__version__status', flat=True).get(pk=self.question_id)
        if status != SurveyVersion.Status.DRAFT:
            raise ValidationError('Published survey versions are immutable.')

    def save(self, *args, **kwargs):
        if not self.identity_id and self.question_id:
            question_identity = self.question.identity
            self.identity = MatrixRowIdentity.objects.create(
                survey_id=self.question.section.version.survey_id,
                question_identity=question_identity,
                order=next_order(question_identity.matrix_row_identities),
            )
        self._ensure_editable()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._ensure_editable()
        return super().delete(*args, **kwargs)


class SurveyBranchRule(models.Model):
    """Live branching keyed to stable identities, independent of snapshots."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(
        Survey,
        on_delete=models.CASCADE,
        related_name='presentation_branch_rules',
    )
    source_question_identity = models.ForeignKey(
        QuestionIdentity,
        on_delete=models.PROTECT,
        related_name='source_branch_rules',
    )
    operator = models.CharField(max_length=16, choices=Operator.choices)
    compare_value = models.CharField(max_length=240, blank=True)
    compare_choice_identity = models.ForeignKey(
        ChoiceIdentity,
        on_delete=models.PROTECT,
        related_name='comparison_branch_rules',
        blank=True,
        null=True,
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    target_section_identity = models.ForeignKey(
        SectionIdentity,
        on_delete=models.PROTECT,
        related_name='incoming_branch_rules',
        blank=True,
        null=True,
    )
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ('order', 'id')
        constraints = [
            models.UniqueConstraint(
                fields=('survey', 'order'),
                name='surveys_live_branch_rule_order_unique',
            ),
        ]

    def clean(self):
        if (
            self.source_question_identity_id
            and self.source_question_identity.survey_id != self.survey_id
        ):
            raise ValidationError('Branch question must belong to this survey.')
        if self.action == Action.GO_TO_SECTION and not self.target_section_identity_id:
            raise ValidationError('A target section is required for this action.')
        if (
            self.target_section_identity_id
            and self.target_section_identity.survey_id != self.survey_id
        ):
            raise ValidationError('Branch target must belong to this survey.')
        if (
            self.compare_choice_identity_id
            and self.compare_choice_identity.question_identity_id
            != self.source_question_identity_id
        ):
            raise ValidationError('Compared choice must belong to the branch question.')

    @property
    def source_question(self):
        return self.source_question_identity.snapshots.filter(
            section__version__status=SurveyVersion.Status.DRAFT,
        ).first()

    @property
    def target_section(self):
        annotated = getattr(self, '_target_section_snapshot', None)
        if annotated is not None:
            return annotated
        if not self.target_section_identity_id:
            return None
        return self.target_section_identity.snapshots.filter(
            version__status=SurveyVersion.Status.DRAFT,
        ).first()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SurveyEligibilityCriteria(models.Model):
    """Live targeting settings. Eligibility outcomes are snapshotted per start."""

    survey = models.OneToOneField(
        Survey,
        on_delete=models.CASCADE,
        related_name='eligibility_criteria',
    )
    min_age = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        validators=[MaxValueValidator(120)],
    )
    max_age = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        validators=[MaxValueValidator(120)],
    )
    education_levels = models.JSONField(default=list, blank=True)
    countries = models.JSONField(default=list, blank=True)
    regions = models.JSONField(default=list, blank=True)
    genders = models.JSONField(default=list, blank=True)
    employment_statuses = models.JSONField(default=list, blank=True)
    industries = models.JSONField(default=list, blank=True)
    income_brackets = models.JSONField(default=list, blank=True)
    religions = models.JSONField(default=list, blank=True)
    ethnicities = models.JSONField(default=list, blank=True)
    languages = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name_plural = 'survey eligibility criteria'

    @property
    def is_targeted(self):
        return bool(
            self.min_age is not None
            or self.max_age is not None
            or self.education_levels
            or self.countries
            or self.regions
            or self.genders
            or self.employment_statuses
            or self.industries
            or self.income_brackets
            or self.religions
            or self.ethnicities
            or self.languages
        )

    def clean(self):
        from accounts import demographics
        from accounts.models import Profile
        from django_countries import countries

        if (
            self.min_age is not None
            and self.max_age is not None
            and self.min_age > self.max_age
        ):
            raise ValidationError({'max_age': 'Maximum age must be at least the minimum age.'})
        valid_values = {
            'education_levels': set(Profile.EducationLevel.values),
            'countries': {code for code, _ in countries},
            'regions': demographics.valid_subdivision_codes(),
            'genders': set(Profile.Gender.values),
            'employment_statuses': set(Profile.EmploymentStatus.values),
            'industries': demographics.INDUSTRY_VALUES,
            'income_brackets': demographics.INCOME_VALUES,
            'religions': demographics.RELIGION_VALUES,
            'ethnicities': demographics.ETHNICITY_VALUES,
            'languages': demographics.LANGUAGE_VALUES,
        }
        for field_name, allowed in valid_values.items():
            values = getattr(self, field_name)
            if not isinstance(values, list) or not set(values).issubset(allowed):
                raise ValidationError({field_name: 'Select only supported eligibility values.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
