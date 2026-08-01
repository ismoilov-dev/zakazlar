"""Imports API URL routes."""

from django.urls import path

from apps.imports.api.views import HealthCheckAPIView, SheetChangedWebhookAPIView

app_name = "imports_api"

urlpatterns = [
    path("sheet-changed/", SheetChangedWebhookAPIView.as_view(), name="sheet-changed"),
    path("health/", HealthCheckAPIView.as_view(), name="health-check"),
]
