"""Root URL configuration.

Application and API routes will be registered here after their apps exist.
"""

from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.imports.api.views import HealthCheckAPIView

urlpatterns = [
    path("panel/", admin.site.urls),
    path("health/", HealthCheckAPIView.as_view(), name="health-check"),
    path("api/v1/statistics/", include("apps.statistics.api.urls")),
    path("api/v1/imports/", include("apps.imports.api.urls")),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
