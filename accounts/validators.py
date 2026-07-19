from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone


MAX_AVATAR_SIZE = 5 * 1024 * 1024


def validate_avatar_size(image):
    if image.size > MAX_AVATAR_SIZE:
        raise ValidationError('Profile photos must be 5 MB or smaller.')


def validate_birth_date(value):
    today = timezone.localdate()
    if value > today:
        raise ValidationError('Birth date cannot be in the future.')

    try:
        oldest_valid_date = date(today.year - 120, today.month, today.day)
    except ValueError:
        oldest_valid_date = date(today.year - 120, today.month, 28)
    if value < oldest_valid_date:
        raise ValidationError('Enter a valid birth date.')
