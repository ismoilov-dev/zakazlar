from datetime import date
from django.test import TestCase
from apps.employees.models import Employee, EmployeeMonthlyStat


class EmployeeMonthlyStatModelTest(TestCase):
    def test_create_employee_monthly_stat(self):
        emp = Employee.objects.create(employee_id="0191", full_name="Amir Karimov")
        stat = EmployeeMonthlyStat.objects.create(
            employee=emp,
            period=date(2026, 6, 1),
            summary_data={"earned_salary": "5000000.00"},
            source_spreadsheet_id="sheet123",
        )

        self.assertEqual(stat.employee.employee_id, "0191")
        self.assertEqual(stat.period, date(2026, 6, 1))
        self.assertEqual(stat.summary_data, {"earned_salary": "5000000.00"})
        self.assertFalse(stat.is_closed)
        self.assertEqual(str(stat), "0191 — 06.2026")
