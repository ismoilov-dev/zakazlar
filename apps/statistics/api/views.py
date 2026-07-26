"""REST views that delegate exclusively to reporting services."""

from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.services.exceptions import DomainError
from apps.statistics.api.serializers import EmployeeDashboardSerializer, GroupDashboardSerializer
from apps.statistics.services.statistics import StatisticsService


class EmployeeStatisticsAPIView(APIView):
    permission_classes = (IsAdminUser,)

    def get(self, request: object, employee_id: str) -> Response:
        try:
            dashboard = StatisticsService().employee_dashboard_for_employee(employee_id)
        except DomainError as exc:
            return Response({"detail": str(exc)}, status=404)
        return Response(EmployeeDashboardSerializer(dashboard.to_dict()).data)


class GroupStatisticsAPIView(APIView):
    permission_classes = (IsAdminUser,)

    def get(self, request: object, telegram_id: int) -> Response:
        try:
            dashboard = StatisticsService().group_dashboard_for_telegram(telegram_id)
        except DomainError as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response(GroupDashboardSerializer(dashboard.to_dict()).data)
