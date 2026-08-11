import uuid

from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.functions import Lower
from django_countries.fields import CountryField

from . import demographics
from .managers import UserManager
from .validators import validate_avatar_size, validate_birth_date


def profile_avatar_path(instance, filename):
    return f'accounts/{instance.user_id}/avatar/{filename}'


avatar_validators = [
    FileExtensionValidator(('jpg', 'jpeg', 'png', 'webp')),
    validate_avatar_size,
]


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None
    email = models.EmailField('email address', unique=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower('email'),
                name='accounts_user_email_ci_unique',
            ),
        ]

    def clean(self):
        super().clean()
        self.email = self.__class__.objects._normalize_email(self.email)

    def __str__(self):
        return self.email


class Profile(models.Model):
    class Gender(models.TextChoices):
        MAN = 'man', 'Man'
        WOMAN = 'woman', 'Woman'
        OTHER = 'other', 'Other'

    class EducationLevel(models.TextChoices):
        SECONDARY = 'secondary', 'Secondary school'
        UNDERGRADUATE = 'undergraduate', 'Undergraduate'
        POSTGRADUATE = 'postgraduate', 'Postgraduate or master’s'
        DOCTORATE = 'doctorate', 'Doctorate'
        VOCATIONAL = 'vocational', 'Vocational or technical training'
        OTHER = 'other', 'Other'
        PREFER_NOT_TO_SAY = 'prefer_not_to_say', 'Prefer not to say'

    class EmploymentStatus(models.TextChoices):
        STUDENT = 'student', 'Student'
        EMPLOYED = 'employed', 'Employed'
        SELF_EMPLOYED = 'self_employed', 'Self-employed'
        UNEMPLOYED = 'unemployed', 'Not currently employed'
        RETIRED = 'retired', 'Retired'
        OTHER = 'other', 'Other'
        PREFER_NOT_TO_SAY = 'prefer_not_to_say', 'Prefer not to say'

    COMPLETION_FIELDS = (
        'first_name',
        'last_name',
        'birth_date',
        'gender',
        'country',
        'education_level',
        'field_of_study',
        'employment_status',
        'research_interests',
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    birth_date = models.DateField(blank=True, null=True, validators=[validate_birth_date])
    gender = models.CharField(max_length=20, choices=Gender.choices, blank=True)
    country = CountryField(blank=True)
    region = models.CharField(max_length=10, blank=True)
    education_level = models.CharField(
        max_length=24,
        choices=EducationLevel.choices,
        blank=True,
    )
    field_of_study = models.CharField(
        max_length=40,
        choices=demographics.FIELD_OF_STUDY_CHOICES,
        blank=True,
    )
    employment_status = models.CharField(
        max_length=24,
        choices=EmploymentStatus.choices,
        blank=True,
    )
    industry = models.CharField(
        max_length=24,
        choices=demographics.INDUSTRY_CHOICES,
        blank=True,
    )
    income_bracket = models.CharField(
        max_length=24,
        choices=demographics.INCOME_CHOICES,
        blank=True,
    )
    religion = models.CharField(
        max_length=24,
        choices=demographics.RELIGION_CHOICES,
        blank=True,
    )
    ethnicity = models.CharField(
        max_length=24,
        choices=demographics.ETHNICITY_CHOICES,
        blank=True,
    )
    languages = models.JSONField(default=list, blank=True)
    occupation = models.CharField(
        max_length=40,
        choices=demographics.OCCUPATION_CHOICES,
        blank=True,
    )
    institution = models.CharField(max_length=160, blank=True)
    research_interests = models.JSONField(default=list, blank=True)
    avatar = models.ImageField(
        upload_to=profile_avatar_path,
        blank=True,
        validators=avatar_validators,
    )
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def avatar_url(self):
        if self.avatar:
            return self.avatar.url

        from allauth.socialaccount.models import SocialAccount
        google_account = SocialAccount.objects.filter(
            user=self.user, provider='google',
        ).first()
        if google_account:
            return google_account.extra_data.get('picture') or None
        return None

    @property
    def age(self):
        return demographics.age_on(self.birth_date)

    @property
    def completion_percentage(self):
        values = {
            'first_name': self.user.first_name,
            'last_name': self.user.last_name,
            'birth_date': self.birth_date,
            'gender': self.gender,
            'country': self.country,
            'education_level': self.education_level,
            'field_of_study': self.field_of_study,
            'employment_status': self.employment_status,
            'research_interests': self.research_interests,
        }
        completed = sum(bool(values[field]) for field in self.COMPLETION_FIELDS)
        return round(completed / len(self.COMPLETION_FIELDS) * 100)

    @property
    def is_complete(self):
        return self.completion_percentage == 100

    @property
    def region_display(self):
        if not self.region:
            return ''
        import pycountry
        subdivision = pycountry.subdivisions.get(code=self.region)
        return subdivision.name if subdivision else self.region

    @property
    def languages_display(self):
        if not self.languages:
            return ''
        labels = dict(demographics.LANGUAGE_CHOICES)
        return ', '.join(labels.get(code, code) for code in self.languages)

    @property
    def research_interests_display(self):
        if not self.research_interests:
            return ''
        from surveys.models import Topic
        names = dict(
            Topic.objects.filter(slug__in=self.research_interests).values_list('slug', 'name')
        )
        return ', '.join(names.get(slug, slug) for slug in self.research_interests)

    def clean(self):
        """Rules every writer must satisfy, not just the profile-edit form.

        A region code is prefixed with its ISO country code (``BD-13``), so the two fields have to
        agree; the response screener saves through here too.
        """
        super().clean()
        if self.region and self.region not in demographics.valid_subdivision_codes():
            raise ValidationError({'region': 'Select a supported region.'})
        country_code = getattr(self.country, 'code', self.country) or ''
        if self.region and not country_code:
            raise ValidationError({'region': 'Select your country before choosing a region.'})
        if self.region and not self.region.startswith(f'{country_code}-'):
            raise ValidationError({'region': 'Choose a region inside your selected country.'})

    def __str__(self):
        return f'Profile for {self.user.email}'
