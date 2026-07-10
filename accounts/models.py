import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from .managers import UserManager


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
