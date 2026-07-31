import tomllib
from pathlib import Path

from django.test import TestCase


class DependenciesTest(TestCase):
    def test_pyproject_dependencies_match_requirements(self) -> None:
        pyproject_path = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)

        deps = data.get("project", {}).get("dependencies", [])
        dep_names = [d.split(">")[0].split("<")[0].split("=")[0].strip() for d in deps]

        self.assertIn("gspread", dep_names)
        self.assertIn("google-auth", dep_names)
        self.assertIn("gunicorn", dep_names)
        self.assertIn("whitenoise", dep_names)
