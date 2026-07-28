from django.test import TestCase

from apps.imports.sources.excel import ExcelSource


class ExcelHeadersTest(TestCase):
    def test_excel_headers_stripped_matching(self) -> None:
        # Headings without trailing spaces
        headings = ("ID", "XODIMLAR ISMLARI", "Bo'lim", "OYLIK MOASH")
        required = {"ID", "XODIMLAR ISMLARI ", "Bo'lim ", "OYLIK MOASH "}

        cols = ExcelSource._columns(headings, required)
        self.assertEqual(cols["ID"], 0)
        self.assertEqual(cols["XODIMLAR ISMLARI "], 1)
        self.assertEqual(cols["Bo'lim "], 2)
        self.assertEqual(cols["OYLIK MOASH "], 3)
