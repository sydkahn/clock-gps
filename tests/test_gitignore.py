"""Verify that real credentials are excluded from Git while the example
placeholder file may be committed.

This guards an explicit project requirement (SPECIFICATION.md section 5) and
is skipped automatically when the ``git`` executable is unavailable.
"""

import pathlib
import subprocess
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def git_check_ignore(path):
    """Return True when *path* would be ignored by Git.

    Raises unittest.SkipTest when git is not available.
    """
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", path],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise unittest.SkipTest("git executable not found")
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise unittest.SkipTest("git check-ignore failed with code %d" % result.returncode)


class GitignoreTests(unittest.TestCase):
    def test_real_credentials_are_ignored(self):
        self.assertTrue(git_check_ignore("device/credentials.py"))

    def test_root_credentials_are_ignored(self):
        self.assertTrue(git_check_ignore("credentials.py"))

    def test_example_credentials_are_not_ignored(self):
        self.assertFalse(git_check_ignore("device/credentials.example.py"))

    def test_example_credentials_file_exists(self):
        self.assertTrue((REPO_ROOT / "device" / "credentials.example.py").is_file())


if __name__ == "__main__":
    unittest.main()
