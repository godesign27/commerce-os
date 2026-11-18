"""Pages ask about every piece's images and approvals on every load; on a slow (synced) disk, reading them all each
time made pages take 50 seconds. Each is now read again only when the file changes. All data is invented."""
import os
import unittest

from packages.adapters import artstore_map as am
from packages.drafting import publication
from tests.test_listing_copy import tmp


class ImageHash(unittest.TestCase):
    def test_a_changed_image_is_hashed_again(self):
        f = tmp() / "room.jpg"
        f.write_bytes(b"first")
        first = am.file_hash(f)
        self.assertEqual(am.file_hash(f), first)
        f.write_bytes(b"second, longer")
        self.assertNotEqual(am.file_hash(f), first, "a new size or time means a fresh read")
        st = f.stat()
        f.write_bytes(b"second, LONGER")                      # same size: the time still changes
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        self.assertEqual(am.file_hash(f), __import__("hashlib").sha256(b"second, LONGER").hexdigest())
        f.unlink()
        self.assertIsNone(am.file_hash(f))


class ApprovalRecords(unittest.TestCase):
    def test_a_new_approval_is_seen_at_once(self):
        a = publication.Approvals(tmp())
        a._append("fox", {"event": "out_of_date", "n": 1})
        self.assertEqual(len(a.records("fox")), 1)
        a._append("fox", {"event": "out_of_date", "n": 2})
        self.assertEqual([r["n"] for r in a.records("fox")], [1, 2])

    def test_callers_get_their_own_copy(self):
        a = publication.Approvals(tmp())
        a._append("fox", {"event": "out_of_date", "n": 1})
        a.records("fox")[0]["n"] = 99
        self.assertEqual(a.records("fox")[0]["n"], 1)


if __name__ == "__main__":
    unittest.main()
