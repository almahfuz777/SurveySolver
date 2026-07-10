import uuid

from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django_countries.fields import CountryField

from .managers import UserManager
from .validators import validate_birth_date


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
        WOMAN = 'woman', 'Woman'
        MAN = 'man', 'Man'
        NON_BINARY = 'non_binary', 'Non-binary'
        SELF_DESCRIBE = 'self_describe', 'Prefer to self-describe'
        PREFER_NOT_TO_SAY = 'prefer_not_to_say', 'Prefer not to say'

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
    gender_self_description = models.CharField(max_length=80, blank=True)
    country = CountryField(blank=True)
    education_level = models.CharField(
        max_length=24,
        choices=EducationLevel.choices,
        blank=True,
    )
    field_of_study = models.CharField(max_length=120, blank=True)
    employment_status = models.CharField(
        max_length=24,
        choices=EmploymentStatus.choices,
        blank=True,
    )
    occupation = models.CharField(max_length=120, blank=True)
    institution = models.CharField(max_length=160, blank=True)
    research_interests = models.CharField(max_length=500, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def completion_percentage(self):
        values = {
            'first_name': self.user.first_name,
            'last_name': self.user.last_name,
            'birth_date': self.birth_date,
            'gender': self.gender and (
                self.gender != self.Gender.SELF_DESCRIBE
                or self.gender_self_description.strip()
            ),
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

    def __str__(self):
        return f'Profile for {self.user.email}'
