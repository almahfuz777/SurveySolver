from allauth.account.forms import LoginForm, SignupForm
from django import forms
from django.contrib.auth import get_user_model

from core.widgets import PillCheckboxSelectMultiple

from . import demographics
from .models import Profile


class AccountLoginForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['login'].widget.attrs['placeholder'] = 'e.g. john@example.com'
        self.fields['password'].widget.attrs['placeholder'] = 'Enter your password'


class AccountSignupForm(SignupForm):
    full_name = forms.CharField(
        label='Full name',
        max_length=301,
        widget=forms.TextInput(attrs={'autocomplete': 'name', 'placeholder': 'e.g. John Doe'}),
    )
    field_order = ('full_name', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs['placeholder'] = 'e.g. john@example.com'
        self.fields['password1'].widget.attrs['placeholder'] = 'At least 8 characters'
        self.fields['password2'].widget.attrs['placeholder'] = 'Re-enter your password'

    def clean_full_name(self):
        full_name = ' '.join(self.cleaned_data['full_name'].split())
        first_name, _, last_name = full_name.partition(' ')
        if len(first_name) > 150 or len(last_name) > 150:
            raise forms.ValidationError('Enter a name with no more than 150 characters per part.')
        return full_name

    def save(self, request):
        user = super().save(request)
        first_name, _, last_name = self.cleaned_data['full_name'].partition(' ')
        user.first_name = first_name
        user.last_name = last_name
        user.save(update_fields=('first_name', 'last_name'))
        return user


class UserNameForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ('first_name', 'last_name')


def _topic_choices():
    from surveys.models import Topic
    return list(Topic.objects.filter(is_active=True).values_list('slug', 'name'))


class ResearchProfileForm(forms.ModelForm):
    region = forms.ChoiceField(
        required=False,
        choices=lambda: [('', 'Select your country first')] + demographics.subdivision_choices(),
        widget=forms.Select(attrs={'data-region-select': ''}),
        help_text='Region or district within your country.',
    )
    languages = forms.MultipleChoiceField(
        required=False,
        choices=demographics.LANGUAGE_CHOICES,
        widget=PillCheckboxSelectMultiple(),
        help_text='Select every language you can respond to a survey in.',
    )
    research_interests = forms.MultipleChoiceField(
        required=False,
        choices=_topic_choices,
        widget=PillCheckboxSelectMultiple(),
        help_text='Pick the subjects you would like to be surveyed about.',
    )

    class Meta:
        model = Profile
        fields = (
            'avatar',
            'birth_date',
            'gender',
            'country',
            'region',
            'languages',
            'education_level',
            'field_of_study',
            'employment_status',
            'industry',
            'income_bracket',
            'religion',
            'ethnicity',
            'occupation',
            'institution',
            'research_interests',
        )
        widgets = {
            'avatar': forms.ClearableFileInput(attrs={'data-avatar-input': '', 'accept': 'image/*'}),
            'birth_date': forms.DateInput(attrs={'type': 'date'}),
            'country': forms.Select(attrs={'data-region-country': ''}),
        }
        help_texts = {
            'income_bracket': 'Approximate personal income, kept private.',
        }

    def clean_region(self):
        region = self.cleaned_data.get('region', '')
        if region and region not in demographics.valid_subdivision_codes():
            raise forms.ValidationError('Select a supported region.')
        return region

    def clean(self):
        cleaned_data = super().clean()
        # A region must belong to the chosen country (its code is prefixed with
        # the ISO country code, e.g. ``BD-13``), otherwise clear it.
        country = cleaned_data.get('country')
        country_code = getattr(country, 'code', country) or ''
        region = cleaned_data.get('region')
        if region and country_code and not region.startswith(f'{country_code}-'):
            self.add_error('region', 'Choose a region inside your selected country.')
        elif region and not country_code:
            self.add_error('region', 'Select your country before choosing a region.')
        return cleaned_data
