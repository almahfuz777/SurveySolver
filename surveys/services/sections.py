"""Adding, editing, reordering and removing a draft's sections."""
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Max

from ..models import (
    Question,
    Section,
    SectionIdentity,
)
from .drafting import (
    _bump_revision,
    _lock_version,
    _version_section_identities,
)


@transaction.atomic
def add_section(version_id, expected_revision):
    version = _lock_version(version_id, expected_revision)
    order = (
        _version_section_identities(version).aggregate(max_order=Max('order'))['max_order']
        or 0
    ) + 1
    identity = SectionIdentity.objects.create(survey=version.survey, order=order)
    section = Section.objects.create(
        version=version,
        identity=identity,
        title=f'Section {order}',
    )
    return section, _bump_revision(version)


@transaction.atomic
def update_section(section_id, expected_revision, cleaned_data):
    section = Section.objects.select_related('version').get(pk=section_id)
    version = _lock_version(section.version_id, expected_revision)
    section.title = cleaned_data['title']
    section.description = cleaned_data['description']
    section.save(update_fields=('title', 'description'))
    SectionIdentity.objects.filter(pk=section.identity_id).update(
        randomize_questions=cleaned_data['randomize_questions'],
    )
    return section, _bump_revision(version)


@transaction.atomic
def move_section(section_id, expected_revision, direction):
    if direction not in {'up', 'down'}:
        raise ValidationError('Invalid move direction.')
    section = Section.objects.select_related('version').get(pk=section_id)
    version = _lock_version(section.version_id, expected_revision)
    identity = section.identity
    queryset = _version_section_identities(version)
    adjacent = queryset.filter(
        **({'order__lt': identity.order} if direction == 'up' else {'order__gt': identity.order})
    ).order_by('-order' if direction == 'up' else 'order').first()
    if adjacent:
        section_order, adjacent_order = identity.order, adjacent.order
        SectionIdentity.objects.filter(pk=identity.pk).update(order=adjacent_order)
        SectionIdentity.objects.filter(pk=adjacent.pk).update(order=section_order)
    return _bump_revision(version)


@transaction.atomic
def delete_section(section_id, expected_revision):
    section = Section.objects.select_related('version').get(pk=section_id)
    version = _lock_version(section.version_id, expected_revision)
    if version.sections.count() == 1:
        raise ValidationError('A survey must contain at least one section.')
    removed_order = section.identity.order
    fallback_section = version.sections.exclude(pk=section.pk).first()
    # Questions snapshotted here but placed elsewhere survive the delete; re-parent
    # them so the snapshot still holds a row for their identity.
    section.questions.exclude(
        identity__section_identity_id=section.identity_id,
    ).update(section=fallback_section)
    logical_questions = Question.objects.filter(
        section__version=version,
        identity__section_identity_id=section.identity_id,
    )
    logical_questions.delete()
    section.delete()
    _version_section_identities(version).filter(order__gt=removed_order).update(
        order=models.F('order') - 1,
    )
    return _bump_revision(version)
