from allauth.account.forms import LoginForm, SignupForm
from django import forms
from django.contrib.auth import get_user_model

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


class ResearchProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = (
            'birth_date',
            'gender',
            'gender_self_description',
            'country',
            'education_level',
            'field_of_study',
            'employment_status',
            'occupation',
            'institution',
            'research_interests',
        )
        widgets = {
            'birth_date': forms.DateInput(attrs={'type': 'date'}),
            'research_interests': forms.Textarea(attrs={'rows': 4}),
        }
        help_texts = {
            'research_interests': 'Describe the topics you are interested in responding to.',
            'gender_self_description': 'Complete only when you selected “Prefer to self-describe”.',
        }

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get('gender') == Profile.Gender.SELF_DESCRIBE
            and not cleaned_data.get('gender_self_description', '').strip()
        ):
            self.add_error(
                'gender_self_description',
                'Describe your gender or choose another option.',
            )
        return cleaned_data
