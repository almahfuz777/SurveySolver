"""Who may respond and how many responses are accepted."""
from django import forms
from django_countries import countries

from accounts import demographics
from accounts.models import Profile

from core.widgets import PillCheckboxSelectMultiple

from ... import targeting


class ResponseLimitForm(forms.Form):
    enabled = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'response-limit-fields'}
        ),
    )
    response_limit = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=10_000_000,
        widget=forms.NumberInput(
            attrs={
                'inputmode': 'numeric',
                'min': 1,
                'max': 10_000_000,
                'placeholder': 'e.g. 500',
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('enabled'):
            if cleaned_data.get('response_limit') is None:
                self.add_error('response_limit', 'Enter the maximum number of completed responses.')
        else:
            cleaned_data['response_limit'] = None
        return cleaned_data


class EligibilityCriteriaForm(forms.Form):
    """Who may respond, as a single opt-in with per-attribute filters underneath.

    An empty filter means the attribute is unrestricted, so the survey stays targeted only for as
    long as at least one value is selected.
    """

    targeted = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'eligibility-criteria-fields'}
        ),
    )
    min_age = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=120,
        widget=forms.NumberInput(attrs={'class': 'age-input', 'placeholder': 'No minimum'}),
    )
    max_age = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=120,
        widget=forms.NumberInput(attrs={'class': 'age-input', 'placeholder': 'No maximum'}),
    )
    education_levels = forms.MultipleChoiceField(
        required=False,
        choices=Profile.EducationLevel.choices,
        widget=PillCheckboxSelectMultiple(),
    )
    countries = forms.MultipleChoiceField(
        required=False,
        choices=countries,
        widget=PillCheckboxSelectMultiple(),
    )
    genders = forms.MultipleChoiceField(
        required=False,
        choices=Profile.Gender.choices,
        widget=PillCheckboxSelectMultiple(),
    )
    employment_statuses = forms.MultipleChoiceField(
        required=False,
        choices=Profile.EmploymentStatus.choices,
        widget=PillCheckboxSelectMultiple(),
    )
    regions = forms.MultipleChoiceField(
        required=False,
        choices=demographics.subdivision_choices,
        widget=PillCheckboxSelectMultiple(),
    )
    industries = forms.MultipleChoiceField(
        required=False,
        choices=demographics.INDUSTRY_CHOICES,
        widget=PillCheckboxSelectMultiple(),
    )
    income_brackets = forms.MultipleChoiceField(
        required=False,
        choices=demographics.INCOME_CHOICES,
        widget=PillCheckboxSelectMultiple(),
    )
    religions = forms.MultipleChoiceField(
        required=False,
        choices=demographics.RELIGION_CHOICES,
        widget=PillCheckboxSelectMultiple(),
    )
    ethnicities = forms.MultipleChoiceField(
        required=False,
        choices=demographics.ETHNICITY_CHOICES,
        widget=PillCheckboxSelectMultiple(),
    )
    languages = forms.MultipleChoiceField(
        required=False,
        choices=demographics.LANGUAGE_CHOICES,
        widget=PillCheckboxSelectMultiple(),
    )

    def clean(self):
        cleaned_data = super().clean()
        # Turning targeting off discards the restrictions rather than remembering them, so the
        # saved criteria always match what the settings page shows.
        if not cleaned_data.get('targeted'):
            for field_name in targeting.AGE_CRITERIA:
                cleaned_data[field_name] = None
            for field_name in targeting.CRITERION_FIELDS:
                cleaned_data[field_name] = []
            return cleaned_data

        minimum = cleaned_data.get('min_age')
        maximum = cleaned_data.get('max_age')
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error('max_age', 'Maximum age must be at least the minimum age.')
        return cleaned_data
