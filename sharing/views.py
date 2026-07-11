from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from surveys.models import Survey

from .models import CollaborationLink, SurveyCollaborator
from .services import (
    accept_collaboration_link,
    create_collaboration_link,
    link_token_is_valid,
    remove_collaborator,
    revoke_collaboration_link,
    update_collaborator,
)


@login_required
def sharing_settings(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id, owner=request.user)
    if request.method == 'POST':
        try:
            link, token = create_collaboration_link(
                survey.id,
                request.user,
                request.POST.get('role', ''),
                int(request.POST.get('lifetime_days', '7')),
            )
        except (ValueError, ValidationError) as error:
            message = '; '.join(error.messages) if isinstance(error, ValidationError) else 'Select a valid expiration period.'
            messages.error(request, message)
        else:
            request.session['new_collaboration_link'] = {
                'id': str(link.id),
                'token': token,
            }
            return redirect('sharing_settings', survey_id=survey.id)
    new_link_data = request.session.pop('new_collaboration_link', None)
    new_link_url = None
    if new_link_data:
        new_link_url = request.build_absolute_uri(
            reverse(
                'accept_collaboration_link',
                args=[new_link_data['id'], new_link_data['token']],
            )
        )
    return render(
        request,
        'sharing/settings.html',
        {
            'survey': survey,
            'collaborators': survey.collaborators.select_related('user', 'added_by'),
            'collaboration_links': survey.collaboration_links.select_related('created_by'),
            'roles': SurveyCollaborator.Role.choices,
            'new_link_url': new_link_url,
        },
    )


@require_POST
@login_required
def revoke_link(request, survey_id, link_id):
    get_object_or_404(
        CollaborationLink,
        id=link_id,
        survey_id=survey_id,
        survey__owner=request.user,
    )
    try:
        revoke_collaboration_link(link_id, request.user)
    except CollaborationLink.DoesNotExist:
        messages.error(request, 'Collaboration link not found.')
    else:
        messages.success(request, 'Collaboration link revoked.')
    return redirect('sharing_settings', survey_id=survey_id)


@require_POST
@login_required
def manage_collaborator(request, survey_id, collaborator_id):
    get_object_or_404(
        SurveyCollaborator,
        id=collaborator_id,
        survey_id=survey_id,
        survey__owner=request.user,
    )
    action = request.POST.get('action')
    try:
        if action == 'remove':
            remove_collaborator(collaborator_id, request.user)
            messages.success(request, 'Collaborator removed.')
        elif action == 'update':
            update_collaborator(collaborator_id, request.user, request.POST.get('role', ''))
            messages.success(request, 'Collaborator role updated.')
        else:
            messages.error(request, 'Select a valid collaborator action.')
    except (SurveyCollaborator.DoesNotExist, ValidationError) as error:
        message = '; '.join(error.messages) if isinstance(error, ValidationError) else 'Collaborator not found.'
        messages.error(request, message)
    return redirect('sharing_settings', survey_id=survey_id)


@login_required
def accept_link(request, link_id, token):
    link = get_object_or_404(CollaborationLink.objects.select_related('survey'), id=link_id)
    if not link_token_is_valid(link, token):
        return render(request, 'sharing/link_unavailable.html', {'link': link}, status=410)
    if request.method == 'POST':
        try:
            accept_collaboration_link(link.id, token, request.user)
        except PermissionDenied:
            return render(request, 'sharing/link_unavailable.html', {'link': link}, status=410)
        messages.success(request, f'You now have {link.get_role_display().lower()} access.')
        return redirect('survey_detail', survey_id=link.survey_id)
    return render(request, 'sharing/accept_link.html', {'link': link})
