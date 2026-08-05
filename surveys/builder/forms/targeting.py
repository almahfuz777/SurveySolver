"""Who may respond and how many responses are accepted."""
from django import forms
from django_countries import countries

from accounts import demographics
from accounts.models import Profile

from core.widgets import PillCheckboxSelectMultiple


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
    restrict_age = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'age-restrictions'}
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
    restrict_education = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'education-restrictions'}
        ),
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
    restrict_countries = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'country-restrictions'}
        ),
    )
    restrict_genders = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'gender-restrictions'}
        ),
    )
    genders = forms.MultipleChoiceField(
        required=False,
        choices=Profile.Gender.choices,
        widget=PillCheckboxSelectMultiple(),
    )
    restrict_employment = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'employment-restrictions'}
        ),
    )
    employment_statuses = forms.MultipleChoiceField(
        required=False,
        choices=Profile.EmploymentStatus.choices,
        widget=PillCheckboxSelectMultiple(),
    )
    restrict_regions = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'region-restrictions'}
        ),
    )
    regions = forms.MultipleChoiceField(
        required=False,
        choices=demographics.subdivision_choices,
        widget=PillCheckboxSelectMultiple(),
    )
    restrict_industries = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'industry-restrictions'}
        ),
    )
    industries = forms.MultipleChoiceField(
        required=False,
        choices=demographics.INDUSTRY_CHOICES,
        widget=PillCheckboxSelectMultiple(),
    )
    restrict_income = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'income-restrictions'}
        ),
    )
    income_brackets = forms.MultipleChoiceField(
        required=False,
        choices=demographics.INCOME_CHOICES,
        widget=PillCheckboxSelectMultiple(),
    )
    restrict_religions = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'religion-restrictions'}
        ),
    )
    religions = forms.MultipleChoiceField(
        required=False,
        choices=demographics.RELIGION_CHOICES,
        widget=PillCheckboxSelectMultiple(),
    )
    restrict_ethnicities = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'ethnicity-restrictions'}
        ),
    )
    ethnicities = forms.MultipleChoiceField(
        required=False,
        choices=demographics.ETHNICITY_CHOICES,
        widget=PillCheckboxSelectMultiple(),
    )
    restrict_languages = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'data-disclosure-toggle': '', 'aria-controls': 'language-restrictions'}
        ),
    )
    languages = forms.MultipleChoiceField(
        required=False,
        choices=demographics.LANGUAGE_CHOICES,
        widget=PillCheckboxSelectMultiple(),
    )

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('restrict_age'):
            cleaned_data['min_age'] = None
            cleaned_data['max_age'] = None
        elif cleaned_data.get('min_age') is None and cleaned_data.get('max_age') is None:
            self.add_error('min_age', 'Enter a minimum or maximum age.')

        restricted_fields = (
            ('restrict_genders', 'genders', 'Select at least one gender.'),
            ('restrict_employment', 'employment_statuses', 'Select at least one employment status.'),
            ('restrict_education', 'education_levels', 'Select at least one education level.'),
            ('restrict_countries', 'countries', 'Select at least one country.'),
            ('restrict_regions', 'regions', 'Select at least one region.'),
            ('restrict_industries', 'industries', 'Select at least one industry.'),
            ('restrict_income', 'income_brackets', 'Select at least one income band.'),
            ('restrict_religions', 'religions', 'Select at least one religion.'),
            ('restrict_ethnicities', 'ethnicities', 'Select at least one ethnicity.'),
            ('restrict_languages', 'languages', 'Select at least one language.'),
        )
        for toggle, field_name, message in restricted_fields:
            if cleaned_data.get(toggle):
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, message)
            else:
                cleaned_data[field_name] = []

        minimum = cleaned_data.get('min_age')
        maximum = cleaned_data.get('max_age')
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error('max_age', 'Maximum age must be at least the minimum age.')
        return cleaned_data
