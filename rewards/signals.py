from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .claims import consume_pending_claim


@receiver(user_logged_in)
def consume_reward_claim_after_login(sender, request, user, **kwargs):
    if request is None or not request.session.session_key:
        return
    consume_pending_claim(user, request.session, request.session.session_key)
