"""
URL configuration for surveysolver project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Public pages
    path('', include('core.urls')),
    path('discover/', include('discover.urls')),

    # Managing an owned survey or as a collaborator
    path('surveys/', include('surveys.urls')),
    path('surveys/', include('responses.creator_urls')),
    path('surveys/', include('sharing.urls')),

    # Answering a survey
    path('s/', include('responses.public_urls')),
    path('responses/', include('responses.urls')),
    path('my-responses/', include('responses.history_urls')),

    # Accepting a tokenised invitation
    path('collaborate/', include('sharing.collaborate_urls')),
    path('invitation/', include('sharing.invitation_urls')),

    path('rewards/', include('rewards.urls')),
    path('analytics/', include('analytics.urls')),

    # Ours first: allauth owns every other accounts/ path (login, signup, password reset).
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('allauth.urls')),

    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
