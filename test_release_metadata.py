"""Keep the shipped release number and its notes honest.

v1.2.2 is the release whose main form scrolls, so the Start button can never
end up below the bottom edge of a short monitor. A release is easy to get
wrong in a way no other test notices: the source can be bumped without the
README following, or the version can drift backwards in a later edit. These
checks are deliberately loose — they do not pin 1.2.2 forever — but they do
refuse a version older than the release that introduced the scrolling main
form, and they insist that the version the code reports is the one the README
and the release notes describe.
"""

import re
import unittest
from pathlib import Path

import auto_typer

ROOT = Path(__file__).resolve().parent
SCROLLING_RELEASE = (1, 2, 2)      # the release that made the main form scroll


def release_numbers(version: str):
    """Split ``MAJOR.MINOR.PATCH`` into comparable integers."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    if match is None:
        raise AssertionError(
            f"APP_VERSION {version!r} is not a MAJOR.MINOR.PATCH release number")
    return tuple(int(part) for part in match.groups())


class ReleaseVersionTests(unittest.TestCase):
    def test_the_version_is_a_three_number_release(self):
        self.assertRegex(auto_typer.APP_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(len(release_numbers(auto_typer.APP_VERSION)), 3)

    def test_the_version_is_not_older_than_the_scrolling_release(self):
        self.assertGreaterEqual(release_numbers(auto_typer.APP_VERSION),
                                SCROLLING_RELEASE)

    def test_the_readme_announces_the_shipped_version(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"v{auto_typer.APP_VERSION}", readme,
                      "the README should name the version the code reports")

    def test_the_release_notes_describe_the_scrolling_main_form(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Release notes", readme)
        notes = readme.split("## Release notes", 1)[1]
        notes = notes.split("## Version numbering", 1)[0]
        self.assertIn("v1.2.2", notes)
        lowered = notes.lower()
        self.assertIn("scroll", lowered)
        self.assertIn("start autotyper", lowered)

    def test_the_source_and_the_docs_name_the_same_release(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        named = set(re.findall(r"v(\d+\.\d+\.\d+)", readme))
        self.assertIn(auto_typer.APP_VERSION, named)
        self.assertIn(".".join(str(part) for part in SCROLLING_RELEASE), named)


if __name__ == "__main__":
    unittest.main()
