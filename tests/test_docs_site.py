"""
The published site and the README state things that go stale.

Both restate what is in the skill directory: how many references there are, how
many helpers, how many annotation types Potato has. Each of those is a number
someone will forget. The nav has the opposite problem: `mkdocs build --strict`
catches an entry pointing at a page that is gone, but a new page nobody added to
the nav builds clean and is simply unreachable.
"""

import os
import re

import pytest
import yaml

from skillpack import REFERENCES, ROOT, SCRIPTS

DOCS = os.path.join(ROOT, "docs")


def _nav_targets(nav):
    """Every `.md` path in the nav tree, at any depth."""
    if isinstance(nav, str):
        return [nav]
    if isinstance(nav, list):
        return [t for entry in nav for t in _nav_targets(entry)]
    if isinstance(nav, dict):
        return [t for value in nav.values() for t in _nav_targets(value)]
    return []


@pytest.fixture(scope="module")
def nav():
    # mkdocs uses `!!python/name:` tags for some options, which safe_load
    # rejects. Only the nav is needed, and it is plain data.
    with open(os.path.join(ROOT, "mkdocs.yml"), encoding="utf-8") as f:
        text = f.read()
    loader = yaml.SafeLoader
    loader.add_multi_constructor("tag:yaml.org,2002:python/name:", lambda *_: None)
    return _nav_targets(yaml.load(text, Loader=loader)["nav"])


class TestTheNavCoversTheSite:
    def test_every_nav_entry_exists(self, nav):
        missing = [t for t in nav if not os.path.isfile(os.path.join(DOCS, t))]
        assert not missing, f"nav points at pages that do not exist: {missing}"

    def test_every_page_is_reachable(self, nav):
        """A page absent from the nav builds clean and cannot be found."""
        on_disk = {f for f in os.listdir(DOCS) if f.endswith(".md")}
        assert not on_disk - set(nav), (
            f"these pages are not in the nav: {sorted(on_disk - set(nav))}")


class TestTheReadmeCountsAreRight:
    @staticmethod
    def _readme():
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            return f.read()

    def test_the_reference_count(self):
        match = re.search(r"(\d+) reference files", self._readme())
        assert match, "README no longer states how many references ship"
        assert int(match.group(1)) == len(REFERENCES)

    def test_the_helper_count(self):
        words = {4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight"}
        assert f"{words[len(SCRIPTS)]} helpers" in self._readme(), (
            f"README does not say there are {len(SCRIPTS)} helpers")

    def test_the_annotation_type_count(self):
        from potato.server_utils.schemas.registry import schema_registry

        match = re.search(r"all (\d+) types", self._readme())
        assert match, "README no longer states how many annotation types there are"
        assert int(match.group(1)) == len(schema_registry.get_supported_types())
