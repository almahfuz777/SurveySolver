"""Editing the questionnaire itself: sections and questions."""
from django import forms


from ..models import Question, Section


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
