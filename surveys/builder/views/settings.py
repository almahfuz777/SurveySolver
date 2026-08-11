"""The Settings tab of the authoring workspace, plus the header controls above the canvas.

Every write here delegates to a survey domain service; this module only validates input and shapes
the autosave response the builder JavaScript expects.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from sharing.permissions import EDIT_ROLES, OWNER_ROLES, get_accessible_survey

from ... import services
from ...lifecycle import set_response_collection
from ...models import SurveyEligibilityCriteria, SurveyVersion
from ...publication import publication_intent, readiness_errors
from ...view_helpers import posted_revision
from ..forms import (
    EligibilityCriteriaForm,
    ResponseLimitForm,
    SurveyBannerForm,
    SurveyBuilderHeaderForm,
    SurveyMetadataForm,
)


STALE_SURVEY_MESSAGE = 'This survey changed in another tab. Reload before continuing.'


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
            'targeted': bool(criteria and criteria.is_targeted),
            'min_age': criteria.min_age if criteria else None,
            'max_age': criteria.max_age if criteria else None,
            'education_levels': criteria.education_levels if criteria else [],
            'countries': criteria.countries if criteria else [],
            'regions': criteria.regions if criteria else [],
            'genders': criteria.genders if criteria else [],
            'employment_statuses': criteria.employment_statuses if criteria else [],
            'industries': criteria.industries if criteria else [],
            'income_brackets': criteria.income_brackets if criteria else [],
            'religions': criteria.religions if criteria else [],
            'ethnicities': criteria.ethnicities if criteria else [],
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
                    STALE_SURVEY_MESSAGE
                    if isinstance(error, services.StaleVersionError)
                    else '; '.join(error.messages)
                )
                return JsonResponse({'error': message}, status=409 if isinstance(error, services.StaleVersionError) else 422)
            if isinstance(error, services.StaleVersionError):
                messages.error(request, STALE_SURVEY_MESSAGE)
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
        'surveys/builder/settings.html',
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
def survey_response_collection(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, OWNER_ROLES)
    accepting = request.POST.get('accepting') == 'on'
    try:
        set_response_collection(survey.id, accepting)
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
