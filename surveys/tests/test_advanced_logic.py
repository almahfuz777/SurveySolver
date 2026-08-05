from django.contrib.auth import get_user_model
from django.test import TestCase

from surveys import services
from surveys.builder.forms import BranchRuleForm, EligibilityCriteriaForm, QuestionEditorForm, ResponseLimitForm
from surveys.branching import Action, Operator
from surveys.models import Question, Survey


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

    def test_branch_and_response_limit_mutations_are_versioned(self):
        question, revision = services.add_question(
            self.section.id,
            Question.Type.SINGLE_CHOICE,
            self.version.revision,
        )
        second_section, revision = services.add_section(self.version.id, revision)
        branch_form = BranchRuleForm(
            data={
                'source_question': question.id,
                'operator': Operator.EQUALS,
                'compare_value': 'Option 1',
                'action': Action.GO_TO_SECTION,
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
        revision = services.update_response_limit(
            self.version.id,
            revision,
            100,
        )

        self.assertEqual(rule.target_section, second_section)
        self.survey.refresh_from_db()
        self.assertEqual(self.survey.response_limit, 100)
        self.assertEqual(revision, 5)

    def test_eligibility_criteria_are_validated_and_versioned(self):
        invalid = EligibilityCriteriaForm(data={'restrict_age': 'on', 'min_age': 30, 'max_age': 20})
        self.assertFalse(invalid.is_valid())

        form = EligibilityCriteriaForm(
            data={
                'restrict_age': 'on',
                'min_age': 18,
                'max_age': 25,
                'restrict_education': 'on',
                'education_levels': ['undergraduate', 'postgraduate'],
                'restrict_countries': 'on',
                'countries': ['BD'],
                'genders': [],
                'restrict_employment': 'on',
                'employment_statuses': ['student'],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        criteria, revision = services.update_eligibility(
            self.version.id,
            self.version.revision,
            form.cleaned_data,
        )

        self.assertTrue(criteria.is_targeted)
        self.assertEqual(criteria.countries, ['BD'])
        self.assertEqual(revision, 2)

    def test_unrestricted_eligibility_toggles_clear_hidden_values(self):
        form = EligibilityCriteriaForm(
            data={
                'min_age': 18,
                'countries': ['BD'],
                'genders': ['man'],
                'employment_statuses': ['student'],
                'education_levels': ['undergraduate'],
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data['min_age'])
        self.assertEqual(form.cleaned_data['countries'], [])
        self.assertEqual(form.cleaned_data['genders'], [])

    def test_response_limit_requires_a_value_only_when_enabled(self):
        self.assertTrue(ResponseLimitForm(data={}).is_valid())
        form = ResponseLimitForm(data={'enabled': 'on'})
        self.assertFalse(form.is_valid())
        self.assertIn('Enter the maximum', form.errors['response_limit'][0])
