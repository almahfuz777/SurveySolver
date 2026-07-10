from django import forms
from django_countries import countries

from accounts.models import Profile

from .models import BranchRule, Question, Quota, Section, Survey, Topic


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


class SectionForm(forms.ModelForm):
    class Meta:
        model = Section
        fields = ('title', 'description', 'randomize_questions')
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}


class QuestionEditorForm(forms.ModelForm):
    choices_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 5}),
        help_text='Enter one choice per line.',
    )
    rows_text = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 4}), help_text='Enter one matrix statement per line.')
    min_value = forms.DecimalField(required=False)
    max_value = forms.DecimalField(required=False)
    min_length = forms.IntegerField(required=False, min_value=0)
    max_length = forms.IntegerField(required=False, min_value=1, max_value=5000)
    scale_min = forms.IntegerField(required=False, min_value=0, max_value=9)
    scale_max = forms.IntegerField(required=False, min_value=1, max_value=10)
    scale_min_label = forms.CharField(required=False, max_length=80)
    scale_max_label = forms.CharField(required=False, max_length=80)

    class Meta:
        model = Question
        fields = ('type', 'prompt', 'help_text', 'required', 'randomize_choices')
        widgets = {'help_text': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            config = self.instance.config
            for field_name in (
                'min_value',
                'max_value',
                'min_length',
                'max_length',
                'scale_min',
                'scale_max',
                'scale_min_label',
                'scale_max_label',
            ):
                self.fields[field_name].initial = config.get(field_name)
            self.fields['choices_text'].initial = '\n'.join(
                self.instance.choices.values_list('label', flat=True)
            )
            self.fields['rows_text'].initial = '\n'.join(self.instance.matrix_rows.values_list('label', flat=True))

    def clean(self):
        cleaned_data = super().clean()
        question_type = cleaned_data.get('type')

        if question_type in {
            Question.Type.SINGLE_CHOICE,
            Question.Type.MULTIPLE_CHOICE,
            Question.Type.DROPDOWN,
            Question.Type.RANKING,
            Question.Type.LIKERT_MATRIX,
        }:
            choices = [
                line.strip()
                for line in cleaned_data.get('choices_text', '').splitlines()
                if line.strip()
            ]
            if len(choices) < 2:
                self.add_error('choices_text', 'Add at least two choices.')
            if len({choice.casefold() for choice in choices}) != len(choices):
                self.add_error('choices_text', 'Choices must be unique.')
            cleaned_data['choice_labels'] = choices
        else:
            cleaned_data['choice_labels'] = []
            cleaned_data['randomize_choices'] = False

        rows = [line.strip() for line in cleaned_data.get('rows_text', '').splitlines() if line.strip()]
        if question_type == Question.Type.LIKERT_MATRIX and len(rows) < 2:
            self.add_error('rows_text', 'Add at least two matrix statements.')
        if len({row.casefold() for row in rows}) != len(rows):
            self.add_error('rows_text', 'Matrix statements must be unique.')
        cleaned_data['row_labels'] = rows if question_type == Question.Type.LIKERT_MATRIX else []

        minimum = cleaned_data.get('min_value')
        maximum = cleaned_data.get('max_value')
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error('max_value', 'Maximum must be greater than or equal to minimum.')

        min_length = cleaned_data.get('min_length')
        max_length = cleaned_data.get('max_length')
        if min_length is not None and max_length is not None and min_length > max_length:
            self.add_error('max_length', 'Maximum length must be at least the minimum length.')

        if question_type == Question.Type.SCALE:
            scale_min = cleaned_data.get('scale_min')
            scale_max = cleaned_data.get('scale_max')
            if scale_min is None:
                scale_min = 1
                cleaned_data['scale_min'] = scale_min
            if scale_max is None:
                scale_max = 5
                cleaned_data['scale_max'] = scale_max
            if scale_min >= scale_max:
                self.add_error('scale_max', 'Scale maximum must be greater than minimum.')

        return cleaned_data

    def question_config(self):
        question_type = self.cleaned_data['type']
        config = {}
        if question_type == Question.Type.NUMBER:
            for key in ('min_value', 'max_value'):
                value = self.cleaned_data.get(key)
                if value is not None:
                    config[key] = float(value)
        elif question_type in {Question.Type.SHORT_TEXT, Question.Type.LONG_TEXT}:
            for key in ('min_length', 'max_length'):
                value = self.cleaned_data.get(key)
                if value is not None:
                    config[key] = value
        elif question_type == Question.Type.SCALE:
            for key in ('scale_min', 'scale_max', 'scale_min_label', 'scale_max_label'):
                value = self.cleaned_data.get(key)
                if value not in (None, ''):
                    config[key] = value
        return config


class BranchRuleForm(forms.ModelForm):
    class Meta:
        model = BranchRule
        fields = ('source_question', 'operator', 'compare_value', 'action', 'target_section')

    def __init__(self, *args, version, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.version = version
        self.fields['source_question'].queryset = Question.objects.filter(section__version=version)
        self.fields['target_section'].queryset = Section.objects.filter(version=version)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('operator') != BranchRule.Operator.ANSWERED and not cleaned_data.get('compare_value', '').strip():
            self.add_error('compare_value', 'Enter the answer value used by this condition.')
        return cleaned_data


class QuotaForm(forms.ModelForm):
    class Meta:
        model = Quota
        fields = ('name', 'limit', 'is_active')


class EligibilityCriteriaForm(forms.Form):
    min_age = forms.IntegerField(required=False, min_value=0, max_value=120)
    max_age = forms.IntegerField(required=False, min_value=0, max_value=120)
    education_levels = forms.MultipleChoiceField(
        required=False,
        choices=Profile.EducationLevel.choices,
    )
    countries = forms.MultipleChoiceField(required=False, choices=countries)
    genders = forms.MultipleChoiceField(required=False, choices=Profile.Gender.choices)
    employment_statuses = forms.MultipleChoiceField(
        required=False,
        choices=Profile.EmploymentStatus.choices,
    )

    def clean(self):
        cleaned_data = super().clean()
        minimum = cleaned_data.get('min_age')
        maximum = cleaned_data.get('max_age')
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error('max_age', 'Maximum age must be at least the minimum age.')
        return cleaned_data
