from django import forms

from .models import Survey, Topic


class SurveyMetadataForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['topics'].queryset = Topic.objects.filter(is_active=True)

    class Meta:
        model = Survey
        fields = (
            'title',
            'summary',
            'description',
            'topics',
            'visibility',
            'identity_mode',
            'estimated_minutes',
            'banner',
            'thumbnail',
        )
        widgets = {
            'description': forms.Textarea(attrs={'rows': 6}),
            'topics': forms.CheckboxSelectMultiple(),
        }
        help_texts = {
            'summary': 'A concise explanation shown on survey discovery cards.',
            'topics': 'Select up to five subjects that accurately describe this research.',
            'visibility': 'Discoverable surveys can appear in matched respondent feeds.',
            'identity_mode': 'Identified collection requires explicit respondent consent.',
            'estimated_minutes': 'A realistic completion estimate between 1 and 120 minutes.',
            'banner': 'Optional JPG, PNG, or WebP image up to 5 MB.',
            'thumbnail': 'Optional square or landscape image up to 5 MB.',
        }

    def clean_topics(self):
        topics = self.cleaned_data['topics']
        if topics.count() > 5:
            raise forms.ValidationError('Select no more than five topics.')
        return topics
