"""Adding, editing, reordering and removing the sections of a draft."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from ... import services
from ...models import Section
from ...view_helpers import draft_version, editable_survey, posted_revision
from ..context import mutation_error
from ..forms import SectionForm


@require_POST
@login_required
def section_add(request, survey_id):
    survey = editable_survey(request, survey_id)
    version = draft_version(survey)
    try:
        services.add_section(version.id, posted_revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)


@require_POST
@login_required
def section_update(request, survey_id, section_id):
    survey = editable_survey(request, survey_id)
    section = get_object_or_404(Section, id=section_id, version__survey=survey)
    form = SectionForm(request.POST, instance=section)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors.get_json_data()}, status=422)
    try:
        _, revision = services.update_section(section.id, posted_revision(request), form.cleaned_data)
    except (services.StaleVersionError, ValidationError) as error:
        return mutation_error(request, survey, error)
    return JsonResponse({'revision': revision})


@require_POST
@login_required
def section_move(request, survey_id, section_id):
    survey = editable_survey(request, survey_id)
    section = get_object_or_404(Section, id=section_id, version__survey=survey)
    direction = request.POST.get('direction')
    if direction not in {'up', 'down'}:
        return JsonResponse({'error': 'Invalid direction.'}, status=422)
    try:
        services.move_section(section.id, posted_revision(request), direction)
    except (services.StaleVersionError, ValidationError) as error:
        return mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)


@require_POST
@login_required
def section_delete(request, survey_id, section_id):
    survey = editable_survey(request, survey_id)
    section = get_object_or_404(Section, id=section_id, version__survey=survey)
    try:
        services.delete_section(section.id, posted_revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)
