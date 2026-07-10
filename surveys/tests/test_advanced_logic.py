from django.contrib.auth import get_user_model
from django.test import TestCase

from surveys import services
from surveys.forms import BranchRuleForm, QuestionEditorForm
from surveys.models import BranchRule, Question, Survey


class AdvancedLogicTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email='logic@example.com')
        self.survey = Survey.objects.create(
            owner=self.user,
            title='Logic study',
            summary='Advanced questionnaire controls.',
        )
        self.version = self.survey.draft_version
        self.section = self.version.sections.get()

    def test_matrix_question_starts_with_rows_and_scale_choices(self):
        question, revision = services.add_question(
            self.section.id,
            Question.Type.LIKERT_MATRIX,
            self.version.revision,
        )

        self.assertEqual(question.matrix_rows.count(), 2)
        self.assertEqual(question.choices.count(), 5)
        self.assertEqual(revision, 2)

    def test_matrix_editor_requires_unique_rows_and_choices(self):
        question, _ = services.add_question(
            self.section.id,
            Question.Type.LIKERT_MATRIX,
            self.version.revision,
        )
        form = QuestionEditorForm(
            data={
                'type': Question.Type.LIKERT_MATRIX,
                'prompt': 'Rate each statement',
                'choices_text': 'Agree\nAgree',
                'rows_text': 'Statement one',
            },
            instance=question,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('Choices must be unique.', form.errors['choices_text'])
        self.assertIn('Add at least two matrix statements.', form.errors['rows_text'])

    def test_branch_and_quota_mutations_are_versioned(self):
        question, revision = services.add_question(
            self.section.id,
            Question.Type.SINGLE_CHOICE,
            self.version.revision,
        )
        second_section, revision = services.add_section(self.version.id, revision)
        branch_form = BranchRuleForm(
            data={
                'source_question': question.id,
                'operator': BranchRule.Operator.EQUALS,
                'compare_value': 'Option 1',
                'action': BranchRule.Action.GO_TO_SECTION,
                'target_section': second_section.id,
            },
            version=self.version,
        )
        self.assertTrue(branch_form.is_valid(), branch_form.errors)

        rule, revision = services.add_branch_rule(
            self.version.id,
            revision,
            branch_form.cleaned_data,
        )
        quota, revision = services.add_quota(
            self.version.id,
            revision,
            {'name': 'First cohort', 'limit': 100, 'is_active': True},
        )

        self.assertEqual(rule.target_section, second_section)
        self.assertEqual(quota.limit, 100)
        self.assertEqual(revision, 5)
