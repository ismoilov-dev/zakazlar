"""Root URL configuration.

Application and API routes will be registered here after their apps exist.
"""

from __future__ import annotations

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("admin/panel/", admin.site.urls),
    path("panel/", admin.site.urls),
    path("api/v1/statistics/", include("apps.statistics.api.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
