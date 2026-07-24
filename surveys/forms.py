from django import forms
from django_countries import countries

from accounts import demographics
from accounts.models import Profile

from .models import BranchRule, Question, Section, Survey, Topic




class PillCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    template_name = 'surveys/widgets/pill_select.html'


class SurveyMetadataForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['topics'].queryset = Topic.objects.filter(is_active=True)

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
    choice_identities_text = forms.CharField(required=False, widget=forms.HiddenInput())
    row_identities_text = forms.CharField(required=False, widget=forms.HiddenInput())
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
        widgets = {
            'prompt': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Question prompt'}),
            'help_text': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Shown under the question'}),
        }

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
                choice.label for choice in self.instance.choices.all()
            )
            self.fields['choice_identities_text'].initial = '\n'.join(
                str(choice.identity_id) for choice in self.instance.choices.all()
            )
            self.fields['rows_text'].initial = '\n'.join(
                row.label for row in self.instance.matrix_rows.all()
            )
            self.fields['row_identities_text'].initial = '\n'.join(
                str(row.identity_id) for row in self.instance.matrix_rows.all()
            )

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
            cleaned_data['choice_identity_ids'] = [
                line.strip()
                for line in cleaned_data.get('choice_identities_text', '').splitlines()
            ][:len(choices)]
        else:
            cleaned_data['choice_labels'] = []
            cleaned_data['choice_identity_ids'] = []
            cleaned_data['randomize_choices'] = False

        rows = [line.strip() for line in cleaned_data.get('rows_text', '').splitlines() if line.strip()]
        if question_type == Question.Type.LIKERT_MATRIX and len(rows) < 2:
            self.add_error('rows_text', 'Add at least two matrix statements.')
        if len({row.casefold() for row in rows}) != len(rows):
            self.add_error('rows_text', 'Matrix statements must be unique.')
        cleaned_data['row_labels'] = rows if question_type == Question.Type.LIKERT_MATRIX else []
        cleaned_data['row_identity_ids'] = (
            [
                line.strip()
                for line in cleaned_data.get('row_identities_text', '').splitlines()
            ][:len(rows)]
            if question_type == Question.Type.LIKERT_MATRIX
            else []
        )

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


class QuestionBranchForm(forms.ModelForm):
    class Meta:
        model = BranchRule
        fields = ('operator', 'compare_value', 'action', 'target_section')

    def __init__(self, *args, version, question, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.version = version
        self.instance.source_question = question
        self.question = question
        self.fields['target_section'].queryset = Section.objects.filter(version=version)

        # Only offer conditions that can actually match this question's answers.
        allowed = BranchRule.allowed_operators(question.type)
        self.fields['operator'].choices = [
            (value, label) for value, label in BranchRule.Operator.choices if value in allowed
        ]

        # For choice questions the compared value must be one of the defined
        # options, so pick from them instead of free-typing a value that can
        # never match. Ranking/matrix only support "is answered" (no value).
        value_from_choices = question.accepts_choices and question.type not in {
            Question.Type.RANKING,
            Question.Type.LIKERT_MATRIX,
        }
        if value_from_choices:
            labels = [choice.label for choice in question.choices.all()]
            self.fields['compare_value'] = forms.ChoiceField(
                required=False,
                choices=[('', 'Choose an option…')] + [(label, label) for label in labels],
            )
        self.fields['compare_value'].widget.attrs['placeholder'] = 'Answer value'
        self.fields['compare_value'].widget.attrs['data-branch-value'] = ''
        self.fields['operator'].widget.attrs['data-branch-operator'] = ''
        self.fields['action'].choices = BranchRule.Action.choices
        self.fields['action'].initial = BranchRule.Action.GO_TO_SECTION
        self.fields['action'].widget.attrs['data-branch-action'] = ''
        self.fields['target_section'].widget.attrs['data-branch-target'] = ''

    def clean(self):
        cleaned_data = super().clean()
        operator = cleaned_data.get('operator')
        if operator and operator not in BranchRule.allowed_operators(self.question.type):
            self.add_error('operator', 'Choose a condition that fits this question type.')
        if operator != BranchRule.Operator.ANSWERED and not cleaned_data.get('compare_value', '').strip():
            self.add_error('compare_value', 'Enter the answer value used by this condition.')
        return cleaned_data


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
