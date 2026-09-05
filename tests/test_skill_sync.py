"""
Guards for the skill.

The pack is what an agent reads instead of guessing, so a wrong field list here
is worse than none: it is confidently wrong. Two halves, two failure modes.

The generated references (`annotation-types.md`, `config-keys.md`) drift, so they
are byte-compared against a fresh build. The hand-written files cannot be
compared to anything, so instead every annotation type, display type, config key,
operator, strategy name and command they mention is checked to exist.

That second half is the one that earns its keep. The design and UI references
name roughly 140 identifiers in prose, and a plausible-sounding wrong one --
`textbox` for the free-text type, say -- is worse than no documentation, because
an agent will use it and then have to discover from a validator that the
authoritative-looking reference was making things up.
"""

import ast
import os
import re
import subprocess
import sys

import pytest

from skillpack import (
    REFERENCES,
    SCRIPTS,
    SKILL_NAME,
    has_potato_repo,
    pack_path,
    potato_repo_path,
)
from potato.server_utils.config_module import KNOWN_CONFIG_KEYS
from potato.server_utils.displays import display_registry
from potato.server_utils.schemas.registry import schema_registry

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATOR = os.path.join(REPO_ROOT, "scripts", "generate_references.py")
DOCS_MIRROR = os.path.join(REPO_ROOT, "docs", "agents-md.md")

HAND_WRITTEN = [
    "AGENTS.md",
    "SKILL.md",
    os.path.join("references", "designing-a-task.md"),
    os.path.join("references", "asking-the-experimenter.md"),
    os.path.join("references", "interviewing.md"),
    os.path.join("references", "building-the-ui.md"),
    os.path.join("references", "evaluating-the-ui.md"),
]
GENERATED = [
    os.path.join("references", "annotation-types.md"),
    os.path.join("references", "config-keys.md"),
]

#: Backticked identifiers that are legitimately not registry entries: structural
#: keys, literals, phase names, filenames, and the three type names the pack
#: deliberately calls out as *not* being types.
PROSE_IDENTIFIERS = {
    # The distribution and the command. Not a config key or a type.
    "potato",
    # sub-keys of one `link_types` entry on a `span_link` scheme. Two levels
    # inside a scheme entry, which is past where any registry describes a
    # config; they are read in span_link.py:78-79
    "allowed_source_labels", "allowed_target_labels",
    # `ai_support.endpoint_type`, named bare because it is the one key the
    # subsystem refuses to start without and the error message quotes it that
    # way. KNOWN_CONFIG_KEYS records `ai_support` as an opaque block, so no
    # sub-key of it resolves; ai_endpoint.py:664 is the check that raises
    "endpoint_type",
    # the module that rejects a non-string label. Named in the warning about
    # YAML booleans because its message is what the boot log prints, and a
    # reader grepping for it needs the real module name
    "identifier_utils",
    # potato/static/annotation.js -- the client file that owns saving,
    # restoring and requiredness. Named where a warning is only actionable if
    # the reader can open the file
    "annotation.js",
    # `layout.breakpoints` sub-keys, named bare in the table that says what
    # each threshold does to a grouped form. KNOWN_CONFIG_KEYS records `layout`
    # two levels deep, so `breakpoints.mobile` resolves and `mobile` alone does
    # not; config_module.py's layout entry is where both are declared
    "mobile", "tablet",
    # The data key the `spreadsheet` display reads its column names from, named
    # in prose in the note about {columns, rows}. Like the display_options
    # below it lives in no registry -- the display types' data contracts are
    # documented only in their own module docstrings
    "headers",

    # `display_options` accepted by the `document` display, named in prose in the
    # note about what a string-valued document field does. The vocabulary is
    # built from the config-key registry and the schema/display type names, and
    # display_options live in neither -- they are enumerated only in the
    # validator's own error message (config_module.py, the display_options
    # branch), which is where these three came from
    "preserve_structure", "show_outline", "style_theme",
    # `cell_width` is a pairwise_display option and `auto` is its default;
    # pairwise_display.py:28 and 54. `auto` is a bare word rather than a key,
    # so nothing in the registries claims it
    "cell_width", "auto",
    # the id `bws_config` gives a generated tuple, measured off a running
    # server. bws_tuple_generator.py's own docstring says `bws_tuple_001`, one
    # digit short of what it emits, so the code is the only source for this
    "bws_tuple_0001",
    # the user_state field holding every answer. Named because the warnings
    # about widgets that store what nobody chose are only checkable by reading
    # it; potato/adjudication.py:312 among many
    "instance_id_to_label_to_value",
    # display options the registry table does not list, though the renderer
    # classes declare them: `caption_key`/`url_key` on gallery_display,
    # `ocr`/`link_schema` on pdf_display. Named in the warning that
    # `list_displays()` under-reports, which is only checkable against the
    # classes -- `display_registry.get(name).renderer.optional_fields`
    "caption_key", "url_key", "ocr", "link_schema",
    # the default `speaker_key` reads, multi_agent_discussion_display.py:85. A
    # field name in the annotator's data, so no registry claims it
    "speaker",
    # a key on one entry of `event_types` on an event_annotation scheme, two
    # levels inside a scheme entry; event_annotation.py:70
    "trigger_labels",
    # the HTML attribute card_sort puts on its cards, named because the
    # accessibility warning is about that attribute being the only affordance
    "draggable",
    # potato/server_utils/displays/registry.py, named so a reader can open the
    # file where the display table is hardcoded
    "registry.py",
    # structural keys inside a scheme or an instance_display field
    "annotation_type", "name", "description", "type", "key", "label",
    "fields", "required", "value", "labels", "direction", "gap",
    # item_properties
    "id_key", "text_key",
    # type-specific fields named in the response-format table
    "target_schema", "key_binding", "max_choices", "max_selections",
    # instance_display field keys, validated by validate_instance_display_config
    "span_target", "display_options", "resizable",
    # display_logic structure
    "show_when", "schema", "operator",
    # phase names
    "consent", "instructions", "training", "annotation", "poststudy",
    # literals and example values
    "true", "false", "y", "n", "not_relevant", "json",
    # what a pairwise scheme stores, alongside "A" and "B". A data value rather
    # than a config key, and the reason a display_logic condition written
    # against the label string never matches
    "tie",
    # filenames and prose
    "config.yaml", "console.error", "text-content", "project.sqlite",
    # deliberately named as non-types; a separate test proves they are not
    "sentiment", "classification", "qa",
    # side-file fields the loaders require, which are not config keys:
    # training instances (flask_server.py:1103), attention checks and gold
    # items (quality_control.py:266, 274)
    "id", "correct_answers", "expected_answer", "gold_label",
    # phases.order, read in flask_server.py; `phases` has no recorded sub-keys
    "order",
    # the field /admin/iaa reports the inferred schema kind under
    "kind",
    # the per-item data field dynamic_options reads when the scheme does not
    # name one, defaulted in flask_server.filter_dynamic_options. A data-file
    # field, so it is in neither the config keys nor the scheme registry.
    "visible_labels",
    # real commands and a provider name, not config keys
    "preview", "destroy", "huggingface",
    # a public API of config_key_docs, named in the pack so an agent calls it
    "get_key_doc",
    # cross-references between the pack's own files
    "deploying.md", "troubleshooting.md",
    # files a running task writes, or the pack tells you to create
    "server.log", "user_state.json",
    # the key the training file must be wrapped in (flask_server.py:1072)
    "training_instances",
    # deploy provider names
    "render",
    # a scheme field six geometry/media types declare
    "source_field",
    # the other stage-1 command, named beside `preview`
    "validate",
    # The ten interface languages ui_language bundles, quoted in
    # building-the-ui.md. Language codes, not config keys.
    "ar", "de", "es", "fr", "hi", "ja", "ko", "pt", "ru", "zh",
    # The MCP control surface a live task exposes through `potato mcp connect`,
    # named in SKILL.md so an agent can call them. They are tool names on the
    # bridge, not config keys -- `mcp.tools` names them without the `live_`
    # prefix the bridge adds, and nothing puts them in a registry this test can
    # read.
    "live_", "live_get_status", "live_get_config", "live_get_progress",
    "live_list_items", "live_get_item", "live_list_annotators",
    "live_get_agreement", "live_submit_annotation", "live_assign_items",
    "live_export_data",
    # the single parameter each live MCP tool declares, and a key passed inside
    # it -- both JSON-RPC argument names rather than anything in a registry
    "arguments", "limit",
    # the file the MCP surface writes its call log to, default of mcp.audit_log
    "mcp_audit.jsonl",
    # the top-level key in user_state.json that spans are stored under, beside
    # instance_id_to_label_to_value. An on-disk field, in no config registry
    "instance_id_to_span_to_value",
    # list_as_text's three sub-keys and the values text_list_prefix_type takes.
    # The key doc describes them in prose rather than registering each one, so
    # iter_key_docs has no entry for `list_as_text.text_list_prefix_type`
    "text_list_prefix_type", "alternating_shading",
    "alphabet", "bullet", "none",
    # column names keyword_highlights_file accepts in its CSV/TSV header, and
    # the accepted spellings of the first one. File-format strings, not config
    "keyword", "word", "pattern", "term", "color",
    # the argument names the live MCP tools publish in their own schemas,
    # quoted in SKILL.md so an agent can call them without a round trip
    "instance_id", "username",
    # the field list_examples returns for each example, named in SKILL.md
    # because get_example wants that value under a differently-named parameter
    "dir",
    # the key /api/keyword_highlights returns naming which fields it scanned --
    # a response field, so it is in no config registry
    "fields_scanned",
    # `min_height` and `max_height` are options of the resizable WRAPPER in
    # instance_display.py, not of any display type, so they appear in no
    # registry's optional_fields and iter_key_docs does not carry them.
    # `max_height` happens to be declared by eleven display types as well;
    # `min_height` is not declared anywhere and is still real. Verified by
    # setting both and reading the computed style.
    "min_height",

    # HTML and CSS vocabulary, not Potato's. The layout section has to name
    # what the generated form gives an assistive reader (`fieldset`, `legend`,
    # `alt`, `lang`) and what a CSS length looks like (`px`), because the
    # accessibility claim is about rendered HTML rather than about config.
    "fieldset", "legend", "alt", "lang", "px",
    # the two values instance_display.layout.direction accepts. Enum values
    # rather than keys, so iter_key_docs does not carry them.
    "vertical",

    # the three values display_options.style_theme accepts on a `document`
    # field. Enum values rather than keys, so iter_key_docs does not carry
    # them; the validator names all three when it refuses a fourth
    "minimal", "print",
}


def _generator_read_keys() -> set:
    """Per-label and per-scheme keys the schema generators actually read.

    Taken from the generator source rather than listed here, because listing
    them is how `key_binding` survived: it reads like a real key, and an
    allowlist would have contained whatever the author believed.
    """
    import inspect
    import re

    try:
        from potato.server_utils.schemas import likert, multiselect, radio, span
        source = "".join(
            inspect.getsource(m) for m in (radio, multiselect, likert, span))
    except Exception:
        return set()
    quoted = set(re.findall(r"""["']([a-z][a-z0-9_]{2,})["']""", source))
    return quoted


def _advertised_mcp_tools() -> set:
    """Tool names the MCP server exposes, read off the built server.

    Not a hardcoded list: `render_task_screenshot` lives on the server rather
    than in `tools_local`, and that split is exactly the kind of thing a second
    list gets wrong.

    Both degraded paths return the fallback rather than an empty set. An empty
    set does not weaken the guard, it inverts it -- the caller treats every
    name it does not return as invented, so a machine without the MCP SDK
    rejects prose that is correct. That is how this first failed in CI, where
    the `mcp` extra is not installed by default.
    """
    fallback = {"render_task_screenshot"}
    try:
        from potato.mcp_server.server import build_server, check_sdk_available
        if not check_sdk_available():
            return fallback
        import asyncio
        server = build_server(root=REPO_ROOT)
        tools = asyncio.run(server.list_tools())
        return {t.name for t in tools}
    except Exception:
        return fallback


def _read(name: str) -> str:
    with open(pack_path(name), "r", encoding="utf-8") as f:
        return f.read()


def _all_pack_text() -> str:
    return "\n".join(_read(name) for name in HAND_WRITTEN)


class TestPackIsComplete:
    @pytest.mark.parametrize("name", HAND_WRITTEN + GENERATED)
    def test_file_exists(self, name):
        assert os.path.isfile(pack_path(name)), f"missing {name}"

    def test_docs_mirror_exists(self):
        assert os.path.isfile(DOCS_MIRROR)


class TestGeneratedHalfIsCurrent:
    def test_check_flag_passes(self):
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            "The references are stale:\n" + result.stdout + result.stderr
        )

    def test_every_type_is_in_the_reference(self):
        text = _read(os.path.join("references", "annotation-types.md"))
        missing = [
            name for name in schema_registry.get_supported_types()
            if f"## {name}\n" not in text
        ]
        assert not missing, (
            f"Annotation types absent from the agent reference: {missing}. "
            "Regenerate: python scripts/generate_references.py"
        )

    def test_every_display_type_is_in_the_reference(self):
        text = _read(os.path.join("references", "config-keys.md"))
        missing = [
            name for name in display_registry.get_supported_types()
            if f"`{name}`" not in text
        ]
        assert not missing, f"Display types absent from the reference: {missing}"

    def test_examples_are_included(self):
        """The worked examples are the reason the reference beats a field list."""
        text = _read(os.path.join("references", "annotation-types.md"))
        assert text.count("```yaml") >= 55, (
            f"only {text.count('```yaml')} worked examples in the reference"
        )


class TestHandWrittenHalfIsTrue:
    """Nothing regenerates these, so every claim in them is checked here."""

    def test_named_annotation_types_are_registered(self):
        registered = set(schema_registry.get_supported_types())
        text = _all_pack_text()

        # Types named in prose as things to use, e.g. example_scheme_for("bws").
        named = set(re.findall(r'example_scheme_for\("([a-z_0-9]+)"\)', text))
        named |= set(re.findall(r"^\s+- annotation_type: ([a-z_0-9]+)", text, re.M))

        unknown = named - registered
        assert not unknown, (
            f"The pack tells agents to use annotation types that do not exist: "
            f"{sorted(unknown)}"
        )

    def test_types_called_out_as_invalid_really_are(self):
        """AGENTS.md names `sentiment` and `classification` as non-types.

        If either were ever registered the warning would be actively wrong.
        """
        registered = set(schema_registry.get_supported_types())
        for name in ("sentiment", "classification", "qa"):
            if name in _all_pack_text():
                assert name not in registered, (
                    f"The pack says {name!r} is not an annotation type, but it "
                    f"is now registered. Fix the prose."
                )

    def test_named_config_keys_exist(self):
        text = _all_pack_text()
        named = set(re.findall(r'get_key_doc\("([a-z_0-9.]+)"\)', text))
        named |= {"annotation_task_name", "task_dir", "output_annotation_dir",
                  "item_properties", "data_files", "annotation_schemes"}

        def known(path):
            node = KNOWN_CONFIG_KEYS
            for part in path.split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                elif isinstance(node, set) and part in node:
                    node = None
                else:
                    return False
            return True

        unknown = sorted(p for p in named if not known(p))
        assert not unknown, f"The pack names config keys that do not exist: {unknown}"

    def test_named_commands_are_dispatched(self):
        """Every `potato <x>` the pack tells an agent to run must resolve."""
        text = _all_pack_text()
        commands = set(re.findall(r"potato ([a-z][a-z-]+)", text))

        if not has_potato_repo():
            pytest.skip("no Potato checkout; set POTATO_REPO")
        with open(potato_repo_path("potato", "flask_server.py"),
                  encoding="utf-8") as f:
            server_source = f.read()

        from potato.server_utils.arg_utils import arguments  # noqa: F401

        for command in sorted(commands):
            dispatched = (
                f"sys.argv[1] == '{command}'" in server_source
                or f'sys.argv[1] == "{command}"' in server_source
                or f"'{command}'" in server_source
            )
            assert dispatched, (
                f"The pack tells agents to run `potato {command}`, which is not "
                f"dispatched in flask_server.main()"
            )

    def test_the_schema_url_is_the_published_one(self):
        from potato.server_utils.config_schema import SCHEMA_URL

        assert SCHEMA_URL in _read("AGENTS.md"), (
            "AGENTS.md tells agents to paste a schema modeline; it must be the "
            "URL the schema is actually published at."
        )

    def test_skill_has_frontmatter(self):
        """Claude Code will not load a skill without name and description."""
        text = _read("SKILL.md")
        assert text.startswith("---\n")
        head = text.split("---", 2)[1]
        assert "name:" in head and "description:" in head


class TestEveryIdentifierInProseIsReal:
    """Each backticked name is checked against the thing that defines it.

    Deliberately not a list of approved strings: an allowlist would have
    accepted `textbox` as readily as `text`. The point is to compare the prose
    against the registries and enums the server actually reads.
    """

    @staticmethod
    def _identifiers():
        import re

        tokens = set()
        for name in HAND_WRITTEN:
            tokens |= set(re.findall(
                r"`([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_.]*)*)`", _read(name)))
        return tokens

    @staticmethod
    def _vocabulary():
        from potato.server_utils.config_module import _VALID_ASSIGNMENT_STRATEGIES
        from potato.server_utils.display_logic import SUPPORTED_OPERATORS
        from potato.server_utils.schemas.registry import (
            UNIVERSAL_OPTIONAL_FIELDS, UNIVERSAL_REQUIRED_FIELDS,
        )
        from potato.mcp_server import tools_local

        vocab = set(schema_registry.get_supported_types())
        vocab |= set(display_registry.get_supported_types())
        vocab |= set(SUPPORTED_OPERATORS)
        vocab |= {s.lower() for s in _VALID_ASSIGNMENT_STRATEGIES}
        vocab |= set(UNIVERSAL_OPTIONAL_FIELDS) | set(UNIVERSAL_REQUIRED_FIELDS)
        vocab |= PROSE_IDENTIFIERS
        # MCP tool names. The local ones are functions in `tools_local`;
        # `render_task_screenshot` is defined on the server itself, so it is
        # taken from the tool list the server advertises rather than guessed.
        vocab |= {n for n in dir(tools_local) if not n.startswith("_")}
        vocab |= _advertised_mcp_tools()
        vocab |= _generator_read_keys()
        # Every field any registered scheme declares. The modality references
        # name `steps_key`, `video_key`, `audio_key` and a dozen more because
        # each family has its own convention for "where is my data" -- which is
        # the point of those files. Taken from the registry, so a name that
        # stops being a field fails here.
        for _schema in schema_registry.list_schemas():
            vocab |= set(_schema["required_fields"])
            vocab |= set(_schema["optional_fields"])
        # Every option any registered display declares. The scheme loop above
        # does the same for annotation types; without this half a display
        # option named in prose -- `show_turn_numbers`, `span_target`'s
        # neighbours on a field -- has no registry behind it. Read off the
        # DisplayDefinition rather than `list_displays()`, which under-reports
        # (see the note at the top of this file).
        for _name in display_registry.get_supported_types():
            _defn = display_registry.get(_name)
            for _attr in ("required_fields", "optional_fields"):
                _fields = getattr(_defn, _attr, None) or ()
                vocab |= set(_fields)
        # Export and import format names. `getting-the-data-out.md` routes a
        # downstream use to a format and `importing-existing-work.md` names the
        # readers, so both lists have to come from the registries -- a format
        # that is renamed or dropped must fail here rather than sit in prose.
        from potato.export import export_registry
        vocab |= {f["format_name"] for f in export_registry.list_exporters()}
        from potato.importers import import_registry
        vocab |= set(import_registry.get_supported_formats())
        # Validated survey instruments. `interviewing.md` and
        # `phases-and-pages.md` name them so a researcher can be offered one by
        # id, and an id that stops shipping has to fail here rather than send
        # someone looking for a questionnaire that is gone. Only the hyphen-free
        # ids reach this check -- `who-5` does not match the token pattern --
        # which is why the registry rather than a list is the right source.
        from potato.survey_instruments import get_registry as _instrument_registry
        vocab |= set(_instrument_registry()["instruments"])
        # The pack's own filenames, so cross-references resolve against what
        # actually ships rather than against a list someone remembered to edit.
        vocab |= set(REFERENCES)
        # The skill's own helpers, resolved against the directory rather than
        # allowlisted: a script the prose tells an agent to run has to be a
        # script that ships.
        vocab |= set(SCRIPTS)
        vocab |= {name[:-3] for name in SCRIPTS}
        return vocab

    def test_no_invented_identifiers(self):
        def known_key(path):
            """Walk KNOWN_CONFIG_KEYS, stopping where it stops describing.

            A set in that structure is a leaf listing sub-keys with no further
            nesting recorded, so `instance_display.layout.gap` runs out of
            structure at `layout`. That key is real -- it is validated in
            `validate_instance_display_config` -- and the structure simply
            does not go that deep. Treat reaching a set member as known rather
            than as a failure, or this test rejects true prose.
            """
            node = KNOWN_CONFIG_KEYS
            for part in path.split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                elif isinstance(node, set) and part in node:
                    return True
                elif node is None:
                    return True
                else:
                    return False
            return True

        vocabulary = self._vocabulary()
        unknown = sorted(
            token for token in self._identifiers()
            if token not in vocabulary and not known_key(token)
        )
        assert not unknown, (
            "The pack names identifiers that exist nowhere in Potato:\n  "
            + "\n  ".join(unknown)
            + "\n\nEither the prose is wrong, or add it to PROSE_IDENTIFIERS "
              "with a reason."
        )

    def test_the_ui_reference_covers_every_display_type(self):
        text = _read(os.path.join("references", "building-the-ui.md"))
        missing = sorted(
            name for name in display_registry.get_supported_types()
            if f"`{name}`" not in text
        )
        assert not missing, (
            f"These display types are not in building-the-ui.md: {missing}. "
            f"An agent reading it would not know they exist."
        )

    def test_span_target_claim_matches_the_registry(self):
        """The reference states a count; the registry decides it."""
        text = _read(os.path.join("references", "building-the-ui.md"))
        capable = display_registry.get_span_target_capable_types()
        assert f"{len(capable)} types accept it" in text.replace("Twelve", "12"), (
            f"building-the-ui.md states a span_target count that is not "
            f"{len(capable)}; the registry now says {sorted(capable)}"
        )


class TestDocumentedLabelKeysAreRead:
    """Keys documented *inside a label dict* must be ones a generator reads.

    This is the hole that let `key_binding` into the reference and kept it
    there. It is not an annotation type, not a display type and not a config
    key, so no registry check saw it; `potato validate --strict` does not
    descend into `annotation_schemes[].labels[]` either. It validated, rendered,
    and produced no keyboard shortcuts at all.

    So the check is behavioural: take the YAML the reference tells an agent to
    write, generate the scheme, and assert the feature actually appears.
    """

    @staticmethod
    def _label_keys_in_docs():
        """Keys used inside a `labels:` block in any hand-written YAML sample."""
        import re

        keys = set()
        for name in HAND_WRITTEN:
            text = _read(name)
            for block in re.findall(r"```yaml\n(.*?)```", text, re.S):
                lines = block.splitlines()
                for index, line in enumerate(lines):
                    # Only the block form nests keys. `labels: [Yes, No]` has
                    # none, and splitting on the first `labels:` in the sample
                    # would attribute every later key in the file to it.
                    match = re.match(r"^(\s*)labels:\s*$", line)
                    if not match:
                        continue
                    indent = len(match.group(1))
                    for following in lines[index + 1:]:
                        if not following.strip():
                            continue
                        if len(following) - len(following.lstrip()) <= indent:
                            break
                        found = re.match(r"^\s+(?:-\s+)?([a-z_]+):", following)
                        if found:
                            keys.add(found.group(1))
        return keys - {"name", "labels"}

    def test_documented_label_keys_are_declared_somewhere(self):
        """Every per-label key named in a sample must be read by a generator."""
        import inspect

        from potato.server_utils.schemas import radio, multiselect, likert

        source = "".join(
            inspect.getsource(m) for m in (radio, multiselect, likert)
        )
        unread = sorted(
            key for key in self._label_keys_in_docs()
            if f'"{key}"' not in source and f"'{key}'" not in source
        )
        assert not unread, (
            f"The pack shows these keys inside a `labels:` block, and no "
            f"schema generator reads them: {unread}. A key nothing reads is "
            f"silently ignored -- it validates and does nothing."
        )

    def test_the_documented_shortcut_key_actually_produces_a_shortcut(self):
        """End-to-end: the documented YAML must yield a real keybinding.

        `key_binding` passed every other check in this file. Only generating
        the scheme and looking at the result catches it.
        """
        import re

        from potato.server_utils.schemas.registry import schema_registry

        text = _read(os.path.join("references", "building-the-ui.md"))
        match = re.search(r"^\s+(key_[a-z_]+):\s*y\s*$", text, re.M)
        assert match, "building-the-ui.md no longer shows a per-label shortcut key"
        documented_key = match.group(1)

        _html, keybindings = schema_registry.generate({
            "annotation_type": "radio",
            "name": "probe",
            "description": "probe",
            "labels": [{"name": "Yes", documented_key: "y"}],
        })
        assert keybindings, (
            f"the pack documents `{documented_key}` as the per-label keyboard "
            f"shortcut, and a scheme using it produces no keybindings at all"
        )


class TestTheScriptsAreReal:
    """The skill tells an agent to run these scripts, so they have to run.

    Prose that says "use `boot_and_check.py`" is worse than no prose at all if
    the file is missing, not executable, or throws on import: the agent falls
    back to reconstructing the procedure and has lost the round trip.
    """

    @pytest.mark.parametrize("name", SCRIPTS)
    def test_the_script_ships(self, name):
        assert os.path.isfile(pack_path(os.path.join("scripts", name)))

    @pytest.mark.parametrize("name", SCRIPTS)
    def test_the_script_runs(self, name):
        """`--help` exercises import and argument parsing without side effects."""
        result = subprocess.run(
            [sys.executable, pack_path(os.path.join("scripts", name)), "--help"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"{name} --help exited {result.returncode}:\n{result.stderr}")
        assert "usage:" in result.stdout

    @pytest.mark.parametrize("name", SCRIPTS)
    def test_the_skill_says_what_it_is_for(self, name):
        """A script nothing points at will never be run."""
        assert name in _read("SKILL.md"), (
            f"{name} ships but SKILL.md never mentions it")

    def test_the_docstring_says_what_it_does(self):
        """Each script is the documentation for itself once installed."""
        for name in SCRIPTS:
            source = open(pack_path(os.path.join("scripts", name)),
                          encoding="utf-8").read()
            tree = ast.parse(source)
            doc = ast.get_docstring(tree)
            assert doc and len(doc.split()) > 30, (
                f"{name} needs a docstring that explains why it exists -- it is "
                f"what `--help` prints and the only documentation an agent has "
                f"once the skill is installed somewhere else")


class TestThePackagedSkillIsComplete:
    """`scripts/package_skill.py` is the route to every host but the marketplace.

    The same content, assembled as a standalone directory for the Agent SDK and
    as a zip for the API. If it drops a reference or a helper, the skill still
    loads and quietly cannot do half of what it says.
    """

    def test_it_builds_everything_the_skill_needs(self, tmp_path):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "package_skill",
            os.path.join(REPO_ROOT, "scripts", "package_skill.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        skill_dir = module.build(str(tmp_path))
        archive = module.zip_skill(skill_dir)

        assert os.path.isfile(os.path.join(skill_dir, "SKILL.md"))
        for name in REFERENCES:
            assert os.path.isfile(os.path.join(skill_dir, "references", name)), (
                f"{name} is in the pack but not in the packaged skill")
        for name in SCRIPTS:
            path = os.path.join(skill_dir, "scripts", name)
            assert os.path.isfile(path) and os.access(path, os.X_OK)

        import zipfile

        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
        assert f"{SKILL_NAME}/SKILL.md" in names, (
            "the zip must have the skill directory as its top-level entry")
        assert len(names) == 1 + len(REFERENCES) + len(SCRIPTS)


class TestShowcaseNumbersAgree:
    """The showcase counts are stated in four places and live in another repo.

    `test_doc_counts` cannot help here: potato-showcase is a
    separate repository and is not present in CI, so there is no registry to
    compare against. What can be checked for free is that the pack does not
    contradict itself -- which is how "56 annotation types" survived in
    `llms.txt` while every other page said 61.

    If the showcase grows, these move together or this fails.
    """

    #: Every file in the pack that states how big the showcase is.
    SOURCES = (
        "SKILL.md",
        os.path.join("references", "finding-a-design.md"),
        os.path.join("references", "writing-guidelines.md"),
        os.path.join("scripts", "find_design.py"),
    )

    @staticmethod
    def _numbers(text):
        total = set(re.findall(r"(\d+) (?:annotation task )?designs", text))
        total |= set(re.findall(r"of the (\d+)\b", text))
        with_instructions = set(re.findall(r"(\d+) of the \d+", text))
        with_instructions |= set(re.findall(r"(\d+) of them carry", text))
        return total, with_instructions

    def test_the_total_is_the_same_everywhere(self):
        seen = {}
        for name in self.SOURCES:
            with open(pack_path(name), encoding="utf-8") as f:
                total, _ = self._numbers(f.read())
            if total:
                seen[name] = total
        values = set().union(*seen.values()) if seen else set()
        assert len(values) == 1, (
            f"the pack states more than one size for the showcase: {seen}")

    def test_the_instruction_count_is_the_same_everywhere(self):
        seen = {}
        for name in self.SOURCES:
            with open(pack_path(name), encoding="utf-8") as f:
                _, with_instructions = self._numbers(f.read())
            if with_instructions:
                seen[name] = with_instructions
        values = set().union(*seen.values()) if seen else set()
        assert len(values) == 1, (
            f"the pack states more than one count of showcase designs that "
            f"carry written instructions: {seen}")

    def test_the_manifest_agrees_when_a_clone_is_present(self):
        """Only runs where the showcase is checked out; skipped in CI."""
        import json

        candidates = [
            os.environ.get("POTATO_SHOWCASE", ""),
            os.path.join(REPO_ROOT, "..", "potato-showcase"),
        ]
        manifest_path = next(
            (os.path.join(d, "showcase.manifest.json") for d in candidates
             if d and os.path.isfile(os.path.join(d, "showcase.manifest.json"))),
            None)
        if manifest_path is None:
            pytest.skip("no potato-showcase clone with a manifest")

        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        with open(pack_path(os.path.join("references", "finding-a-design.md")),
                  encoding="utf-8") as f:
            text = f.read()

        assert str(manifest["count"]) in text, (
            f"the showcase has {manifest['count']} designs and "
            f"finding-a-design.md does not say so")
        assert str(manifest["with_instructions"]) in text, (
            f"{manifest['with_instructions']} designs carry instructions and "
            f"finding-a-design.md does not say so")


class TestThePluginManifestsAreValid:
    """The manifests are the install path, and nothing else reads them.

    A broken `marketplace.json` fails at `/plugin marketplace add`, on someone
    else's machine, with no test in between. Every field checked here is one
    Claude Code reads at load time.
    """

    #: Names Anthropic reserves. A marketplace using one stops loading and
    #: reports itself as registered from an untrusted source.
    RESERVED = {
        "claude-code-marketplace", "claude-code-plugins", "claude-plugins-official",
        "claude-plugins-community", "claude-community", "anthropic-marketplace",
        "anthropic-plugins", "agent-skills", "anthropic-agent-skills",
        "knowledge-work-plugins", "life-sciences", "claude-for-legal",
        "claude-for-financial-services", "financial-services-plugins",
        "first-party-plugins", "healthcare",
    }

    @staticmethod
    def _load(name):
        import json

        with open(os.path.join(REPO_ROOT, ".claude-plugin", name),
                  encoding="utf-8") as f:
            return json.load(f)

    def test_the_marketplace_has_its_required_fields(self):
        market = self._load("marketplace.json")
        for field in ("name", "owner", "plugins"):
            assert field in market, f"marketplace.json has no {field!r}"
        assert market["owner"].get("name"), "owner.name is required"
        assert market["plugins"], "a marketplace with no plugins installs nothing"

    def test_the_marketplace_name_is_kebab_case_and_unreserved(self):
        name = self._load("marketplace.json")["name"]
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name), (
            f"marketplace name {name!r} must be kebab-case with no spaces")
        assert name not in self.RESERVED, (
            f"{name!r} is reserved for Anthropic; Claude Code will refuse to "
            f"load this marketplace")

    def test_every_plugin_entry_has_a_name_and_a_source(self):
        for entry in self._load("marketplace.json")["plugins"]:
            assert entry.get("name"), "a plugin entry has no name"
            assert entry.get("source"), f"{entry['name']} has no source"

    def test_the_plugin_source_resolves(self):
        """Relative sources resolve against the marketplace root, not `.claude-plugin/`."""
        for entry in self._load("marketplace.json")["plugins"]:
            source = entry["source"]
            if not isinstance(source, str):
                continue
            assert not source.startswith(".."), (
                "a source may not point outside the marketplace root")
            assert os.path.isdir(os.path.join(REPO_ROOT, source)), (
                f"{entry['name']} points at {source}, which does not exist")

    def test_the_plugin_manifest_agrees_with_the_marketplace_entry(self):
        plugin = self._load("plugin.json")
        entry = next(e for e in self._load("marketplace.json")["plugins"]
                     if e["name"] == plugin["name"])
        assert plugin["name"] == SKILL_NAME
        assert plugin.get("version") == entry.get("version"), (
            "plugin.json and marketplace.json state different versions; a user "
            "gets updates only when the version string changes, so the two "
            "disagreeing means it is ambiguous which one pins them")

    def test_the_skill_is_where_claude_code_looks(self):
        """A skill must be at `skills/<name>/SKILL.md`, and `<name>` is the id."""
        assert os.path.isfile(
            os.path.join(REPO_ROOT, "skills", SKILL_NAME, "SKILL.md"))

    def test_the_frontmatter_name_matches_the_directory(self):
        """Claude Code invokes the skill by its frontmatter name, not the path."""
        text = _read("SKILL.md")
        head = text.split("---", 2)[1]
        declared = re.search(r"^name:\s*(\S+)\s*$", head, re.M)
        assert declared, "SKILL.md declares no name"
        assert declared.group(1) == SKILL_NAME, (
            f"SKILL.md is installed at skills/{SKILL_NAME}/ but calls itself "
            f"{declared.group(1)!r}")

    def test_components_are_not_hidden_inside_the_metadata_directory(self):
        """`skills/` must sit at the plugin root; inside `.claude-plugin/` it is ignored."""
        stray = os.path.join(REPO_ROOT, ".claude-plugin", "skills")
        assert not os.path.exists(stray), (
            "skills/ inside .claude-plugin/ is never scanned")

    def test_the_skill_declares_no_allowed_tools(self):
        """An allowlist would cut off whatever browser tooling is present.

        The skill tells an agent to drive a browser and take screenshots with
        whatever MCP tooling the host has. Naming tools here silently disables
        the half of the workflow that proves the interface renders.
        """
        head = _read("SKILL.md").split("---", 2)[1]
        assert "allowed-tools" not in head


class TestTheScriptsShipRunnable:
    @pytest.mark.parametrize("name", SCRIPTS)
    def test_the_committed_script_is_executable(self, name):
        """Git records the mode, and the plugin is installed by clone.

        There is no copy step left to restore a lost executable bit, so the bit
        has to be right in the repository.
        """
        path = pack_path(os.path.join("scripts", name))
        assert os.access(path, os.X_OK), (
            f"{name} is not executable; `git update-index --chmod=+x` it")
