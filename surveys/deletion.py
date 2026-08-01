from django.db import transaction

from responses.deletion import purge_survey_responses
from rewards.services import detach_survey_transactions

from .models import Survey


@transaction.atomic
def permanently_delete_survey(survey_id, user):
    """Delete an owner's soft-deleted survey while retaining anonymous tombstones."""
    survey = Survey.objects.select_for_update().get(
        pk=survey_id,
        owner=user,
        deleted_at__isnull=False,
    )
    # Responses go first: deleting them invalidates guest claims and detaches the immutable point transactions from their response.
    # The ledger then loses its final survey link before the survey hierarchy is removed.
    response_count = purge_survey_responses(survey, user)
    detach_survey_transactions(survey)

    title = survey.title
    survey.delete()
    return title, response_count
