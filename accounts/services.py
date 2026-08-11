"""Writing to a research profile.

Every caller goes through here so a profile is never saved unvalidated, and so completing a
profile always earns its bonus — no matter which page the answers came from.
"""
from django.db import transaction

from rewards.services import award_profile_completion_bonus


def research_profile_snapshot(profile):
    """The demographics an identified survey shares, as labelled rows fixed at response time.

    Display strings rather than raw codes: the snapshot has to stay readable years later, after
    the vocabularies behind those codes have moved on.
    """
    age = profile.age
    rows = (
        ('Age', str(age) if age is not None else ''),
        ('Gender', profile.get_gender_display() if profile.gender else ''),
        ('Country', profile.country.name if profile.country else ''),
        ('Region', profile.region_display),
        ('Education', profile.get_education_level_display() if profile.education_level else ''),
        ('Field of study', profile.get_field_of_study_display() if profile.field_of_study else ''),
        ('Employment', profile.get_employment_status_display() if profile.employment_status else ''),
        ('Industry', profile.get_industry_display() if profile.industry else ''),
        ('Occupation', profile.get_occupation_display() if profile.occupation else ''),
        ('Institution', profile.institution),
        ('Income', profile.get_income_bracket_display() if profile.income_bracket else ''),
        ('Religion', profile.get_religion_display() if profile.religion else ''),
        ('Ethnicity', profile.get_ethnicity_display() if profile.ethnicity else ''),
        ('Languages', profile.languages_display),
        ('Research interests', profile.research_interests_display),
    )
    return [{'label': label, 'value': value} for label, value in rows if value]


@transaction.atomic
def update_research_profile(profile, values):
    """Apply these attributes to the profile, validate, save, and award any bonus earned.

    Returns ``(profile, bonus_awarded)``. Raises ``ValidationError`` when the resulting profile
    would be inconsistent, which keeps model-level rules such as region-inside-country in force.
    """
    for attribute, value in values.items():
        setattr(profile, attribute, value)
    profile.full_clean()
    profile.save()
    _, bonus_awarded = award_profile_completion_bonus(profile)
    return profile, bonus_awarded
