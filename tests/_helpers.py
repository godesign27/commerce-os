"""Shared paths and parsers for the structural test suite (stdlib only)."""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugins" / "commerce-os"
SKILLS = PLUGIN / "skills"
AGENTS = PLUGIN / "agents"
COMMANDS = PLUGIN / "commands"
SHARED = PLUGIN / "shared"

# The skills PRD §6.1 requires, and which specialist owns each.
SKILL_OWNERS = {
    "drive-intake": "intake-assets",
    "asset-validation": "intake-assets",
    "image-preparation": "intake-assets",
    "product-classification": "product-intelligence",
    "variant-grouping": "product-intelligence",
    "catalog-retrieval": "product-intelligence",
    "canonical-drafting": "catalog-draft",
    "destination-mapping": "catalog-draft",
    "review-packaging": "review-publishing",
    "approval-verification": "review-publishing",
    "publishing": "review-publishing",
    "reconciliation": "review-publishing",
}
# Administrator skills run directly from their command in the main session; no agent routes them.
ADMIN_SKILLS = {"storefront-setup"}
SPECIALISTS = sorted(set(SKILL_OWNERS.values()))
ROUTER = "commerce-lead"

SKILL_SECTIONS = [
    "Inputs", "Outputs", "Allowed tools", "Forbidden actions", "Workflow",
    "Validation", "Failure behavior", "Evidence requirements", "Current status",
]

SKIP_DIRS = {".git", "node_modules", ".commerce-os", "__pycache__"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path):
    return json.loads(read(path))


def frontmatter(path: Path) -> dict:
    text = read(path)
    assert text.startswith("---\n"), f"{path}: no frontmatter"
    block = text.split("---\n", 2)[1]
    out = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def body(path: Path) -> str:
    text = read(path)
    return text.split("---\n", 2)[2] if text.startswith("---\n") else text


def headings(path: Path, level: int = 2) -> list:
    return re.findall(rf"^{'#' * level} (.+?)\s*$", body(path), re.M)


def repo_files(suffixes=None):
    for p in REPO.rglob("*"):
        if p.is_file() and not (SKIP_DIRS & set(p.relative_to(REPO).parts)):
            if suffixes is None or p.suffix in suffixes:
                yield p


def markdown_files():
    return list(repo_files({".md", ".mdc"}))
