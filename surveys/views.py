from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import SurveyMetadataForm
from .models import Survey


@login_required
def survey_list(request):
    surveys = Survey.objects.owned_by(request.user).prefetch_related('topics')
    return render(request, 'surveys/survey_list.html', {'surveys': surveys})


@login_required
def survey_create(request):
    if request.method == 'POST':
        form = SurveyMetadataForm(request.POST, request.FILES)
        if form.is_valid():
            survey = form.save(commit=False)
            survey.owner = request.user
            survey.save()
            form.save_m2m()
            messages.success(request, 'Survey draft created. Add questions when you are ready.')
            return redirect('survey_detail', survey_id=survey.id)
    else:
        form = SurveyMetadataForm()

    return render(
        request,
        'surveys/survey_form.html',
        {'form': form, 'page_title': 'Create a research survey'},
    )


@login_required
def survey_detail(request, survey_id):
    survey = get_object_or_404(
        Survey.objects.prefetch_related('topics'),
        id=survey_id,
        owner=request.user,
    )
    return render(request, 'surveys/survey_detail.html', {'survey': survey})


@login_required
def survey_edit(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id, owner=request.user)
    if request.method == 'POST':
        form = SurveyMetadataForm(request.POST, request.FILES, instance=survey)
        if form.is_valid():
            form.save()
            messages.success(request, 'Survey details updated.')
            return redirect('survey_detail', survey_id=survey.id)
    else:
        form = SurveyMetadataForm(instance=survey)

    return render(
        request,
        'surveys/survey_form.html',
        {'form': form, 'survey': survey, 'page_title': 'Edit survey details'},
    )


@require_POST
@login_required
def survey_archive(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id, owner=request.user)
    survey.archive()
    messages.success(request, 'Survey archived.')
    return redirect('survey_list')
