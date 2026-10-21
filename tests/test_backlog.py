"""BACKLOG.md structure: IDs unique and sequential, statuses valid, PRD §22 fully tracked."""
import re
import unittest

from tests._helpers import REPO, read

STATUSES = {"Open", "In progress", "Blocked", "Done"}
ROW = re.compile(r"^\| (B-\d{3}) \|.*\| ([^|]+?) \|$", re.M)


class Backlog(unittest.TestCase):
    def setUp(self):
        self.rows = ROW.findall(read(REPO / "BACKLOG.md"))

    def test_ids_unique(self):
        ids = [r[0] for r in self.rows]
        self.assertEqual(len(ids), len(set(ids)), "duplicate backlog IDs")

    def test_statuses_valid(self):
        for bid, status in self.rows:
            self.assertIn(status, STATUSES, f"{bid}: invalid status '{status}'")

    def test_every_prd_open_question_is_tracked(self):
        prd = read(REPO / "PRD.md")
        questions = re.findall(r"^(\d+)\. ", prd.split("## 22.", 1)[1].split("## 23.", 1)[0], re.M)
        tracked = {r[0] for r in self.rows}
        for n in questions:
            self.assertIn(f"B-{int(n):03d}", tracked, f"PRD §22 question {n} has no backlog item")


if __name__ == "__main__":
    unittest.main()
