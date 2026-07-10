from django.urls import path

from . import views


urlpatterns = [
    path('claims/<uuid:claim_id>/prepare/', views.prepare_claim, name='prepare_reward_claim'),
]
