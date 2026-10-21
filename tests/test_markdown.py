"""Markdown hygiene: tables are well formed and relative links resolve."""
import re
import unittest

from tests._helpers import REPO, markdown_files, read

LINK = re.compile(r"\]\(([^)\s]+)\)")


def strip_code(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def cells(row: str) -> int:
    return len(re.sub(r"`[^`]*`", "x", row).strip().strip("|").split("|"))


class Tables(unittest.TestCase):
    def test_table_rows_match_header(self):
        bad = []
        for f in markdown_files():
            lines = strip_code(read(f)).splitlines()
            for i, line in enumerate(lines):
                if i + 1 < len(lines) and line.startswith("|") and re.match(r"^\|[\s:|-]+\|$", lines[i + 1]):
                    width = cells(line)
                    j = i + 1
                    while j < len(lines) and lines[j].startswith("|"):
                        if cells(lines[j]) != width:
                            bad.append(f"{f.relative_to(REPO)}: '{lines[j][:60]}'")
                        j += 1
                    if j < len(lines) and lines[j].strip():
                        bad.append(f"{f.relative_to(REPO)}: prose butted onto a table: '{lines[j][:60]}'")
        self.assertEqual(bad, [], "malformed tables:\n" + "\n".join(bad))


class Links(unittest.TestCase):
    def test_relative_links_resolve(self):
        bad = []
        for f in markdown_files():
            for target in LINK.findall(strip_code(read(f))):
                if re.match(r"^(https?:|mailto:|#)", target):
                    continue
                path = target.split("#", 1)[0]
                if path and not (f.parent / path).exists():
                    bad.append(f"{f.relative_to(REPO)} → {target}")
        self.assertEqual(bad, [], "broken links:\n" + "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
