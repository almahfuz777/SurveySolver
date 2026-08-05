"""Survey lifecycle: listing, publication, deletion and version history.

Editing a survey lives in the builder package; everything here is about the survey as a whole.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from responses.services import completed_response_counts
from sharing.permissions import EDIT_ROLES, OWNER_ROLES, VIEW_ROLES, accessible_surveys, get_accessible_survey

from . import services
from .deletion import permanently_delete_survey
from .diff import questionnaire_diff
from .publication import (
    PublicationError,
    delete_retired_version,
    discard_draft_changes,
    publication_intent,
    publish_survey,
    readiness_errors,
    restore_version_to_draft,
)
from .models import (
    Survey,
    SurveyVersion,
)
from .view_helpers import draft_version, editable_survey, posted_revision


@login_required
def survey_list(request):
    services.discard_empty_drafts(request.user)
    accessible = list(
        accessible_surveys(request.user, VIEW_ROLES).prefetch_related(
            'topics',
            'versions',
        )
    )

    response_counts = completed_response_counts(accessible)
    for survey in accessible:
        survey.response_count = response_counts.get(survey.id, 0)
        versions = list(survey.versions.all())
        display_version = next(
            (
                version
                for version in versions
                if version.status == SurveyVersion.Status.PUBLISHED
            ),
            None,
        ) or next(
            (
                version
                for version in versions
                if version.status == SurveyVersion.Status.DRAFT
            ),
            None,
        )
        survey.display_version_number = (
            display_version.number if display_version is not None else None
        )

    owned_all = [s for s in accessible if s.owner_id == request.user.id]
    shared_surveys = [s for s in accessible if s.owner_id != request.user.id]

    status_counts = {
        'all': len(owned_all),
        'draft': sum(1 for s in owned_all if s.status == Survey.Status.DRAFT),
        'published': sum(1 for s in owned_all if s.status == Survey.Status.PUBLISHED),
        'closed': sum(1 for s in owned_all if s.status == Survey.Status.CLOSED),
    }

    status_filter = request.GET.get('status')
    if status_filter not in {'draft', 'published', 'closed'}:
        status_filter = 'all'
    owned_surveys = (
        owned_all if status_filter == 'all'
        else [s for s in owned_all if s.status == status_filter]
    )

    deleted_surveys = Survey.objects.filter(owner=request.user, deleted_at__isnull=False).order_by('-deleted_at')
    return render(
        request,
        'surveys/survey_list.html',
        {
            'owned_surveys': owned_surveys,
            'shared_surveys': shared_surveys,
            'status_counts': status_counts,
            'status_filter': status_filter,
            'has_owned': bool(owned_all),
            'deleted_surveys': deleted_surveys,
        },
    )


@require_POST
@login_required
def survey_create(request):
    survey = Survey.objects.create(owner=request.user, title=services.DEFAULT_SURVEY_TITLE, summary='')
    return redirect('survey_builder', survey_id=survey.id)


@login_required
def survey_detail(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    if survey.access_role in EDIT_ROLES and survey.status != Survey.Status.ARCHIVED:
        return redirect('survey_builder', survey_id=survey.id)
    return redirect('survey_preview', survey_id=survey.id)


@require_POST
@login_required
def survey_archive(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, OWNER_ROLES)
    survey.archive()
    messages.success(request, 'Survey archived.')
    return redirect('survey_list')


@require_POST
@login_required
def survey_delete(request, survey_id):
    survey = get_object_or_404(Survey.objects.active(), id=survey_id, owner=request.user)
    survey.soft_delete()
    messages.success(request, f'“{survey.title}” moved to recently deleted.')
    return redirect('survey_list')


@require_POST
@login_required
def survey_restore(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id, owner=request.user, deleted_at__isnull=False)
    survey.restore()
    messages.success(request, f'“{survey.title}” restored.')
    return redirect('survey_list')


@login_required
def survey_purge(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id, owner=request.user, deleted_at__isnull=False)
    confirmation = f'DELETE {survey.title}'
    if request.method == 'POST':
        if request.POST.get('confirmation') != confirmation:
            messages.error(request, f'Type {confirmation} exactly to confirm deletion.')
        else:
            title, response_count = permanently_delete_survey(
                survey.id,
                request.user,
            )
            messages.success(
                request,
                f'“{title}” and {response_count} response'
                f'{"s" if response_count != 1 else ""} were deleted forever.',
            )
            return redirect('survey_list')
    return render(
        request,
        'surveys/survey_purge.html',
        {
            'survey': survey,
            'confirmation': confirmation,
        },
    )


@require_POST
@login_required
def survey_publish(request, survey_id):
    survey = editable_survey(request, survey_id)
    try:
        published_version, _ = publish_survey(survey.id, request.user, posted_revision(request))
    except services.StaleVersionError:
        messages.error(request, 'This draft changed in another tab. Reload before publishing.')
    except PublicationError as error:
        for message in error.errors:
            messages.error(request, message)
    else:
        messages.success(request, 'Survey published. Respondents now see the latest questions.')
        return redirect('survey_list')
    return redirect('survey_publish_review', survey_id=survey.id)


@login_required
def survey_publish_review(request, survey_id):
    """Show what publishing would change before the creator commits to it."""
    survey = editable_survey(request, survey_id)
    version = draft_version(survey)
    active = survey.versions.filter(status=SurveyVersion.Status.PUBLISHED).first()
    return render(
        request,
        'surveys/publish_review.html',
        {
            'survey': survey,
            'version': version,
            'active_version': active,
            'diff': questionnaire_diff(version, active),
            'publication_intent': publication_intent(survey, version),
            'readiness_errors': readiness_errors(version),
            'title_changed': bool(
                active is not None
                and (active.title_snapshot or survey.title) != survey.title
            ),
            'page_title': 'Review changes',
        },
    )


@require_POST
@login_required
def survey_discard_draft(request, survey_id):
    survey = editable_survey(request, survey_id)
    try:
        discard_draft_changes(survey.id, request.user, posted_revision(request))
    except services.StaleVersionError:
        messages.error(request, 'This draft changed in another tab. Reload before discarding.')
    except PublicationError as error:
        for message in error.errors:
            messages.error(request, message)
    else:
        messages.success(
            request,
            'Draft changes discarded. The builder now matches the published version.',
        )
    return redirect('survey_builder', survey_id=survey.id)


@require_POST
@login_required
def survey_version_restore(request, survey_id, version_id):
    survey = get_accessible_survey(request.user, survey_id, OWNER_ROLES)
    try:
        source, restored = restore_version_to_draft(
            survey.id,
            version_id,
            request.user,
            posted_revision(request),
        )
    except services.StaleVersionError:
        messages.error(request, 'This draft changed in another tab. Reload before restoring.')
    except SurveyVersion.DoesNotExist:
        messages.error(request, 'Only a retired version can be restored.')
    else:
        messages.success(
            request,
            f'Version {source.number} was copied into the draft. '
            'Live ordering and survey settings were not changed.',
        )
    return redirect('survey_edit', survey_id=survey.id)


@login_required
def survey_version_delete(request, survey_id, version_id):
    survey = get_accessible_survey(request.user, survey_id, OWNER_ROLES)
    version = get_object_or_404(
        SurveyVersion,
        pk=version_id,
        survey=survey,
        status=SurveyVersion.Status.RETIRED,
    )
    confirmation = f'DELETE VERSION {version.number}'
    if request.method == 'POST':
        if request.POST.get('confirmation') != confirmation:
            messages.error(request, f'Type {confirmation} exactly to confirm deletion.')
        else:
            deleted_count = delete_retired_version(
                survey.id,
                version.id,
                request.user,
            )
            messages.success(
                request,
                f'Version {version.number} and {deleted_count} response'
                f'{"s" if deleted_count != 1 else ""} were permanently deleted.',
            )
            return redirect('survey_edit', survey_id=survey.id)
    return render(
        request,
        'surveys/version_delete.html',
        {
            'survey': survey,
            'version': version,
            'confirmation': confirmation,
        },
    )
