"""Draft locking and the optimistic-revision counter every mutation goes through."""
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef

from ..models import (
    Question,
    QuestionIdentity,
    SectionIdentity,
    Survey,
    SurveyVersion,
)


# Title stamped on a freshly created survey before the owner has edited anything.
DEFAULT_SURVEY_TITLE = 'Untitled survey'


class StaleVersionError(Exception):
    pass


def discard_empty_drafts(user):
    """Hard-delete the user's pristine, never-touched draft surveys.

    A survey is created the moment the owner clicks "Create survey", so an
    accidental click (or a builder opened and abandoned without adding a
    question) leaves an untouched draft behind. Sweep those away: still a
    DRAFT, default title, no summary/description, no questions, no responses.
    """
    has_questions = Question.objects.filter(section__version__survey=OuterRef('pk'))
    candidates = Survey.objects.filter(
        owner=user,
        deleted_at__isnull=True,
        status=Survey.Status.DRAFT,
        title=DEFAULT_SURVEY_TITLE,
        summary='',
        description='',
        banner='',
        thumbnail='',
        submissions__isnull=True,
    ).annotate(has_questions=Exists(has_questions)).filter(has_questions=False)
    # SurveyQuerySet.delete() routes each survey through Survey.delete(), so the
    # versions and identity hierarchy come down safely and atomically.
    candidates.delete()


def _lock_version(version_id, expected_revision):
    version = SurveyVersion.objects.select_for_update().get(pk=version_id)
    if version.status != SurveyVersion.Status.DRAFT:
        raise ValidationError('Published survey versions are immutable.')
    if version.revision != expected_revision:
        raise StaleVersionError
    return version


def _bump_revision(version):
    version.revision += 1
    version.save(update_fields=('revision', 'updated_at'))
    return version.revision


def _version_section_identities(version):
    return SectionIdentity.objects.filter(
        snapshots__version=version,
    ).distinct()


def _version_question_identities(version, section_identity=None):
    queryset = QuestionIdentity.objects.filter(
        snapshots__section__version=version,
    ).distinct()
    if section_identity is not None:
        queryset = queryset.filter(section_identity=section_identity)
    return queryset
