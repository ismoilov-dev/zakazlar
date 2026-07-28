from django.test import TestCase
from apps.telegram_bot.routers import router


class RouterHandlersTest(TestCase):
    def test_single_regexp_handler_for_employee_id(self):
        """Verify that exactly one message handler is registered for bind_and_show_employee_stats."""
        message_handlers = router.observers["message"].handlers
        bind_handlers = [h for h in message_handlers if getattr(h.callback, "__name__", "") == "bind_and_show_employee_stats"]
        self.assertEqual(len(bind_handlers), 1)

