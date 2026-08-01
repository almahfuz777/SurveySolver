"""Validating a branch condition before it becomes a live rule."""
from django import forms


from .. import branching
from ..models import Question, Section


class BranchConditionForm(forms.Form):
    """Shared validation for a branch condition before it becomes a live rule.

    Rules are stored as SurveyBranchRule rows keyed to stable identities, so
    these forms only validate the creator's input and hand cleaned values to
    ``services.add_branch_rule``.
    """

    operator = forms.ChoiceField(choices=branching.Operator.choices)
    compare_value = forms.CharField(max_length=240, required=False)
    action = forms.ChoiceField(choices=branching.Action.choices)
    target_section = forms.ModelChoiceField(queryset=Section.objects.none(), required=False)

    def clean(self):
        cleaned_data = super().clean()
        operator = cleaned_data.get('operator')
        if operator != branching.Operator.ANSWERED and not cleaned_data.get('compare_value', '').strip():
            self.add_error('compare_value', 'Enter the answer value used by this condition.')
        if cleaned_data.get('action') == branching.Action.GO_TO_SECTION and not cleaned_data.get('target_section'):
            self.add_error('target_section', 'A target section is required for this action.')
        return cleaned_data


class BranchRuleForm(BranchConditionForm):
    source_question = forms.ModelChoiceField(queryset=Question.objects.none())

    field_order = ('source_question', 'operator', 'compare_value', 'action', 'target_section')

    def __init__(self, *args, version, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['source_question'].queryset = Question.objects.filter(section__version=version)
        self.fields['target_section'].queryset = Section.objects.filter(version=version)


class QuestionBranchForm(BranchConditionForm):
    def __init__(self, *args, version, question, **kwargs):
        super().__init__(*args, **kwargs)
        self.question = question
        self.fields['target_section'].queryset = Section.objects.filter(version=version)

        # Only offer conditions that can actually match this question's answers.
        allowed = branching.allowed_operators(question.type)
        self.fields['operator'].choices = [
            (value, label) for value, label in branching.Operator.choices if value in allowed
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
        self.fields['action'].initial = branching.Action.GO_TO_SECTION
        self.fields['action'].widget.attrs['data-branch-action'] = ''
        self.fields['target_section'].widget.attrs['data-branch-target'] = ''

    def clean(self):
        cleaned_data = super().clean()
        operator = cleaned_data.get('operator')
        if operator and operator not in branching.allowed_operators(self.question.type):
            self.add_error('operator', 'Choose a condition that fits this question type.')
        return cleaned_data
