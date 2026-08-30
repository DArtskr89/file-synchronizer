"""Tests for the synchronization algorithm."""

import os
import sys
import tempfile
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from main import synchronize  # noqa: E402


class FakeCloud:
    """Small in-memory replacement for the cloud connector."""

    def __init__(self, files):
        self.files = files.copy()
        self.loaded = []
        self.reloaded = []
        self.deleted = []

    def get_info(self):
        return self.files.copy()

    def load(self, path):
        self.loaded.append(os.path.basename(path))

    def reload(self, path):
        self.reloaded.append(os.path.basename(path))

    def delete(self, filename):
        self.deleted.append(filename)


class SynchronizeTests(unittest.TestCase):
    """Verify upload, replacement, and deletion decisions."""

    def test_first_sync_makes_cloud_match_local_files(self):
        with tempfile.TemporaryDirectory() as folder:
            first = os.path.join(folder, "first.txt")
            second = os.path.join(folder, "second.txt")
            open(first, "w", encoding="utf-8").close()
            open(second, "w", encoding="utf-8").close()
            local_time = os.path.getmtime(first)
            cloud = FakeCloud(
                {"first.txt": local_time - 10, "removed.txt": local_time}
            )

            synchronize(cloud, folder)

            self.assertEqual(cloud.loaded, ["second.txt"])
            self.assertEqual(cloud.reloaded, ["first.txt"])
            self.assertEqual(cloud.deleted, ["removed.txt"])

    def test_current_file_is_not_uploaded_again(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "current.txt")
            open(path, "w", encoding="utf-8").close()
            cloud = FakeCloud({"current.txt": os.path.getmtime(path) + 10})

            synchronize(cloud, folder)

            self.assertEqual(cloud.loaded, [])
            self.assertEqual(cloud.reloaded, [])
            self.assertEqual(cloud.deleted, [])


if __name__ == "__main__":
    unittest.main()
