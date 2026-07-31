from django.test import SimpleTestCase

from apps.accounts.services.name_match import names_match


class NameMatchTest(SimpleTestCase):
    def test_name_matching_table(self) -> None:
        pairs = [
            # Exact matches with different order / case
            ("Elbek Xaydarov", "XAYDAROV ELBEK", True),
            ("XAYDAROV ELBEK", "Elbek Xaydarov", True),

            # Uzbek x / h equivalences
            ("Shuhrat Khaydarov", "Shuxrat Haydarov", True),
            ("Shuxrat Haydarov", "Shuhrat Xaydarov", True),

            # Cyrillic vs Latin
            ("ЭЛБЕК ХАЙДАРОВ", "Elbek Xaydarov", True),
            ("Elbek Xaydarov", "ЭЛБЕК ХАЙДАРОВ", True),

            # Apostrophe and o'/g' variants
            ("O'g'iloy Xasanova", "Ogiloy Hasanova", True),
            ("Oʻgʻiloy Hasanova", "O'g'iloy Xasanova", True),

            # Ye / e at word start
            ("Yelena Kim", "Elena Kim", True),
            ("Yernazar Tulepov", "Ernazar Tulepov", True),

            # Token count rule (typed 2 tokens against 3-token sheet name with patronymic)
            ("Elbek Xaydarov", "Xaydarov Elbek O'g'li", True),
            ("Elbek Xaydarov", "Xaydarov Elbek Xusniddinovich", True),

            # Single token typed -> MUST return False
            ("Elbek", "Xaydarov Elbek", False),
            ("Xaydarov", "Xaydarov Elbek", False),

            # Mismatched name tokens
            ("Elbek Smith", "Xaydarov Elbek", False),
            ("Ali Valiyev", "Hasan Husanov", False),
            ("Javohir Karimov", "Javohir Alimov", False),
        ]

        for typed, sheet_name, expected in pairs:
            with self.subTest(typed=typed, sheet_name=sheet_name):
                result = names_match(typed, sheet_name)
                self.assertEqual(
                    result,
                    expected,
                    f"Expected names_match('{typed}', '{sheet_name}') to be {expected}, got {result}",
                )
