from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase

from surveys.models import MatrixRow, Question, QuestionChoice, QuestionIdentity, Survey

from responses.services import normalize_answer


class AnswerNormalizationTests(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user(email='owner@example.com')
        survey = Survey.objects.create(
            owner=owner,
            title='Question validation',
            summary='Question validation fixtures.',
        )
        self.section = survey.draft_version.sections.get()

    def question(self, question_type, required=False, **kwargs):
        question = Question.objects.create(
            section=self.section,
            type=question_type,
            prompt=f'{question_type} question',
            **kwargs,
        )
        if required:
            QuestionIdentity.objects.filter(pk=question.identity_id).update(required=True)
            question.refresh_from_db()
        return question

    def choices(self, question, labels):
        return [
            QuestionChoice.objects.create(question=question, label=label,)
            for index, label in enumerate(labels, start=1)
        ]

    def test_numeric_date_and_scale_constraints_are_server_authoritative(self):
        number = self.question(
            Question.Type.NUMBER,
            config={'min_value': 2, 'max_value': 8},
        )
        scale = self.question(
            Question.Type.SCALE,
            config={'scale_min': 1, 'scale_max': 5},
        )
        date_question = self.question(Question.Type.DATE)

        with self.assertRaisesMessage(ValueError, 'at least 2'):
            normalize_answer(number, QueryDict(f'q_{number.id}=1'))
        with self.assertRaisesMessage(ValueError, 'from 1 to 5'):
            normalize_answer(scale, QueryDict(f'q_{scale.id}=7'))
        self.assertEqual(
            normalize_answer(date_question, QueryDict(f'q_{date_question.id}=2026-07-10')),
            '2026-07-10',
        )

    def test_tampered_choice_and_duplicate_ranking_are_rejected(self):
        single = self.question(Question.Type.SINGLE_CHOICE)
        self.choices(single, ['Yes', 'No'])
        ranking = self.question(Question.Type.RANKING)
        rank_choices = self.choices(ranking, ['First', 'Second'])

        with self.assertRaisesMessage(ValueError, 'available options'):
            normalize_answer(single, QueryDict(f'q_{single.id}=not-a-choice'))
        data = QueryDict('', mutable=True)
        data.setlist(
            f'q_{ranking.id}',
            [str(rank_choices[0].id), str(rank_choices[0].id)],
        )
        with self.assertRaisesMessage(ValueError, 'exactly once'):
            normalize_answer(ranking, data)

    def test_required_likert_matrix_requires_every_row(self):
        matrix = self.question(Question.Type.LIKERT_MATRIX, required=True)
        choices = self.choices(matrix, ['Agree', 'Disagree'])
        rows = [
            MatrixRow.objects.create(question=matrix, label=label,)
            for index, label in enumerate(['Statement one', 'Statement two'], start=1)
        ]
        data = QueryDict('', mutable=True)
        data[f'q_{matrix.id}_{rows[0].id}'] = str(choices[0].id)

        with self.assertRaisesMessage(ValueError, 'every statement'):
            normalize_answer(matrix, data)
