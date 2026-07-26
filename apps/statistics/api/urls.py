"""Reporting API routes."""

from django.urls import path

from apps.statistics.api.views import EmployeeStatisticsAPIView, GroupStatisticsAPIView

app_name = "statistics_api"

urlpatterns = [
    path("employees/<str:employee_id>/", EmployeeStatisticsAPIView.as_view(), name="employee-statistics"),
    path("groups/by-telegram/<int:telegram_id>/", GroupStatisticsAPIView.as_view(), name="group-statistics"),
]
