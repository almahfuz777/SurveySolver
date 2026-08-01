"""Survey lifecycle: listing, settings, publication and version history."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from responses.models import Submission
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
from .forms import (
    EligibilityCriteriaForm,
    ResponseLimitForm,
    SurveyBannerForm,
    SurveyBuilderHeaderForm,
    SurveyMetadataForm,
)
from .models import (
    Survey,
    SurveyEligibilityCriteria,
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

    # Completed-response counts for every accessible survey, in one query.
    response_counts = dict(
        Submission.objects.filter(
            survey__in=accessible,
            status=Submission.Status.COMPLETED,
        )
        .values_list('survey')
        .annotate(total=Count('id'))
    )
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


@login_required
def survey_edit(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, EDIT_ROLES)
    version = survey.draft_version
    wants_json = (
        'application/json' in request.headers.get('Accept', '')
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.POST.get('autosave') == '1'
    )
    form = SurveyMetadataForm(instance=survey)
    response_limit_form = ResponseLimitForm(
        initial={
            'enabled': survey.response_limit is not None,
            'response_limit': survey.response_limit,
        }
    )
    try:
        criteria = survey.eligibility_criteria
    except SurveyEligibilityCriteria.DoesNotExist:
        criteria = None
    eligibility_form = EligibilityCriteriaForm(
        initial={
            'restrict_age': bool(criteria and (criteria.min_age is not None or criteria.max_age is not None)),
            'min_age': criteria.min_age if criteria else None,
            'max_age': criteria.max_age if criteria else None,
            'restrict_education': bool(criteria and criteria.education_levels),
            'education_levels': criteria.education_levels if criteria else [],
            'restrict_countries': bool(criteria and criteria.countries),
            'countries': criteria.countries if criteria else [],
            'restrict_regions': bool(criteria and criteria.regions),
            'regions': criteria.regions if criteria else [],
            'restrict_genders': bool(criteria and criteria.genders),
            'genders': criteria.genders if criteria else [],
            'restrict_employment': bool(criteria and criteria.employment_statuses),
            'employment_statuses': criteria.employment_statuses if criteria else [],
            'restrict_industries': bool(criteria and criteria.industries),
            'industries': criteria.industries if criteria else [],
            'restrict_income': bool(criteria and criteria.income_brackets),
            'income_brackets': criteria.income_brackets if criteria else [],
            'restrict_religions': bool(criteria and criteria.religions),
            'religions': criteria.religions if criteria else [],
            'restrict_ethnicities': bool(criteria and criteria.ethnicities),
            'ethnicities': criteria.ethnicities if criteria else [],
            'restrict_languages': bool(criteria and criteria.languages),
            'languages': criteria.languages if criteria else [],
        }
    )
    if request.method == 'POST':
        action = request.POST.get('action', 'metadata')
        try:
            if action == 'metadata':
                form = SurveyMetadataForm(request.POST, request.FILES, instance=survey)
                if form.is_valid():
                    form.save()
                    if wants_json:
                        return JsonResponse({'revision': version.revision if version else None})
                    messages.success(request, 'Survey settings saved.')
                    return redirect('survey_edit', survey_id=survey.id)
            elif action == 'update_response_limit' and version:
                response_limit_form = ResponseLimitForm(request.POST)
                if response_limit_form.is_valid():
                    revision = services.update_response_limit(
                        version.id,
                        posted_revision(request),
                        response_limit_form.cleaned_data['response_limit'],
                    )
                    if wants_json:
                        return JsonResponse({'revision': revision})
                    messages.success(request, 'Response limit updated.')
                    return redirect('survey_edit', survey_id=survey.id)
            elif action == 'update_eligibility' and version:
                eligibility_form = EligibilityCriteriaForm(request.POST)
                if eligibility_form.is_valid():
                    _, revision = services.update_eligibility(
                        version.id,
                        posted_revision(request),
                        eligibility_form.cleaned_data,
                    )
                    if wants_json:
                        return JsonResponse({'revision': revision})
                    messages.success(request, 'Eligibility criteria updated.')
                    return redirect('survey_edit', survey_id=survey.id)
        except (services.StaleVersionError, ValidationError) as error:
            if wants_json:
                message = (
                    'This survey changed in another tab. Reload before continuing.'
                    if isinstance(error, services.StaleVersionError)
                    else '; '.join(error.messages)
                )
                return JsonResponse({'error': message}, status=409 if isinstance(error, services.StaleVersionError) else 422)
            if isinstance(error, services.StaleVersionError):
                messages.error(request, 'This survey changed in another tab. Reload before continuing.')
            else:
                messages.error(request, '; '.join(error.messages))
            return redirect('survey_edit', survey_id=survey.id)

        if wants_json:
            action_forms = {
                'metadata': form,
                'update_eligibility': eligibility_form,
                'update_response_limit': response_limit_form,
            }
            invalid_form = action_forms.get(action)
            errors = invalid_form.errors.get_json_data() if invalid_form else {}
            return JsonResponse({'error': 'Check the highlighted settings.', 'errors': errors}, status=422)

    return render(
        request,
        'surveys/survey_form.html',
        {
            'form': form,
            'survey': survey,
            'version': version,
            'response_limit_form': response_limit_form,
            'eligibility_form': eligibility_form,
            'readiness_errors': readiness_errors(version) if version else [],
            'publication_intent': publication_intent(survey, version) if version else None,
            'historical_versions': survey.versions.filter(
                status=SurveyVersion.Status.RETIRED,
            ).order_by('-number'),
            'page_title': 'Survey settings',
        },
    )


@require_POST
@login_required
def survey_archive(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, OWNER_ROLES)
    survey.archive()
    messages.success(request, 'Survey archived.')
    return redirect('survey_list')


@require_POST
@login_required
def survey_response_collection(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, OWNER_ROLES)
    accepting = request.POST.get('accepting') == 'on'
    try:
        services.set_response_collection(survey.id, accepting)
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        state = 'accepting responses' if accepting else 'paused'
        messages.success(request, f'“{survey.title}” is now {state}.')
    return redirect('survey_edit', survey_id=survey.id)


@require_POST
@login_required
def survey_rename(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, EDIT_ROLES)
    title = request.POST.get('title', '').strip()
    if not title:
        return JsonResponse({'errors': {'title': [{'message': 'Enter a survey title.'}]}}, status=422)
    if len(title) > 160:
        return JsonResponse({'errors': {'title': [{'message': 'Keep the title under 160 characters.'}]}}, status=422)
    survey.title = title
    survey.save(update_fields=('title', 'updated_at'))
    return JsonResponse({'title': survey.title})


@require_POST
@login_required
def survey_builder_header_update(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, EDIT_ROLES)
    form = SurveyBuilderHeaderForm(request.POST, instance=survey)
    if not form.is_valid():
        return JsonResponse(
            {
                'error': 'Check the highlighted survey details.',
                'errors': form.errors.get_json_data(),
            },
            status=422,
        )
    survey = form.save()
    return JsonResponse(
        {
            'title': survey.title,
            'summary': survey.summary,
        }
    )


@require_POST
@login_required
def survey_banner_update(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, EDIT_ROLES)
    form = SurveyBannerForm(request.POST, request.FILES, instance=survey)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
        return redirect('survey_builder', survey_id=survey.id)
    form.save()
    messages.success(request, 'Cover image updated.')
    return redirect('survey_builder', survey_id=survey.id)


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
