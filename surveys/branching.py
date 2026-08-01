"""Vocabulary and rules for conditional branching.

Kept out of ``models.py`` so the runtime evaluator, the builder forms and the
stored rule can share one definition without any of them owning it. Nothing
here touches the database.
"""
from functools import cache

from django.db import models


class Operator(models.TextChoices):
    EQUALS = 'equals', 'Equals'
    NOT_EQUALS = 'not_equals', 'Does not equal'
    CONTAINS = 'contains', 'Contains'
    ANSWERED = 'answered', 'Is answered'


class Action(models.TextChoices):
    GO_TO_SECTION = 'go_to_section', 'Go to section'
    END_SURVEY = 'end_survey', 'End survey'


@cache
def _operators_by_question_type():
    # Imported lazily because models.py reads the choices above; a module-level import would be circular.
    from .models import Question

    # Which conditions actually make sense to evaluate against each answer shape.
    # e.g. "contains" is meaningless for a single-answer choice, "equals" is meaningless for a matrix whose answer is one value per row.
    return {
        Question.Type.SINGLE_CHOICE: (Operator.EQUALS, Operator.NOT_EQUALS, Operator.ANSWERED),
        Question.Type.DROPDOWN: (Operator.EQUALS, Operator.NOT_EQUALS, Operator.ANSWERED),
        Question.Type.MULTIPLE_CHOICE: (Operator.CONTAINS, Operator.ANSWERED),
        Question.Type.RANKING: (Operator.ANSWERED,),
        Question.Type.LIKERT_MATRIX: (Operator.ANSWERED,),
        Question.Type.SCALE: (Operator.EQUALS, Operator.NOT_EQUALS, Operator.ANSWERED),
        Question.Type.NUMBER: (Operator.EQUALS, Operator.NOT_EQUALS, Operator.ANSWERED),
        Question.Type.SHORT_TEXT: (
            Operator.EQUALS,
            Operator.NOT_EQUALS,
            Operator.CONTAINS,
            Operator.ANSWERED,
        ),
        Question.Type.LONG_TEXT: (Operator.CONTAINS, Operator.ANSWERED),
        Question.Type.DATE: (Operator.EQUALS, Operator.NOT_EQUALS, Operator.ANSWERED),
    }


def allowed_operators(question_type):
    return _operators_by_question_type().get(question_type, tuple(Operator.values))
