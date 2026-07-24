"""Creator-facing comparison between the working draft and the live version.

Only version-triggering content is compared — the same content the questionnaire
signature covers. Presentation controls (ordering, placement, required state,
randomization, branching) apply live and never appear here, because publishing
does not change them.

Both sides are read through ``resolved_version`` so the two structures line up on
the shared identity lineage: an identity present on both sides is the same piece
of content, which is what lets us report "changed" instead of "removed + added".
"""

from .presentation import resolved_version


SECTION_FIELDS = (
    ('title', 'Title'),
    ('description', 'Description'),
)

QUESTION_FIELDS = (
    ('prompt', 'Prompt'),
    ('help_text', 'Help text'),
)

CONFIG_LABELS = {
    'min_value': 'Minimum value',
    'max_value': 'Maximum value',
    'min_length': 'Minimum length',
    'max_length': 'Maximum length',
    'scale_min': 'Scale minimum',
    'scale_max': 'Scale maximum',
    'scale_min_label': 'Scale minimum label',
    'scale_max_label': 'Scale maximum label',
}

ADDED = 'added'
REMOVED = 'removed'
CHANGED = 'changed'
UNCHANGED = 'unchanged'


def _blank(value):
    return '—' if value in (None, '') else value


def _field_changes(before, after, fields):
    changes = []
    for attribute, label in fields:
        old = getattr(before, attribute)
        new = getattr(after, attribute)
        if old != new:
            changes.append({'label': label, 'from': _blank(old), 'to': _blank(new)})
    return changes


def _config_changes(before, after):
    changes = []
    for key in sorted(set(before.config) | set(after.config)):
        old = before.config.get(key)
        new = after.config.get(key)
        if old != new:
            changes.append(
                {
                    'label': CONFIG_LABELS.get(key, key.replace('_', ' ').capitalize()),
                    'from': _blank(old),
                    'to': _blank(new),
                }
            )
    return changes


def _question_changes(before, after):
    changes = _field_changes(before, after, QUESTION_FIELDS)
    if before.type != after.type:
        changes.insert(
            0,
            {
                'label': 'Type',
                'from': before.get_type_display(),
                'to': after.get_type_display(),
            },
        )
    changes.extend(_config_changes(before, after))
    return changes


def _label_entries(before_items, after_items):
    """Diff a question's choices or matrix rows, matched on identity lineage."""
    before_by_identity = {item.identity_id: item for item in before_items}
    after_by_identity = {item.identity_id: item for item in after_items}
    entries = []
    changed = False
    for item in after_items:
        previous = before_by_identity.get(item.identity_id)
        if previous is None:
            entries.append({'status': ADDED, 'label': item.label, 'previous': None})
            changed = True
        elif previous.label != item.label:
            entries.append({'status': CHANGED, 'label': item.label, 'previous': previous.label})
            changed = True
        else:
            entries.append({'status': UNCHANGED, 'label': item.label, 'previous': None})
    for item in before_items:
        if item.identity_id not in after_by_identity:
            entries.append({'status': REMOVED, 'label': item.label, 'previous': None})
            changed = True
    return entries, changed


def _question_entry(status, question, previous=None):
    changes = _question_changes(previous, question) if previous is not None else []
    choices, choices_changed = _label_entries(
        list(previous.choices.all()) if previous is not None else [],
        list(question.choices.all()),
    )
    rows, rows_changed = _label_entries(
        list(previous.matrix_rows.all()) if previous is not None else [],
        list(question.matrix_rows.all()),
    )
    if status == CHANGED and not (changes or choices_changed or rows_changed):
        status = UNCHANGED
    if status in (ADDED, REMOVED):
        # Nothing to compare against, so show the content as-is rather than as
        # a list of per-field edits.
        choices = [
            {'status': status, 'label': choice.label, 'previous': None}
            for choice in question.choices.all()
        ]
        rows = [
            {'status': status, 'label': row.label, 'previous': None}
            for row in question.matrix_rows.all()
        ]
    return {
        'status': status,
        'identity': str(question.identity_id),
        'prompt': question.prompt,
        'help_text': question.help_text,
        'type_label': question.get_type_display(),
        'changes': changes,
        'choices': choices,
        'rows': rows,
    }


def _section_questions(draft_section, active_section):
    draft_questions = list(draft_section.questions.all()) if draft_section else []
    active_questions = list(active_section.questions.all()) if active_section else []
    active_by_identity = {question.identity_id: question for question in active_questions}
    draft_identities = {question.identity_id for question in draft_questions}

    entries = []
    for question in draft_questions:
        previous = active_by_identity.get(question.identity_id)
        if previous is None:
            entries.append(_question_entry(ADDED, question))
        else:
            entries.append(_question_entry(CHANGED, question, previous))
    for question in active_questions:
        if question.identity_id not in draft_identities:
            entries.append(_question_entry(REMOVED, question))
    return entries


def _section_entry(status, draft_section, active_section):
    questions = _section_questions(draft_section, active_section)
    section = draft_section or active_section
    changes = (
        _field_changes(active_section, draft_section, SECTION_FIELDS)
        if status == CHANGED
        else []
    )
    if status == CHANGED and not changes and all(
        question['status'] == UNCHANGED for question in questions
    ):
        status = UNCHANGED
    return {
        'status': status,
        'identity': str(section.identity_id),
        'title': section.title,
        'description': section.description,
        'changes': changes,
        'questions': questions,
    }


def question_change_map(draft, active):
    """Map question identity -> 'added'/'changed' for builder gutter markers.

    Returns an empty map when nothing is published yet: with no live version to
    compare against, marking every question as new is noise rather than signal.
    """
    if active is None:
        return {}
    diff = questionnaire_diff(draft, active)
    return {
        question['identity']: question['status']
        for section in diff['sections']
        for question in section['questions']
        if question['status'] in (ADDED, CHANGED)
    }


def questionnaire_diff(draft, active):
    """Return an ordered, colour-codable comparison of draft vs live content."""
    draft_sections = resolved_version(draft)
    active_sections = resolved_version(active) if active is not None else []
    active_by_identity = {section.identity_id: section for section in active_sections}
    draft_identities = {section.identity_id for section in draft_sections}

    sections = []
    for section in draft_sections:
        previous = active_by_identity.get(section.identity_id)
        if previous is None:
            sections.append(_section_entry(ADDED, section, None))
        else:
            sections.append(_section_entry(CHANGED, section, previous))
    for section in active_sections:
        if section.identity_id not in draft_identities:
            sections.append(_section_entry(REMOVED, None, section))

    counts = {
        'sections_added': 0,
        'sections_removed': 0,
        'sections_changed': 0,
        'questions_added': 0,
        'questions_removed': 0,
        'questions_changed': 0,
    }
    for section in sections:
        if section['status'] == ADDED:
            counts['sections_added'] += 1
        elif section['status'] == REMOVED:
            counts['sections_removed'] += 1
        elif section['status'] == CHANGED:
            counts['sections_changed'] += 1
        for question in section['questions']:
            if question['status'] == ADDED:
                counts['questions_added'] += 1
            elif question['status'] == REMOVED:
                counts['questions_removed'] += 1
            elif question['status'] == CHANGED:
                counts['questions_changed'] += 1

    return {
        'sections': sections,
        'counts': counts,
        'has_changes': any(value for value in counts.values()),
        'is_first_publication': active is None,
    }
