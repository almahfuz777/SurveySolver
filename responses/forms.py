from django import forms

from .models import Submission


class ResponseFilterForm(forms.Form):
    COMPLETION_CHOICES = (
        ('all', 'All activity'),
        (Submission.Status.COMPLETED, 'Completed'),
        (Submission.Status.IN_PROGRESS, 'In progress'),
    )
    EXCLUSION_CHOICES = (
        ('included', 'Included only'),
        ('all', 'Included and excluded'),
        ('excluded', 'Excluded only'),
    )
    COLUMN_CHOICES = (
        ('started', 'Started'),
        ('status', 'Status'),
        ('version', 'Version'),
        ('source', 'Source'),
        ('duration', 'Duration'),
        ('respondent', 'Respondent'),
    )

    version = forms.ChoiceField(required=False)
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    completion = forms.ChoiceField(choices=COMPLETION_CHOICES, required=False)
    source = forms.ChoiceField(
        choices=(('', 'All sources'), *Submission.Source.choices),
        required=False,
    )
    eligibility = forms.ChoiceField(
        choices=(('all', 'All eligibility'), ('eligible', 'Eligible'), ('ineligible', 'Ineligible')),
        required=False,
    )
    exclusion = forms.ChoiceField(choices=EXCLUSION_CHOICES, required=False)
    search = forms.CharField(required=False, max_length=100)
    columns = forms.MultipleChoiceField(
        choices=COLUMN_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, survey, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['version'].choices = [('', 'All versions')] + [
            (str(version.id), f'Version {version.number}')
            for version in survey.versions.order_by('-number')
        ]
        if not self.is_bound:
            self.initial.update(
                {
                    'completion': 'all',
                    'eligibility': 'all',
                    'exclusion': 'included',
                    'columns': [choice[0] for choice in self.COLUMN_CHOICES],
                }
            )

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        if date_from and date_to and date_from > date_to:
            self.add_error('date_to', 'End date must be on or after the start date.')
        cleaned_data['columns'] = cleaned_data.get('columns') or [
            choice[0] for choice in self.COLUMN_CHOICES
        ]
        return cleaned_data
