"""Survey-level settings: metadata, builder header and banner artwork."""
from django import forms


from ..models import Survey, Topic
from .widgets import PillCheckboxSelectMultiple


class SurveyMetadataForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['topics'].queryset = Topic.objects.filter(is_active=True)
        self.fields['identity_mode'].choices = [
            (Survey.IdentityMode.ANONYMOUS, 'Anonymous'),
            (Survey.IdentityMode.IDENTIFIED, 'Collect Responder Profiles'),
        ]

    class Meta:
        model = Survey
        fields = (
            'topics',
            'visibility',
            'identity_mode',
            'estimated_minutes',
        )
        widgets = {
            'topics': PillCheckboxSelectMultiple(attrs={'maxselect': 3}),
            'visibility': forms.RadioSelect(),
            'identity_mode': forms.RadioSelect(),
            'estimated_minutes': forms.NumberInput(attrs={'data-stepper-input': 'estimated_minutes', 'min': 1, 'max': 120}),
        }
        help_texts = {
            'topics': 'Select up to three subjects that accurately describe this research.',
            'visibility': 'Discoverable surveys can appear in matched respondent feeds.',
            'identity_mode': 'Identified collection requires explicit respondent consent.',
            'estimated_minutes': 'A realistic completion estimate between 1 and 120 minutes.',
        }

    def clean_topics(self):
        topics = self.cleaned_data['topics']
        if topics.count() > 3:
            raise forms.ValidationError('Select no more than three topics.')
        return topics


class SurveyBuilderHeaderForm(forms.ModelForm):
    """Survey-level copy edited from the questionnaire canvas."""

    summary = forms.CharField(required=False, max_length=320)

    class Meta:
        model = Survey
        fields = ('title', 'summary')


class SurveyBannerForm(forms.ModelForm):
    """Cover image edited independently from the full settings form."""

    class Meta:
        model = Survey
        fields = ('banner',)
