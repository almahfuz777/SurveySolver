"""The eligibility questions a respondent answers before starting a targeted survey.

A guest answers every attribute the survey filters on. A signed-in respondent answers only the
ones their research profile is still missing, and their answers are written back to the profile so
the next targeted survey does not ask again.
"""
from django import forms
from django.core.exceptions import ValidationError
from django_countries import countries

from accounts import demographics
from accounts.models import Profile
from accounts.services import update_research_profile
from accounts.validators import validate_birth_date
from surveys.targeting import (
    AGE_ATTRIBUTE,
    missing_attributes,
    profile_values,
    targeted_attributes,
)


def _select(choices, placeholder):
    return forms.ChoiceField(
        choices=[('', placeholder)] + list(choices),
        widget=forms.Select(),
    )


# One builder per respondent attribute, so a criterion added to the builder cannot be left
# unanswerable here.
FIELD_BUILDERS = {
    AGE_ATTRIBUTE: lambda: (
        'Date of birth',
        forms.DateField(
            widget=forms.DateInput(attrs={'type': 'date'}),
            validators=[validate_birth_date],
        ),
    ),
    'education_level': lambda: (
        'Education level',
        _select(Profile.EducationLevel.choices, 'Select your education level'),
    ),
    'country': lambda: ('Country', _select(list(countries), 'Select your country')),
    'region': lambda: (
        'Region or district',
        _select(demographics.subdivision_choices(), 'Select your region'),
    ),
    'gender': lambda: ('Gender', _select(Profile.Gender.choices, 'Select your gender')),
    'employment_status': lambda: (
        'Employment status',
        _select(Profile.EmploymentStatus.choices, 'Select your employment status'),
    ),
    'industry': lambda: ('Industry', _select(demographics.INDUSTRY_CHOICES, 'Select your industry')),
    'income_bracket': lambda: (
        'Income band',
        _select(demographics.INCOME_CHOICES, 'Select your income band'),
    ),
    'religion': lambda: ('Religion', _select(demographics.RELIGION_CHOICES, 'Select your religion')),
    'ethnicity': lambda: ('Ethnicity', _select(demographics.ETHNICITY_CHOICES, 'Select your ethnicity')),
    'languages': lambda: (
        'Languages you can respond in',
        forms.MultipleChoiceField(
            choices=demographics.LANGUAGE_CHOICES,
            widget=forms.CheckboxSelectMultiple(attrs={'class': 'pill-select'}),
        ),
    ),
}


class EligibilityScreenerForm(forms.Form):
    """Asks only what is still unknown about this respondent for this survey."""

    prefix = 'eligibility'

    def __init__(self, *args, criteria=None, user=None, **kwargs):
        kwargs.setdefault('prefix', self.prefix)
        super().__init__(*args, **kwargs)
        self.criteria = criteria
        self.user = user
        self.known_values = (
            profile_values(user.profile)
            if user is not None and user.is_authenticated
            else {}
        )
        self.asked_attributes = (
            missing_attributes(criteria, self.known_values)
            if self.known_values
            else targeted_attributes(criteria)
        )
        for attribute in self.asked_attributes:
            label, field = FIELD_BUILDERS[attribute]()
            field.label = label
            field.required = True
            self.fields[attribute] = field

    @property
    def is_needed(self):
        return bool(self.fields)

    def clean(self):
        """Reject answers that would not make a valid profile, before any response is started.

        Catching it here means :meth:`save_to_profile` can never fail once the response exists.
        """
        cleaned_data = super().clean()
        if self.errors or not (self.user is not None and self.user.is_authenticated):
            return cleaned_data
        profile = self.user.profile
        original = {attribute: getattr(profile, attribute) for attribute in cleaned_data}
        try:
            for attribute, value in cleaned_data.items():
                setattr(profile, attribute, value)
            profile.full_clean(exclude=('user',))
        except ValidationError as error:
            for field, messages in error.message_dict.items():
                self.add_error(field if field in self.fields else None, messages)
        finally:
            for attribute, value in original.items():
                setattr(profile, attribute, value)
        return cleaned_data

    def respondent_values(self):
        """Everything known about the respondent once this screener is answered."""
        values = dict(self.known_values)
        values.update(self.cleaned_data)
        return values

    def save_to_profile(self):
        """Keep a signed-in respondent's answers so later surveys do not ask again.

        Goes through the accounts service so the answers are validated and any profile-completion
        bonus is awarded, exactly as if they had been typed on the profile page.
        """
        if not (self.user is not None and self.user.is_authenticated):
            return False
        _, bonus_awarded = update_research_profile(self.user.profile, self.cleaned_data)
        return bonus_awarded
