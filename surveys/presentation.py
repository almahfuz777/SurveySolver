import hashlib
import json
import random

from .branching import Action
from .models import Question, SurveyBranchRule


def _stable_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def resolved_version(version):
    """Return snapshot rows arranged exclusively by the live presentation layer.

    The returned model instances are annotated in memory for existing templates:
    legacy presentation fields are overwritten only on these loaded instances,
    never persisted. Related-manager prefetch caches are replaced with the
    resolved ordering so callers using ``section.questions.all`` and
    ``question.choices.all`` cannot accidentally fall back to snapshot order.
    """

    sections = list(
        version.sections.select_related('identity').prefetch_related(
            'questions__identity__section_identity',
            'questions__choices__identity',
            'questions__matrix_rows__identity',
        )
    )
    section_by_identity = {section.identity_id: section for section in sections}
    questions_by_section = {identity_id: [] for identity_id in section_by_identity}

    for section in sections:
        section.order = section.identity.order
        section.randomize_questions = section.identity.randomize_questions
        for question in list(section.questions.all()):
            target_identity_id = question.identity.section_identity_id
            if target_identity_id not in section_by_identity:
                continue
            question.order = question.identity.order
            question.required = question.identity.required
            question.randomize_choices = question.identity.randomize_choices
            choices = sorted(
                question.choices.all(),
                key=lambda item: (item.identity.order, str(item.identity_id)),
            )
            rows = sorted(
                question.matrix_rows.all(),
                key=lambda item: (item.identity.order, str(item.identity_id)),
            )
            for choice in choices:
                choice.order = choice.identity.order
            for row in rows:
                row.order = row.identity.order
            question._prefetched_objects_cache['choices'] = choices
            question._prefetched_objects_cache['matrix_rows'] = rows
            questions_by_section[target_identity_id].append(question)

    resolved_sections = sorted(
        sections,
        key=lambda item: (item.identity.order, str(item.identity_id)),
    )
    for section in resolved_sections:
        questions = sorted(
            questions_by_section[section.identity_id],
            key=lambda item: (item.identity.order, str(item.identity_id)),
        )
        section._prefetched_objects_cache['questions'] = questions
    return resolved_sections


def snapshot_maps(version):
    sections = resolved_version(version)
    section_map = {section.identity_id: section for section in sections}
    question_map = {}
    choice_map = {}
    row_map = {}
    for section in sections:
        for question in section.questions.all():
            question_map[question.identity_id] = question
            choice_map.update(
                {choice.identity_id: choice for choice in question.choices.all()}
            )
            row_map.update(
                {row.identity_id: row for row in question.matrix_rows.all()}
            )
    return sections, section_map, question_map, choice_map, row_map


def resolved_branch_rules(version):
    _, section_map, question_map, choice_map, _ = snapshot_maps(version)
    rules = []
    for rule in (
        SurveyBranchRule.objects.filter(survey=version.survey)
        .select_related(
            'source_question_identity',
            'compare_choice_identity',
            'target_section_identity',
        )
        .order_by('order', 'id')
    ):
        source = question_map.get(rule.source_question_identity_id)
        target = section_map.get(rule.target_section_identity_id)
        if source is None:
            continue
        if rule.action == Action.GO_TO_SECTION and target is None:
            continue
        compare_choice = choice_map.get(rule.compare_choice_identity_id)
        compare_value = (
            str(compare_choice.id)
            if compare_choice is not None
            else rule.compare_value
        )
        rules.append(
            {
                'id': str(rule.id),
                'source_question_id': str(source.id),
                'source_section_id': str(
                    section_map[source.identity.section_identity_id].id
                ),
                'operator': rule.operator,
                'compare_value': compare_value,
                'action': rule.action,
                'target_section_id': str(target.id) if target else None,
                'order': rule.order,
            }
        )
    return rules


def questionnaire_content(version):
    sections = resolved_version(version)
    content = {
        'sections': [],
        'questions': [],
        'choices': [],
        'matrix_rows': [],
    }
    for section in sections:
        content['sections'].append(
            {
                'identity': str(section.identity_id),
                'title': section.title,
                'description': section.description,
            }
        )
        for question in section.questions.all():
            content['questions'].append(
                {
                    'identity': str(question.identity_id),
                    'type': question.type,
                    'prompt': question.prompt,
                    'help_text': question.help_text,
                    'config': question.config,
                }
            )
            content['choices'].extend(
                {
                    'identity': str(choice.identity_id),
                    'question_identity': str(question.identity_id),
                    'label': choice.label,
                }
                for choice in question.choices.all()
            )
            content['matrix_rows'].extend(
                {
                    'identity': str(row.identity_id),
                    'question_identity': str(question.identity_id),
                    'label': row.label,
                }
                for row in question.matrix_rows.all()
            )
    for values in content.values():
        values.sort(key=lambda item: item['identity'])
    return content


def questionnaire_signature(version):
    return hashlib.sha256(_stable_json(questionnaire_content(version)).encode()).hexdigest()


def content_changed(draft, active):
    return active is None or questionnaire_signature(draft) != questionnaire_signature(active)


def build_submission_presentation(version):
    generator = random.SystemRandom()
    sections, _, _, _, _ = snapshot_maps(version)
    section_data = []
    configuration = {'sections': [], 'branch_rules': resolved_branch_rules(version)}

    for section in sections:
        # `ordered_questions` keeps the canonical (unshuffled) order so the
        # configuration fingerprint stays stable across starts; `presented`
        # is the per-respondent shuffle that only feeds the visible order.
        ordered_questions = list(section.questions.all())
        configured_question_ids = [str(question.id) for question in ordered_questions]
        configured_questions = [
            {
                'id': str(question.id),
                'required': question.required,
                'randomize_choices': question.randomize_choices,
                'choices': [str(choice.id) for choice in question.choices.all()],
                'rows': [str(row.id) for row in question.matrix_rows.all()],
            }
            for question in ordered_questions
        ]

        presented = list(ordered_questions)
        if section.randomize_questions:
            generator.shuffle(presented)
        questions_data = []
        for question in presented:
            choices = list(question.choices.all())
            if question.randomize_choices:
                generator.shuffle(choices)
            rows = list(question.matrix_rows.all())
            questions_data.append(
                {
                    'id': str(question.id),
                    'required': question.required,
                    'choices': [str(choice.id) for choice in choices],
                    'rows': [str(row.id) for row in rows],
                }
            )
        section_data.append({'id': str(section.id), 'questions': questions_data})
        configuration['sections'].append(
            {
                'id': str(section.id),
                'randomize_questions': section.randomize_questions,
                'questions': configured_questions,
                'ordered_question_ids': configured_question_ids,
            }
        )

    fingerprint = hashlib.sha256(
        _stable_json(configuration).encode()
    ).hexdigest()
    return {
        'schema': 2,
        'sections': section_data,
        'branch_rules': configuration['branch_rules'],
        'fingerprint': fingerprint,
    }


def presented_question_ids(presentation):
    return [
        question['id']
        for section in presentation.get('sections', [])
        for question in section.get('questions', [])
    ]


def presentation_question(presentation, question_id):
    question_id = str(question_id)
    for section in presentation.get('sections', []):
        for question in section.get('questions', []):
            if question.get('id') == question_id:
                return question
    return None
