from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('discover/', views.discover, name='discover'),
    path('overview/', views.overview, name='overview'),
]
