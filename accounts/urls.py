from django.urls import path

from . import views


urlpatterns = [
    path('profile/', views.profile_detail, name='profile_detail'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
]


# default allauth urls:
# accounts/ login/ [name='account_login']
# accounts/ logout/ [name='account_logout']
# accounts/ inactive/ [name='account_inactive']
# accounts/ signup/ [name='account_signup']
# accounts/ reauthenticate/ [name='account_reauthenticate']
# accounts/ email/ [name='account_email']
# accounts/ confirm-email/ [name='account_email_verification_sent']
# accounts/ password/change/ [name='account_change_password']
# accounts/ password/set/ [name='account_set_password']
# accounts/ password/reset/ [name='account_reset_password']
# accounts/ login/code/confirm/ [name='account_confirm_login_code']
# accounts/ ^confirm-email/(?P<key>[-:\w]+)/$ [name='account_confirm_email']
# accounts/ password/reset/key/done/ [name='account_reset_password_from_key_done']
# accounts/ ^password/reset/key/(?P<uidb36>[0-9A-Za-z]+)-(?P<key>.+)/$ [name='account_reset_password_from_key']
# accounts/ password/reset/done/ [name='account_reset_password_done']
# accounts/ 3rdparty/
# accounts/ social/login/cancelled/
# accounts/ social/login/error/
# accounts/ social/signup/
# accounts/ social/connections/
# accounts/ google/
# accounts/ google/login/token/ [name='google_login_by_token']