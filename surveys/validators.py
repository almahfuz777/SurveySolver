from django.core.exceptions import ValidationError


MAX_SURVEY_IMAGE_SIZE = 5 * 1024 * 1024


def validate_survey_image_size(image):
    if image.size > MAX_SURVEY_IMAGE_SIZE:
        raise ValidationError('Survey images must be 5 MB or smaller.')
