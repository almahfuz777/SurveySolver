from django.urls import path

from . import views


urlpatterns = [
    path('profile/', views.profile_detail, name='profile_detail'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
]
