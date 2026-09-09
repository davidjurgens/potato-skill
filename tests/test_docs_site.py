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

from skillpack import REFERENCES, ROOT, SCRIPTS, pack_path

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

    WORDS = {4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight"}

    def test_the_helper_count(self):
        assert f"{self.WORDS[len(SCRIPTS)]} helpers" in self._readme(), (
            f"README does not say there are {len(SCRIPTS)} helpers")

    def test_the_helper_count_in_the_skill(self):
        """The README was pinned and SKILL.md was not, so adding check_ui.py left
        the sentence an agent actually reads saying six."""
        with open(pack_path("SKILL.md"), encoding="utf-8") as f:
            skill = f.read()
        expected = f"{self.WORDS[len(SCRIPTS)]} of the procedures below are scripts"
        assert expected in skill, (
            f"SKILL.md does not say there are {len(SCRIPTS)} helper scripts")

    def test_the_annotation_type_count(self):
        from potato.server_utils.schemas.registry import schema_registry

        match = re.search(r"all (\d+) types", self._readme())
        assert match, "README no longer states how many annotation types there are"
        assert int(match.group(1)) == len(schema_registry.get_supported_types())


class TestThePluginMetadataAgreesWithItself:
    """`plugin.json` and the marketplace entry are two copies of one record.

    Nine fields are duplicated verbatim between them, and only one of the two
    is the file a person edits when they bump a version or reword a
    description. Nothing here or in Claude Code reconciles them: the plugin
    loads from `plugin.json` and the marketplace serves its own copy, so a
    stale entry advertises a version that is not what installs.

    Written after Potato was found shipping a packaged JSON schema that had
    been fixed in the docs copy three commits earlier. Same shape, invisible
    for the same reason.
    """

    @staticmethod
    def _pair():
        import json
        root = os.path.join(ROOT, ".claude-plugin")
        with open(os.path.join(root, "plugin.json"), encoding="utf-8") as f:
            plugin = json.load(f)
        with open(os.path.join(root, "marketplace.json"), encoding="utf-8") as f:
            market = json.load(f)
        entries = [e for e in market.get("plugins", [])
                   if e.get("name") == plugin.get("name")]
        assert entries, (
            f"marketplace.json lists no plugin named {plugin.get('name')!r}. "
            f"It lists: {[e.get('name') for e in market.get('plugins', [])]}")
        return plugin, entries[0]

    def test_every_shared_field_matches(self):
        plugin, entry = self._pair()
        shared = sorted(k for k in plugin if k in entry)
        assert shared, "the two records share no fields; one of them is empty"
        mismatched = {k: (plugin[k], entry[k])
                      for k in shared if plugin[k] != entry[k]}
        assert not mismatched, (
            "plugin.json and the marketplace entry disagree: "
            + "; ".join(f"{k}: {a!r} != {b!r}"
                        for k, (a, b) in mismatched.items())
            + ". Both are published; whichever you edited, edit the other.")

    def test_the_skill_it_names_is_the_one_that_ships(self):
        plugin, _ = self._pair()
        name = plugin.get("name")
        skill_dir = os.path.join(ROOT, "skills", name)
        assert os.path.isdir(skill_dir), (
            f"plugin.json names {name!r} but skills/{name}/ does not exist, so "
            f"installing the plugin installs no skill.")
        assert os.path.isfile(os.path.join(skill_dir, "SKILL.md"))
