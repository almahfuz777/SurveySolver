from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('discover/', views.discover, name='discover'),
    path('my-responses/', views.my_responses, name='my_responses'),
]
