#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

from project_identity import (
    DEFAULT_KNOWLEDGE_ROOT,
    identify,
    normalize_remote,
    safe_directory,
)


class ProjectIdentityTests(unittest.TestCase):
    def test_default_knowledge_root_uses_current_users_documents_directory(self):
        self.assertEqual(
            Path(DEFAULT_KNOWLEDGE_ROOT),
            Path.home() / "Documents" / "Obsidian" / "GS" / "TaskSummary",
        )

    def test_ssh_and_https_are_equivalent(self):
        expected = "github.com/company/MyApp"
        remotes = [
            "git@github.com:company/MyApp.git",
            "ssh://git@github.com/company/MyApp.git",
            "https://github.com/company/MyApp.git",
        ]
        self.assertEqual([normalize_remote(item)[0] for item in remotes], [expected] * 3)

    def test_credentials_are_removed(self):
        project_id, display = normalize_remote(
            "https://person:secret@example.com/company/repo.git"
        )
        self.assertEqual(project_id, "example.com/company/repo")
        self.assertNotIn("secret", display)

    def test_non_default_port_is_part_of_identity(self):
        project_id, _ = normalize_remote("ssh://git@example.com:2222/company/repo.git")
        self.assertEqual(project_id, "example.com:2222/company/repo")

    def test_directory_name_is_safe_and_readable(self):
        self.assertEqual(
            safe_directory("github.com/company/MyApp"),
            "github.com--company--MyApp",
        )

    def test_manual_identity_supports_confirmed_chinese_name(self):
        with tempfile.TemporaryDirectory() as directory:
            result = identify(directory, directory, "内部工具")
        self.assertEqual(result["identity_kind"], "manual")
        self.assertEqual(result["project_id"], "manual/内部工具")
        self.assertEqual(result["directory_name"], "manual--内部工具")


if __name__ == "__main__":
    unittest.main()
