from django import forms
from django.contrib.auth import get_user_model

from .models import Profile


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
