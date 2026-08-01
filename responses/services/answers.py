"""Reading a posted answer into stored form, and testing it against branch rules."""
from datetime import date
from decimal import Decimal, InvalidOperation



from surveys.branching import Operator
from surveys.models import Question



def _empty(value):
    return value is None or value == '' or value == [] or value == {}


def _choice_map(question, allowed_ids=None):
    allowed_ids = set(allowed_ids or ())
    return {
        str(choice.id): choice.label
        for choice in question.choices.all()
        if not allowed_ids or str(choice.id) in allowed_ids
    }


def _selected_choice(question, raw_value, allowed_ids=None):
    choices = _choice_map(question, allowed_ids)
    if raw_value not in choices:
        raise ValueError('Select one of the available options.')
    return {'choice_id': raw_value, 'label': choices[raw_value]}


def normalize_answer(
    question,
    data,
    enforce_required=True,
    presentation_data=None,
):
    name = f'q_{question.id}'
    raw_value = data.get(name)
    if question.type in {Question.Type.MULTIPLE_CHOICE, Question.Type.RANKING}:
        raw_value = [value for value in data.getlist(name) if value]
    elif question.type == Question.Type.LIKERT_MATRIX:
        presented_rows = (
            presentation_data.get('rows', [])
            if presentation_data is not None
            else [str(row.id) for row in question.matrix_rows.all()]
        )
        raw_value = {
            row_id: data.get(f'{name}_{row_id}', '')
            for row_id in presented_rows
            if data.get(f'{name}_{row_id}', '')
        }

    required = (
        presentation_data.get('required', False)
        if presentation_data is not None
        else question.required
    )
    if _empty(raw_value):
        if required and enforce_required:
            raise ValueError('This question is required.')
        return None

    config = question.config
    if question.type in {Question.Type.SHORT_TEXT, Question.Type.LONG_TEXT}:
        value = raw_value.strip()
        minimum = config.get('min_length')
        maximum = config.get('max_length')
        if minimum is not None and len(value) < minimum:
            raise ValueError(f'Enter at least {minimum} characters.')
        if maximum is not None and len(value) > maximum:
            raise ValueError(f'Enter no more than {maximum} characters.')
        return value
    if question.type == Question.Type.NUMBER:
        try:
            number = Decimal(raw_value)
        except (InvalidOperation, TypeError):
            raise ValueError('Enter a valid number.') from None
        if not number.is_finite():
            raise ValueError('Enter a finite number.')
        minimum = config.get('min_value')
        maximum = config.get('max_value')
        if minimum is not None and number < Decimal(str(minimum)):
            raise ValueError(f'Enter a value of at least {minimum}.')
        if maximum is not None and number > Decimal(str(maximum)):
            raise ValueError(f'Enter a value no greater than {maximum}.')
        return str(number)
    if question.type == Question.Type.DATE:
        try:
            return date.fromisoformat(raw_value).isoformat()
        except (TypeError, ValueError):
            raise ValueError('Enter a valid date.') from None
    if question.type in {Question.Type.SINGLE_CHOICE, Question.Type.DROPDOWN}:
        return _selected_choice(
            question,
            raw_value,
            presentation_data.get('choices') if presentation_data else None,
        )
    if question.type == Question.Type.MULTIPLE_CHOICE:
        if len(raw_value) != len(set(raw_value)):
            raise ValueError('Select each option only once.')
        return [
            _selected_choice(
                question,
                value,
                presentation_data.get('choices') if presentation_data else None,
            )
            for value in raw_value
        ]
    if question.type == Question.Type.RANKING:
        choices = _choice_map(
            question,
            presentation_data.get('choices') if presentation_data else None,
        )
        if len(raw_value) != len(choices) or set(raw_value) != set(choices):
            raise ValueError('Rank every option exactly once.')
        return [
            _selected_choice(question, value, choices)
            for value in raw_value
        ]
    if question.type == Question.Type.SCALE:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            raise ValueError('Select a valid scale value.') from None
        minimum = int(config.get('scale_min', 1))
        maximum = int(config.get('scale_max', 5))
        if value < minimum or value > maximum:
            raise ValueError(f'Select a value from {minimum} to {maximum}.')
        return value
    if question.type == Question.Type.LIKERT_MATRIX:
        choices = _choice_map(
            question,
            presentation_data.get('choices') if presentation_data else None,
        )
        allowed_rows = set(presentation_data.get('rows', [])) if presentation_data else set()
        rows = {
            str(row.id): row.label
            for row in question.matrix_rows.all()
            if not allowed_rows or str(row.id) in allowed_rows
        }
        if required and set(raw_value) != set(rows):
            raise ValueError('Answer every statement in this matrix.')
        if not set(raw_value).issubset(rows):
            raise ValueError('The matrix response contains an invalid statement.')
        normalized = {}
        for row_id, choice_id in raw_value.items():
            if choice_id not in choices:
                raise ValueError('Select an available response for every statement.')
            normalized[row_id] = {
                'row_label': rows[row_id],
                'choice_id': choice_id,
                'choice_label': choices[choice_id],
            }
        return normalized
    raise ValueError('This question type is not supported.')


def _branch_values(value):
    if value is None:
        return []
    if isinstance(value, dict):
        if 'choice_id' in value:
            return [value['choice_id'], value['label']]
        values = []
        for row_value in value.values():
            values.extend((row_value['choice_id'], row_value['choice_label']))
        return values
    if isinstance(value, list):
        values = []
        for choice in value:
            values.extend((choice['choice_id'], choice['label']))
        return values
    return [str(value)]


def _branch_matches(rule, value):
    operator = rule['operator'] if isinstance(rule, dict) else rule.operator
    compare = (
        rule.get('compare_value', '')
        if isinstance(rule, dict)
        else rule.compare_value
    )
    if operator == Operator.ANSWERED:
        return bool(_branch_values(value))
    compare_value = compare.strip().casefold()
    values = [str(item).strip().casefold() for item in _branch_values(value)]
    if operator == Operator.EQUALS:
        return compare_value in values
    if operator == Operator.NOT_EQUALS:
        return bool(values) and compare_value not in values
    if operator == Operator.CONTAINS:
        return any(compare_value in item for item in values)
    return False
