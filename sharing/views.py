from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from surveys.models import Survey

from .invitations import (
    accept_collaborator_invitation,
    create_collaborator_invitation,
    deliver_collaborator_invitation,
    invitation_token_is_valid,
    revoke_collaborator_invitation,
)
from .models import CollaborationLink, CollaboratorInvitation, SurveyCollaborator
from .models import RespondentInvitation
from .respondent_invitations import (
    create_respondent_invitation,
    deliver_respondent_invitation,
    invitation_token_is_valid as respondent_invitation_token_is_valid,
    revoke_respondent_invitation,
    store_invitation_grant,
)
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
            'collaborator_invitations': survey.collaborator_invitations.select_related(
                'created_by',
                'accepted_by',
            ),
            'respondent_invitations': survey.respondent_invitations.select_related(
                'created_by',
            ),
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
def send_collaborator_invitation(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id, owner=request.user)
    try:
        invitation, token = create_collaborator_invitation(
            survey.id,
            request.user,
            request.POST.get('email', ''),
            request.POST.get('role', ''),
        )
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        invitation_url = request.build_absolute_uri(
            reverse('accept_collaborator_invitation', args=[invitation.id, token])
        )
        if deliver_collaborator_invitation(invitation, invitation_url):
            messages.success(request, f'Invitation sent to {invitation.email}.')
        else:
            messages.error(request, 'The invitation was saved, but email delivery failed.')
    return redirect('sharing_settings', survey_id=survey.id)


@require_POST
@login_required
def revoke_invitation(request, survey_id, invitation_id):
    get_object_or_404(
        CollaboratorInvitation,
        id=invitation_id,
        survey_id=survey_id,
        survey__owner=request.user,
    )
    try:
        revoke_collaborator_invitation(invitation_id, request.user)
    except CollaboratorInvitation.DoesNotExist:
        messages.error(request, 'Invitation not found.')
    else:
        messages.success(request, 'Invitation revoked.')
    return redirect('sharing_settings', survey_id=survey_id)


@require_POST
@login_required
def send_respondent_invitation(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id, owner=request.user)
    try:
        invitation, token = create_respondent_invitation(
            survey.id,
            request.user,
            request.POST.get('email', ''),
        )
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        invitation_url = request.build_absolute_uri(
            reverse('open_respondent_invitation', args=[invitation.id, token])
        )
        if deliver_respondent_invitation(invitation, invitation_url):
            messages.success(request, f'Respondent invitation sent to {invitation.email}.')
        else:
            messages.error(request, 'The invitation was saved, but email delivery failed.')
    return redirect('sharing_settings', survey_id=survey.id)


@require_POST
@login_required
def revoke_respondent_invite(request, survey_id, invitation_id):
    get_object_or_404(
        RespondentInvitation,
        id=invitation_id,
        survey_id=survey_id,
        survey__owner=request.user,
    )
    try:
        revoke_respondent_invitation(invitation_id, request.user)
    except RespondentInvitation.DoesNotExist:
        messages.error(request, 'Respondent invitation not found.')
    else:
        messages.success(request, 'Respondent invitation revoked.')
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


@login_required
def accept_invitation(request, invitation_id, token):
    invitation = get_object_or_404(
        CollaboratorInvitation.objects.select_related('survey'),
        id=invitation_id,
    )
    if not invitation_token_is_valid(invitation, token):
        return render(request, 'sharing/invitation_unavailable.html', status=410)
    email_matches = request.user.email.casefold() == invitation.email
    if request.method == 'POST' and email_matches:
        try:
            accept_collaborator_invitation(invitation.id, token, request.user)
        except PermissionDenied:
            return render(request, 'sharing/invitation_unavailable.html', status=410)
        messages.success(request, f'You now have {invitation.get_role_display().lower()} access.')
        return redirect('survey_detail', survey_id=invitation.survey_id)
    return render(
        request,
        'sharing/accept_invitation.html',
        {'invitation': invitation, 'email_matches': email_matches},
        status=200 if email_matches else 403,
    )


def open_respondent_invitation(request, invitation_id, token):
    invitation = get_object_or_404(
        RespondentInvitation.objects.select_related('survey'),
        id=invitation_id,
    )
    if not respondent_invitation_token_is_valid(invitation, token):
        return render(request, 'sharing/respondent_invitation_unavailable.html', status=410)
    store_invitation_grant(request.session, invitation)
    return redirect('respond_survey', slug=invitation.survey.slug)
