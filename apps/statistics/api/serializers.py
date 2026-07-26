"""Output serializers for statistics DTOs."""

from rest_framework import serializers


class EmployeeDashboardSerializer(serializers.Serializer):
    full_name = serializers.CharField()
    employee_id = serializers.CharField()
    group_code = serializers.CharField(allow_null=True)
    total_orders = serializers.IntegerField()
    successful_orders = serializers.IntegerField()
    cancelled_orders = serializers.IntegerField()
    total_sales = serializers.DecimalField(max_digits=16, decimal_places=2)
    total_profit = serializers.DecimalField(max_digits=16, decimal_places=2)
    monthly_salary = serializers.DecimalField(max_digits=16, decimal_places=2)
    sources = serializers.ListField()


class GroupDashboardSerializer(serializers.Serializer):
    group_code = serializers.CharField()
    group_name = serializers.CharField()
    successful_orders = serializers.IntegerField()
    total_profit = serializers.DecimalField(max_digits=16, decimal_places=2)
    leader_bonus = serializers.DecimalField(max_digits=16, decimal_places=2)
    leader_personal_profit = serializers.DecimalField(max_digits=16, decimal_places=2)
