from django.test import TestCase

from apps.telegram_bot.routers import router


class RouterHandlersTest(TestCase):
    def test_registration_handlers_registered(self) -> None:
        """Verify that FSM message handlers process_employee_id and process_name are registered."""
        message_handlers = router.observers["message"].handlers
        handler_names = [getattr(h.callback, "__name__", "") for h in message_handlers]

        self.assertIn("process_employee_id", handler_names)
        self.assertIn("process_name", handler_names)
        self.assertIn("start", handler_names)
