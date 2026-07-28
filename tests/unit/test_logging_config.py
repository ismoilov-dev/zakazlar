from django.conf import settings
from django.test import TestCase


class LoggingConfigTest(TestCase):
    def test_logging_configuration_present(self) -> None:
        self.assertTrue(hasattr(settings, "LOGGING"))
        logging_dict = getattr(settings, "LOGGING")
        self.assertEqual(logging_dict.get("version"), 1)
        self.assertIn("console", logging_dict.get("handlers", {}))
