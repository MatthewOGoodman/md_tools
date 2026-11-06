"""Unit tests for md_tools.

Tests the custom MarkdownTree parser, path resolution helpers,
tree operations, and CLI commands (via subprocess).

md_tools is a standalone script with shebang. We import it as a module
using importlib for unit tests, and use subprocess for CLI integration tests.
"""

import importlib.machinery
import importlib.util
import os
import sys
import subprocess
import textwrap
import pytest
from pathlib import Path

# ---------------------------------------------------------------------------
# Import md_tools as a module (safe: has if __name__ == '__main__' guard)
# ---------------------------------------------------------------------------
# The installed package is the default. MD_TOOLS_PATH points the suite at a dev
# copy (e.g. md_tools_v2.py) during a refactor, loaded from that path instead.
_md_tools_path = os.environ.get("MD_TOOLS_PATH")
if _md_tools_path:
    _loader = importlib.machinery.SourceFileLoader("md_tools", _md_tools_path)
    _spec = importlib.util.spec_from_loader("md_tools", _loader, origin=_md_tools_path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
else:
    import md_tools as _mod
    _md_tools_path = _mod.__file__

MarkdownTree = _mod.MarkdownTree
detect_single_root = _mod.detect_single_root
prepend_root_prefix = _mod.prepend_root_prefix
find_node_with_suggestions = _mod.find_node_with_suggestions
build_node_path = _mod.build_node_path
collect_all_paths = _mod.collect_all_paths
suggest_matches = _mod.suggest_matches
calculate_position = _mod.calculate_position
insert_section = _mod.insert_section
_strip_state_tags = _mod._strip_state_tags
# SELECT → TRANSFORM → EMIT core (function-space redesign)
collect_children = _mod.collect_children
_resolve_rel_path = _mod._resolve_rel_path
select_keep = _mod.select_keep
select_omit = _mod.select_omit
strip_markers = _mod.strip_markers
strip_bodies = _mod.strip_bodies
build_view = _mod.build_view


# ============================================================================
# Fixtures
# ============================================================================

SIMPLE_DOC = textwrap.dedent("""\
    # Root

    ## Section A

    Content A.

    ## Section B

    Content B.

    ## Section C

    Content C.
""")

NESTED_DOC = textwrap.dedent("""\
    # Project

    ## Active Work

    ### TODO: First Item

    Description of first.

    ### TODO: Second Item

    Description of second.

    ### TODO: Third Item

    Description of third.

    ## Key Decisions

    Some decisions.
""")

CODE_FENCE_DOC = textwrap.dedent("""\
    # Guide

    ## Setup

    Install things:

    ```bash
    # This is NOT a heading
    ## Neither is this
    echo "hello"
    ```

    ## Usage

    Use the tool.
""")

MULTI_ROOT_DOC = textwrap.dedent("""\
    ## Alpha

    Alpha content.

    ## Beta

    Beta content.

    ## Gamma

    Gamma content.
""")


@pytest.fixture
def simple_tree():
    tree = MarkdownTree()
    tree.parse(SIMPLE_DOC)
    return tree


@pytest.fixture
def nested_tree():
    tree = MarkdownTree()
    tree.parse(NESTED_DOC)
    return tree


@pytest.fixture
def simple_file(tmp_path):
    f = tmp_path / "simple.md"
    f.write_text(SIMPLE_DOC)
    return f


@pytest.fixture
def nested_file(tmp_path):
    f = tmp_path / "nested.md"
    f.write_text(NESTED_DOC)
    return f


# ============================================================================
# 1. Parser Round-Trip Tests
# ============================================================================

class TestParserRoundTrip:
    """Parse → dump should preserve document structure."""

    def test_simple_doc_round_trip(self):
        tree = MarkdownTree()
        tree.parse(SIMPLE_DOC)
        output = tree.dump()
        # Re-parse the output and compare structure
        tree2 = MarkdownTree()
        tree2.parse(output)
        assert len(tree2.root.children) == 1  # single root
        root = tree2.root.children[0]
        assert root.title == "Root"
        assert len(root.children) == 3
        assert [c.title for c in root.children] == ["Section A", "Section B", "Section C"]

    def test_nested_doc_round_trip(self):
        tree = MarkdownTree()
        tree.parse(NESTED_DOC)
        output = tree.dump()
        tree2 = MarkdownTree()
        tree2.parse(output)
        root = tree2.root.children[0]
        assert root.title == "Project"
        active = root.children[0]
        assert active.title == "Active Work"
        assert len(active.children) == 3
        assert active.children[0].title == "TODO: First Item"

    def test_code_fence_headings_ignored(self):
        """Headings inside ``` code blocks must NOT be parsed as tree nodes."""
        tree = MarkdownTree()
        tree.parse(CODE_FENCE_DOC)
        root = tree.root.children[0]
        assert root.title == "Guide"
        # Only Setup and Usage — NOT the # and ## inside the code fence
        assert len(root.children) == 2
        assert [c.title for c in root.children] == ["Setup", "Usage"]

    def test_code_fence_content_preserved(self):
        """Code fence content should be preserved in dump."""
        tree = MarkdownTree()
        tree.parse(CODE_FENCE_DOC)
        output = tree.dump()
        assert "```bash" in output
        assert '# This is NOT a heading' in output
        assert '## Neither is this' in output

    def test_multi_root_doc(self):
        """Three same-level ## with no # parse as three SIBLINGS (real multiple roots),
        not a chain. The parser nests by heading level, so a heading never gets
        absorbed under a same-level predecessor."""
        tree = MarkdownTree()
        tree.parse(MULTI_ROOT_DOC)
        assert [c.title for c in tree.root.children] == ["Alpha", "Beta", "Gamma"]
        assert all(c.children == [] for c in tree.root.children)

    def test_empty_content(self):
        tree = MarkdownTree()
        tree.parse("")
        assert len(tree.root.children) == 0

    def test_no_headings(self):
        """Plain text with no headings."""
        tree = MarkdownTree()
        tree.parse("Just some text.\n\nMore text.\n")
        assert len(tree.root.children) == 0


# ============================================================================
# 2. Path Resolution Tests
# ============================================================================

class TestPathResolution:

    def test_detect_single_root(self, simple_tree):
        assert detect_single_root(simple_tree) == "Root"

    def test_detect_single_root_none_for_rootless_siblings(self):
        """Three same-level ## with no # are real siblings, so there is NO single root."""
        tree = MarkdownTree()
        tree.parse(MULTI_ROOT_DOC)
        assert detect_single_root(tree) is None

    def test_prepend_root_prefix_adds_when_missing(self):
        assert prepend_root_prefix("Section A", "Root") == "Root:/:Section A"

    def test_prepend_root_prefix_skips_when_present(self):
        assert prepend_root_prefix("Root:/:Section A", "Root") == "Root:/:Section A"

    def test_prepend_root_prefix_skips_when_exact_root(self):
        assert prepend_root_prefix("Root", "Root") == "Root"

    def test_prepend_root_prefix_no_root(self):
        assert prepend_root_prefix("Section A", None) == "Section A"

    def test_find_node_exact(self, simple_tree):
        node = simple_tree.find_node_by_path("Root:/:Section B")
        assert node is not None
        assert node.title == "Section B"

    def test_find_node_not_found(self, simple_tree):
        node = simple_tree.find_node_by_path("Root:/:Nonexistent")
        assert node is None

    def test_find_node_nested(self, nested_tree):
        node = nested_tree.find_node_by_path("Project:/:Active Work:/:TODO: Second Item")
        assert node is not None
        assert node.title == "TODO: Second Item"

    def test_find_node_with_suggestions_case_insensitive(self, simple_tree):
        """Case-insensitive fallback should find the node."""
        node, failed = find_node_with_suggestions(simple_tree, "root:/:section a")
        assert not failed
        assert node is not None
        assert node.title == "Section A"

    def test_find_node_with_suggestions_not_found(self, simple_tree):
        """Nonexistent path should fail with suggestions."""
        node, failed = find_node_with_suggestions(simple_tree, "Root:/:Nonexistent")
        assert failed or node is None

    def test_build_node_path(self, nested_tree):
        node = nested_tree.find_node_by_path("Project:/:Active Work:/:TODO: First Item")
        path = build_node_path(node)
        assert path == "Project:/:Active Work:/:TODO: First Item"

    def test_collect_all_paths(self, simple_tree):
        paths = collect_all_paths(simple_tree.root)
        assert "Root" in paths
        assert "Root:/:Section A" in paths
        assert "Root:/:Section B" in paths
        assert "Root:/:Section C" in paths
        assert len(paths) == 4

    def test_suggest_matches(self):
        all_paths = [
            "Root:/:Active Work:/:TODO: First",
            "Root:/:Active Work:/:TODO: Second",
            "Root:/:Key Decisions",
        ]
        suggestions = suggest_matches("TODO", all_paths)
        assert len(suggestions) >= 2
        assert all("TODO" in s for s in suggestions)


# ============================================================================
# 3. Tree Operations Tests
# ============================================================================

class TestTreeOperations:

    def test_calculate_position_first(self, nested_tree):
        active = nested_tree.find_node_by_path("Project:/:Active Work")
        pos = calculate_position(active, "^")
        assert pos == 0

    def test_calculate_position_after_sibling(self, nested_tree):
        active = nested_tree.find_node_by_path("Project:/:Active Work")
        pos = calculate_position(active, "TODO: First Item")
        assert pos == 1  # After first item

    def test_calculate_position_not_found(self, nested_tree):
        """Missing sibling should return None."""
        active = nested_tree.find_node_by_path("Project:/:Active Work")
        pos = calculate_position(active, "Nonexistent")
        assert pos is None

    def test_calculate_position_fuzzy_prefix(self, nested_tree):
        """Regression: --after-sibling must resolve a UNIQUE prefix, not require the
        exact title. Real titles carry state tags ('  [ ]'), so exact-only matching
        made positional inserts fail in practice."""
        active = nested_tree.find_node_by_path("Project:/:Active Work")
        # "TODO: First" is a unique prefix of "TODO: First Item"
        assert calculate_position(active, "TODO: First") == 1

    def test_calculate_position_fuzzy_ambiguous(self, nested_tree):
        """An ambiguous fuzzy match must resolve to None, not silently pick the first."""
        active = nested_tree.find_node_by_path("Project:/:Active Work")
        # "TODO:" prefixes all three children — ambiguous
        assert calculate_position(active, "TODO:") is None

    def test_add_section(self, simple_tree):
        node = simple_tree.add_section("Root", "Section D", content="New content.")
        assert node is not None
        assert node.title == "Section D"
        assert simple_tree.root.children[0].children[-1].title == "Section D"

    def test_remove_section(self, simple_tree):
        result = simple_tree.remove_section("Root:/:Section B")
        assert result is True
        assert simple_tree.find_node_by_path("Root:/:Section B") is None
        assert len(simple_tree.root.children[0].children) == 2


# ============================================================================
# 4. CLI Integration Tests (subprocess)
# ============================================================================

# The CLI under test, run by the interpreter running this suite: the source
# carries a portable shebang, so the file is never executed directly.
MD_TOOLS = [sys.executable, _md_tools_path]  # honors MD_TOOLS_PATH for dev-copy targeting


class TestCLIInsert:
    """insert takes a DESTINATION plus a markdown fragment whose FIRST heading
    becomes the new section's title — mirroring replace, which also parses its
    content as markdown rather than writing it as literal body text. Payload
    heading levels re-level to nest under the destination."""

    def test_insert_default_append(self, simple_file):
        """Insert with no positioning appends to end."""
        subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), "Root", "# Section D\n\nNew content."],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        root = tree.root.children[0]
        assert root.children[-1].title == "Section D"

    def test_insert_after_sibling(self, simple_file):
        """Insert after a specific sibling."""
        subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), "Root", "# Section X\n\nInserted.",
             "--after-sibling", "Section A"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        root = tree.root.children[0]
        titles = [c.title for c in root.children]
        assert titles == ["Section A", "Section X", "Section B", "Section C"]

    def test_insert_after_sibling_fuzzy(self, nested_file):
        """--after-sibling accepts a UNIQUE PREFIX, not just the exact title."""
        subprocess.run(
            [*MD_TOOLS, "insert", str(nested_file), "Active Work", "# TODO: Inserted\n\nBody.",
             "--after-sibling", "TODO: First"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(nested_file.read_text())
        active = tree.find_node_by_path("Project:/:Active Work")
        titles = [c.title for c in active.children]
        assert titles == ["TODO: First Item", "TODO: Inserted",
                          "TODO: Second Item", "TODO: Third Item"]

    def test_insert_first_child(self, simple_file):
        """Insert as first child with ^."""
        subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), "Root", "# First!\n\nI am first.",
             "--after-sibling", "^"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        root = tree.root.children[0]
        assert root.children[0].title == "First!"

    def test_insert_before_sibling(self, simple_file):
        """--before-sibling places the payload ahead of the named sibling."""
        subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), "Root", "# Section W\n\nBefore B.",
             "--before-sibling", "Section B"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        root = tree.root.children[0]
        titles = [c.title for c in root.children]
        assert titles == ["Section A", "Section W", "Section B", "Section C"]

    def test_insert_stdin(self, simple_file):
        """Insert with content from stdin."""
        content = "# Stdin Section\n\nMulti-line content.\n\n**Bold** text.\n"
        subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), "Root", "--stdin"],
            input=content, text=True, check=True,
        )
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        root = tree.root.children[0]
        assert root.children[-1].title == "Stdin Section"
        assert "**Bold** text." in tree.dump()

    def test_insert_bad_sibling_fails(self, simple_file):
        """Insert with nonexistent sibling should fail and not modify file."""
        result = subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), "Root", "# Bad\n\nContent.",
             "--after-sibling", "Nonexistent Section"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "not found" in result.stderr.lower()
        assert "Available siblings" in result.stderr
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        root = tree.root.children[0]
        assert not any(c.title == "Bad" for c in root.children)

    def test_insert_relevels_payload_subsections(self, simple_file):
        """Payload headings nest UNDER the new section whatever depth they were
        written at. Writing them at the destination's own level used to make them
        siblings of their intended parent, scattering them across the document
        while the command still reported success."""
        payload = "# New Parent\n\nIntro.\n\n## Sub One\n\nBody.\n\n## Sub Two\n"
        subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), "Root", "--stdin"],
            input=payload, text=True, check=True,
        )
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        root = tree.root.children[0]
        parent = [c for c in root.children if c.title == "New Parent"][0]
        assert [c.title for c in parent.children] == ["Sub One", "Sub Two"]
        # and NOT scattered as siblings of New Parent
        assert not any(c.title in ("Sub One", "Sub Two") for c in root.children)

    def test_insert_preserves_fenced_headings(self, simple_file):
        """Headings inside a code fence are content, not structure — a gated code
        block survives byte-exact and mints no sections."""
        payload = ("# Gated\n\n```\n## Header 1\n"
                   'complex --call "with quotations"\n### Header 2\n```\n')
        subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), "Root", "--stdin"],
            input=payload, text=True, check=True,
        )
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        root = tree.root.children[0]
        gated = [c for c in root.children if c.title == "Gated"][0]
        assert gated.children == []
        assert not any(c.title.startswith("Header") for c in root.children)
        dumped = simple_file.read_text()
        assert "## Header 1" in dumped and 'complex --call "with quotations"' in dumped

    def test_insert_headingless_content_errors(self, simple_file):
        """Migration guard. The superseded form passed the new TITLE where the
        destination now goes, with headingless body text — which would otherwise
        silently create a section named after the intended destination."""
        original = simple_file.read_text()
        result = subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), "My New Title", "just body text"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "heading" in result.stderr.lower()
        assert simple_file.read_text() == original

    def test_insert_content_before_heading_errors(self, simple_file):
        """Text ahead of the payload's heading would be dropped by the parser, so
        it is refused rather than silently discarded."""
        original = simple_file.read_text()
        result = subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), "Root", "stray lead\n\n# Title\n"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert simple_file.read_text() == original

    def test_insert_dot_destination(self, simple_file):
        """'.' addresses the file root, so the payload becomes a top-level section."""
        subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), ".", "# Via Dot\n\nBody."],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        root = tree.root.children[0]
        assert any(c.title == "Via Dot" for c in root.children)

    def test_insert_multiple_top_level_payload_headings(self, simple_file):
        """A payload carrying several top-level headings inserts them as siblings."""
        payload = "# Alpha\n\nA body.\n\n# Beta\n\nB body.\n"
        subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), "Root", "--stdin"],
            input=payload, text=True, check=True,
        )
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        root = tree.root.children[0]
        titles = [c.title for c in root.children]
        assert titles[-2:] == ["Alpha", "Beta"]


class TestCLIListAndRead:

    def test_list(self, nested_file):
        result = subprocess.run(
            [*MD_TOOLS, "list", str(nested_file)],
            capture_output=True, text=True, check=True,
        )
        assert "Project" in result.stdout
        assert "Active Work" in result.stdout
        assert "TODO: First Item" in result.stdout

    def test_read_section(self, nested_file):
        result = subprocess.run(
            [*MD_TOOLS, "read", str(nested_file), "Active Work"],
            capture_output=True, text=True, check=True,
        )
        assert "TODO: First Item" in result.stdout
        assert "Description of first" in result.stdout


class TestCLIMapAndListPaths:

    def test_map(self, nested_file):
        """Map shows structure with line counts."""
        result = subprocess.run(
            [*MD_TOOLS, "map", str(nested_file)],
            capture_output=True, text=True, check=True,
        )
        assert "Project" in result.stdout
        assert "Active Work" in result.stdout
        # Map output includes line counts
        assert "lines" in result.stdout.lower() or any(c.isdigit() for c in result.stdout)

    def test_map_with_path(self, nested_file):
        """Map with --path narrows to subtree."""
        result = subprocess.run(
            [*MD_TOOLS, "map", str(nested_file), "--path", "Active Work"],
            capture_output=True, text=True, check=True,
        )
        assert "TODO: First Item" in result.stdout
        # Should NOT contain sibling section
        assert "Key Decisions" not in result.stdout

    def test_list_paths(self, nested_file):
        """list-paths outputs all valid :/:-separated paths."""
        result = subprocess.run(
            [*MD_TOOLS, "list-paths", str(nested_file)],
            capture_output=True, text=True, check=True,
        )
        assert "Project:/:Active Work" in result.stdout
        assert "Project:/:Key Decisions" in result.stdout
        assert "TODO: First Item" in result.stdout


class TestCLIExtract:

    def test_extract(self, nested_file, tmp_path):
        """Extract removes section from source and writes to output."""
        output = tmp_path / "extracted.md"
        subprocess.run(
            [*MD_TOOLS, "extract", str(nested_file), "Key Decisions", str(output)],
            check=True,
        )
        # Section should be in output file
        assert output.exists()
        ext_tree = MarkdownTree()
        ext_tree.parse(output.read_text())
        assert any(c.title == "Key Decisions" for c in ext_tree.root.children)
        # Section should be removed from source
        src_tree = MarkdownTree()
        src_tree.parse(nested_file.read_text())
        assert src_tree.find_node_by_path("Project:/:Key Decisions") is None


class TestCLIMove:

    def test_move_same_file_reorder(self, nested_file):
        """Move within same file reorders sections."""
        subprocess.run(
            [*MD_TOOLS, "move", str(nested_file), "TODO: Third Item",
             "--parent", "Active Work", "--after-sibling", "^"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(nested_file.read_text())
        active = tree.find_node_by_path("Project:/:Active Work")
        assert active.children[0].title == "TODO: Third Item"

    def test_move_cross_file(self, nested_file, simple_file):
        """Move section from one file to another."""
        subprocess.run(
            [*MD_TOOLS, "move", str(nested_file), "Key Decisions",
             "--target", str(simple_file), "--parent", "Root"],
            check=True,
        )
        # Section should be in target
        target_tree = MarkdownTree()
        target_tree.parse(simple_file.read_text())
        assert target_tree.find_node_by_path("Root:/:Key Decisions") is not None
        # Section should be removed from source
        src_tree = MarkdownTree()
        src_tree.parse(nested_file.read_text())
        assert src_tree.find_node_by_path("Project:/:Key Decisions") is None

    def test_move_same_file_fuzzy_parent_no_dataloss(self, nested_file):
        """Regression (DATA LOSS): a same-file move with a NON-EXACT (prefix) parent
        path must RELOCATE the section, never delete it. The bug: move passed the
        unresolved parent string to attach_subtree (exact-match → fail) AFTER already
        removing the source, then wrote the file → silent deletion, exit 0. The two
        pre-existing move tests used exact top-level parents, so they never caught it."""
        result = subprocess.run(
            [*MD_TOOLS, "move", str(nested_file), "TODO: Second",  # fuzzy source (prefix)
             "--parent", "Key Dec"],                              # fuzzy parent (prefix)
            capture_output=True, text=True,
        )
        text = nested_file.read_text()
        assert text.count("TODO: Second Item") == 1, "section was deleted, not moved"
        tree = MarkdownTree()
        tree.parse(text)
        assert tree.find_node_by_path("Project:/:Key Decisions:/:TODO: Second Item") is not None
        assert tree.find_node_by_path("Project:/:Active Work:/:TODO: Second Item") is None
        assert result.returncode == 0

    def test_move_nothing_moved_leaves_file_unchanged(self, nested_file):
        """Regression: when nothing is successfully moved, move must NOT write the file
        (moved_count==0 guard) and must report failure — so a partial/destructive state
        can never be persisted."""
        original = nested_file.read_text()
        result = subprocess.run(
            [*MD_TOOLS, "move", str(nested_file), "No Such Section", "--parent", "Key Decisions"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert nested_file.read_text() == original


class TestCLIDelete:

    def test_delete(self, simple_file):
        subprocess.run(
            [*MD_TOOLS, "delete", str(simple_file), "Section B"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        root = tree.root.children[0]
        titles = [c.title for c in root.children]
        assert "Section B" not in titles
        assert len(titles) == 2


class TestCLICopy:

    def test_copy(self, nested_file, tmp_path):
        output = tmp_path / "copied.md"
        subprocess.run(
            [*MD_TOOLS, "copy", str(nested_file), "Key Decisions", str(output)],
            check=True,
        )
        assert output.exists()
        tree = MarkdownTree()
        tree.parse(output.read_text())
        assert any(c.title == "Key Decisions" for c in tree.root.children)
        # Original should be unchanged
        orig = MarkdownTree()
        orig.parse(nested_file.read_text())
        assert orig.find_node_by_path("Project:/:Key Decisions") is not None


class TestCLIReshapeStrip:

    def test_reshape_strip_all_body_text(self, nested_file):
        """reshape --strip-all-body-text strips a section's bodies in place,
        preserving heading structure (the in-place heading-skeleton op)."""
        subprocess.run(
            [*MD_TOOLS, "reshape", str(nested_file), "Active Work", "--strip-all-body-text"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(nested_file.read_text())
        active = tree.find_node_by_path("Project:/:Active Work")
        # Headings still exist
        assert len(active.children) == 3
        assert active.children[0].title == "TODO: First Item"
        # Content stripped
        output = tree.dump()
        assert "Description of first" not in output
        assert "Description of second" not in output


class TestCLIReorder:

    def test_reorder(self, nested_file):
        """Reorder moves specified sections to top, rest retain order."""
        subprocess.run(
            [*MD_TOOLS, "reorder", str(nested_file),
             "TODO: Third Item:,:TODO: First Item",
             "--parent", "Active Work"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(nested_file.read_text())
        active = tree.find_node_by_path("Project:/:Active Work")
        titles = [c.title for c in active.children]
        # Third and First moved to top (in specified order), Second stays
        assert titles == ["TODO: Third Item", "TODO: First Item", "TODO: Second Item"]


class TestSubstEmptySearchRefused:
    """An empty search string matches every line boundary — subst/gsub must refuse.

    Regression for a live incident: a caller built its anchor from a failed command
    substitution, the variable came back empty, and `subst` reported 135 successful
    substitutions while turning a 21-bullet index into 156 bullets.
    """

    def _fixture(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Doc\n\n- alpha\n- beta\n- gamma\n")
        return f

    def test_subst_empty_old_exits_nonzero(self, tmp_path):
        f = self._fixture(tmp_path)
        r = subprocess.run([*MD_TOOLS, "subst", str(f), "", "INJECTED"],
                           capture_output=True, text=True)
        assert r.returncode != 0, "empty search string must exit non-zero"

    def test_subst_empty_old_writes_nothing(self, tmp_path):
        f = self._fixture(tmp_path)
        before = f.read_text()
        subprocess.run([*MD_TOOLS, "subst", str(f), "", "INJECTED"],
                       capture_output=True, text=True)
        assert f.read_text() == before, "refused call must not modify the file"
        assert "INJECTED" not in f.read_text()

    def test_gsub_empty_pattern_refused(self, tmp_path):
        f = self._fixture(tmp_path)
        before = f.read_text()
        r = subprocess.run([*MD_TOOLS, "gsub", str(f), "", "INJECTED"],
                           capture_output=True, text=True)
        assert r.returncode != 0
        assert f.read_text() == before

    def test_dry_run_also_refused(self, tmp_path):
        """The dry-run path bypasses the lock, so it needs the guard too."""
        f = self._fixture(tmp_path)
        r = subprocess.run([*MD_TOOLS, "subst", str(f), "", "INJECTED", "--dry-run"],
                           capture_output=True, text=True)
        assert r.returncode != 0

    def test_empty_replacement_still_allowed(self, tmp_path):
        """Deleting text is legitimate — only the SEARCH side is guarded."""
        f = self._fixture(tmp_path)
        r = subprocess.run([*MD_TOOLS, "subst", str(f), "beta", ""],
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert "beta" not in f.read_text()
        assert "alpha" in f.read_text()


class TestReorderMarkerTransparency:
    """reorder resolves sibling names marker-transparently, like every other verb, and
    reports a zero-match run as a failure instead of printing a check-mark over a no-op."""

    @pytest.fixture
    def tagged_file(self, tmp_path):
        f = tmp_path / "tagged.md"
        f.write_text(
            "# T\n\n## Threads\n\n"
            "### Alpha thread  [implement] [v1]\n\na\n\n"
            "### Beta thread  [plan] [v2]\n\nb\n\n"
            "### Gamma thread  [queued]\n\nc\n"
        )
        return f

    def _titles(self, f):
        tree = MarkdownTree()
        tree.parse(f.read_text())
        return [c.title for c in tree.find_node_by_path("T:/:Threads").children]

    def test_reorder_without_state_tags(self, tagged_file):
        """Naming a section WITHOUT its ' [state] [v-tier]' zone resolves it.

        Regression: the matcher used raw `child.title == name`, so every canonical
        STATUS.md heading missed, and the run reported success having done nothing.
        """
        r = subprocess.run(
            [*MD_TOOLS, "reorder", str(tagged_file),
             "Gamma thread:,:Alpha thread:,:Beta thread", "--parent", "Threads"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert self._titles(tagged_file) == [
            "Gamma thread  [queued]",
            "Alpha thread  [implement] [v1]",
            "Beta thread  [plan] [v2]",
        ]

    def test_reorder_exact_titles_still_work(self, tagged_file):
        """The full-title path that was previously the ONLY working form must not break."""
        r = subprocess.run(
            [*MD_TOOLS, "reorder", str(tagged_file),
             "Gamma thread  [queued]:,:Alpha thread  [implement] [v1]",
             "--parent", "Threads"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert self._titles(tagged_file)[0] == "Gamma thread  [queued]"

    def test_reorder_zero_matches_exits_nonzero(self, tagged_file):
        """A reorder that matches nothing FAILS — a caller must be able to detect it."""
        before = self._titles(tagged_file)
        r = subprocess.run(
            [*MD_TOOLS, "reorder", str(tagged_file), "Nope one:,:Nope two",
             "--parent", "Threads"],
            capture_output=True, text=True,
        )
        assert r.returncode != 0
        assert "no sections matched" in r.stderr
        assert self._titles(tagged_file) == before  # file untouched

    def test_reorder_partial_match_reports_skipped(self, tagged_file):
        """A partial match still reorders, but the summary must SAY some name missed."""
        r = subprocess.run(
            [*MD_TOOLS, "reorder", str(tagged_file), "Gamma thread:,:Nonexistent",
             "--parent", "Threads"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert "not found" in r.stdout
        assert self._titles(tagged_file)[0] == "Gamma thread  [queued]"

    def test_reorder_repeated_name_does_not_duplicate(self, tagged_file):
        """Naming one section twice must not consume it twice or drop a sibling."""
        r = subprocess.run(
            [*MD_TOOLS, "reorder", str(tagged_file), "Gamma thread:,:Gamma thread",
             "--parent", "Threads"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        titles = self._titles(tagged_file)
        assert len(titles) == 3
        assert len(set(titles)) == 3

    @pytest.fixture
    def collide_file(self, tmp_path):
        """Two siblings differing ONLY by marker — they share a _title_key."""
        f = tmp_path / "collide.md"
        f.write_text(
            "# T\n\n## Threads\n\n"
            "### Foo  [ ]\n\npending\n\n"
            "### Bar  [queued]\n\nbar\n\n"
            "### Foo  [x]\n\ndone\n"
        )
        return f

    def _ctitles(self, f):
        tree = MarkdownTree()
        tree.parse(f.read_text())
        return [c.title for c in tree.find_node_by_path("T:/:Threads").children]

    def test_reorder_ambiguous_name_refuses(self, collide_file):
        """Marker-transparent matching must REFUSE an ambiguous name, not silently take
        the first — the resolver contract is 'unique wins; ambiguity refuses'. Taking
        the first would reorder a section the caller did not name."""
        before = self._ctitles(collide_file)
        r = subprocess.run(
            [*MD_TOOLS, "reorder", str(collide_file), "Foo", "--parent", "Threads"],
            capture_output=True, text=True,
        )
        assert r.returncode != 0
        assert "Ambiguous" in r.stderr
        assert self._ctitles(collide_file) == before  # file untouched

    def test_reorder_exact_heading_disambiguates(self, collide_file):
        """Passing the full heading including its marker zone resolves the collision."""
        r = subprocess.run(
            [*MD_TOOLS, "reorder", str(collide_file), "Foo  [x]", "--parent", "Threads"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert self._ctitles(collide_file)[0] == "Foo  [x]"

    def test_reorder_unambiguous_sibling_unaffected_by_collision(self, collide_file):
        """A non-colliding name still resolves marker-transparently in the same file."""
        r = subprocess.run(
            [*MD_TOOLS, "reorder", str(collide_file), "Bar", "--parent", "Threads"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert self._ctitles(collide_file)[0] == "Bar  [queued]"

    def test_reorder_preserves_bodies(self, tagged_file):
        """Reordering must not lose any section's body."""
        subprocess.run(
            [*MD_TOOLS, "reorder", str(tagged_file), "Gamma thread", "--parent", "Threads"],
            check=True, capture_output=True,
        )
        text = tagged_file.read_text()
        for body in ("a", "b", "c"):
            assert f"\n{body}\n" in text


class TestCopyThenReshape:

    def test_copy_then_reshape_keeps_full_in_output_strips_source(self, nested_file, tmp_path):
        """copy (full) + reshape --strip-all-body-text reproduces the extract-to-file-
        keep-breadcrumbs-in-source workflow."""
        output = tmp_path / "extracted.md"
        subprocess.run(
            [*MD_TOOLS, "copy", str(nested_file), "Active Work", str(output)], check=True)
        subprocess.run(
            [*MD_TOOLS, "reshape", str(nested_file), "Active Work", "--strip-all-body-text"],
            check=True)
        # Output has full content
        ext_tree = MarkdownTree()
        ext_tree.parse(output.read_text())
        assert "Description of first" in ext_tree.dump()
        # Source has headings but no content
        src_tree = MarkdownTree()
        src_tree.parse(nested_file.read_text())
        active = src_tree.find_node_by_path("Project:/:Active Work")
        assert active is not None
        assert len(active.children) == 3  # headings preserved
        assert "Description of first" not in src_tree.dump()


class TestCLIConvertBold:
    """convert --from bold: **Title:** lines -> child headings (whole-file or section)."""

    def test_convert_bold_whole_file(self, tmp_path):
        """Converts **Bold:** lines to markdown headings (whole file)."""
        f = tmp_path / "bold.md"
        f.write_text(textwrap.dedent("""\
            # Root

            ## Settings

            **Option A:** First option.

            **Option B:** Second option.
        """))
        subprocess.run([*MD_TOOLS, "convert", str(f), "--from", "bold"], check=True)
        tree = MarkdownTree()
        tree.parse(f.read_text())
        settings = tree.find_node_by_path("Root:/:Settings")
        child_titles = [c.title for c in settings.children]
        assert "Option A" in child_titles
        assert "Option B" in child_titles

    def test_bold_fence_aware(self, tmp_path):
        """A **Bold:** line inside a ``` code fence is body, not a header."""
        f = tmp_path / "bold_fence.md"
        f.write_text(textwrap.dedent("""\
            # Root

            ## Settings

            **Real:** promoted.

            ```
            **Fenced:** not a header.
            ```
        """))
        subprocess.run([*MD_TOOLS, "convert", str(f), "--from", "bold"], check=True)
        tree = MarkdownTree()
        tree.parse(f.read_text())
        settings = tree.find_node_by_path("Root:/:Settings")
        child_titles = [c.title for c in settings.children]
        assert "Real" in child_titles
        assert "Fenced" not in child_titles   # inside the fence -> left alone

    def test_bold_section_scoped(self, tmp_path):
        """convert FILE SECTION --from bold only processes that subtree."""
        f = tmp_path / "bold_scoped.md"
        f.write_text(textwrap.dedent("""\
            # Root

            ## Alpha

            **A1:** in alpha.

            ## Beta

            **B1:** in beta.
        """))
        subprocess.run([*MD_TOOLS, "convert", str(f), "Root:/:Alpha", "--from", "bold"], check=True)
        tree = MarkdownTree()
        tree.parse(f.read_text())
        alpha = tree.find_node_by_path("Root:/:Alpha")
        beta = tree.find_node_by_path("Root:/:Beta")
        assert "A1" in [c.title for c in alpha.children]        # promoted
        assert "B1" not in [c.title for c in beta.children]     # untouched
        assert "**B1:**" in "\n".join(beta.content)


class TestCLICleanupBackups:

    def test_cleanup_backups(self, tmp_path):
        """Cleanup keeps most recent backup per file, removes older."""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        # Create two backups for same file (different timestamps)
        (backup_dir / "test.backup_20260101_120000.md").write_text("old")
        (backup_dir / "test.backup_20260102_120000.md").write_text("new")
        # Create one backup for a different file
        (backup_dir / "other.backup_20260101_120000.md").write_text("only")
        subprocess.run(
            [*MD_TOOLS, "cleanup-backups", str(backup_dir)],
            check=True,
        )
        remaining = sorted(f.name for f in backup_dir.iterdir())
        # Should keep newest of "test" and the only "other"
        assert "test.backup_20260102_120000.md" in remaining
        assert "test.backup_20260101_120000.md" not in remaining
        assert "other.backup_20260101_120000.md" in remaining


# ============================================================================
# 5. Replace helpers + subtree-replace regressions
#    (replace had NO CLI coverage — the gap behind the verbatim-header footgun)
# ============================================================================

class TestReplaceHelpers:

    def test_split_head_and_headers(self):
        head, rest = _mod._split_at_first_unfenced_header(
            "leading body\n\n### Child\n\nchild body")
        assert head == "leading body"
        assert rest.startswith("### Child")

    def test_split_no_header(self):
        head, rest = _mod._split_at_first_unfenced_header("just body, no headers")
        assert head == "just body, no headers"
        assert rest == ""

    def test_split_fenced_header_is_not_a_split_point(self):
        text = "body\n\n```\n### Not Real\n```\n"
        head, rest = _mod._split_at_first_unfenced_header(text)
        assert rest == ""                       # fenced header is not a real header
        assert head == text                     # no unfenced header -> text returned unchanged

    def test_dedent_headers_equal_level_siblings(self):
        # Two level-3 siblings -> dedented to level 1 so the parser sees them as siblings
        assert _mod._dedent_headers("### A\n\n### B\n") == "# A\n\n# B\n"

    def test_dedent_headers_preserves_relative_depth(self):
        assert _mod._dedent_headers("### Parent\n\n#### Child\n") == "# Parent\n\n## Child\n"


class TestCLIReplace:

    def test_replace_body_only_preserves_children(self, nested_file):
        """Default replace with a plain body keeps subsections (Case A)."""
        subprocess.run(
            [*MD_TOOLS, "replace", str(nested_file), "Active Work", "Fresh body."],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(nested_file.read_text())
        active = tree.find_node_by_path("Project:/:Active Work")
        titles = [c.title for c in active.children]
        assert titles == ["TODO: First Item", "TODO: Second Item", "TODO: Third Item"]

    def test_replace_default_merges_headers(self, nested_file):
        """Default replace MERGES headers in the body: a re-typed child updates in place
        (no dup), un-named children are kept, and the leading body replaces the body."""
        subprocess.run(
            [*MD_TOOLS, "replace", str(nested_file), "Active Work",
             "New lead body.\n\n### TODO: First Item\n\nrewritten first"],
            check=True,
        )
        text = nested_file.read_text()
        tree = MarkdownTree()
        tree.parse(text)
        active = tree.find_node_by_path("Project:/:Active Work")
        titles = [c.title for c in active.children]
        assert titles == ["TODO: First Item", "TODO: Second Item", "TODO: Third Item"]  # no dup, others kept
        assert "New lead body." in text
        assert "rewritten first" in text

    def test_replace_fenced_header_allowed(self, nested_file):
        """A fenced header in the body is literal, not a section — replace succeeds."""
        subprocess.run(
            [*MD_TOOLS, "replace", str(nested_file), "Active Work",
             "Body with example:\n\n```\n### Not A Section\n```"],
            check=True,
        )
        out = subprocess.run([*MD_TOOLS, "list-paths", str(nested_file)],
                             capture_output=True, text=True, check=True).stdout
        assert "Not A Section" not in out      # stayed literal, never a section

    def test_replace_full_subtree_replaces_children(self, nested_file):
        """--full-subtree replaces body + children WHOLESALE: re-typed children appear
        once (no dup, the Case B fix), the leading body is preserved (parser-drop gotcha),
        and a child NOT in the replacement is DROPPED."""
        subprocess.run(
            [*MD_TOOLS, "replace", str(nested_file), "Active Work",
             "Updated lead body.\n\n"
             "### TODO: First Item\n\nfirst rewritten\n\n"
             "### TODO: Second Item\n\nsecond rewritten",
             "--full-subtree"],
            check=True,
        )
        text = nested_file.read_text()
        tree = MarkdownTree()
        tree.parse(text)
        active = tree.find_node_by_path("Project:/:Active Work")
        titles = [c.title for c in active.children]
        assert titles == ["TODO: First Item", "TODO: Second Item"]  # no dup, Third dropped
        assert "Updated lead body." in text                          # preamble preserved
        assert "first rewritten" in text                             # body updated

    def test_replace_full_subtree_drops_unmentioned(self, nested_file):
        """--full-subtree keeps only the supplied children; un-supplied ones are dropped."""
        subprocess.run(
            [*MD_TOOLS, "replace", str(nested_file), "Active Work",
             "body\n\n### TODO: First Item\n\nkept\n\n### TODO: Fourth Item\n\nnew",
             "--full-subtree"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(nested_file.read_text())
        active = tree.find_node_by_path("Project:/:Active Work")
        titles = [c.title for c in active.children]
        assert titles == ["TODO: First Item", "TODO: Fourth Item"]
        assert "TODO: Second Item" not in titles

    def test_replace_full_subtree_body_only_drops_all_children(self, nested_file):
        """Sharp edge, documented: --full-subtree with a body-only payload (no headers)
        drops ALL children. (Plain replace is the safe body-only edit.)"""
        subprocess.run(
            [*MD_TOOLS, "replace", str(nested_file), "Active Work",
             "only a body, no headers", "--full-subtree"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(nested_file.read_text())
        active = tree.find_node_by_path("Project:/:Active Work")
        assert active.children == []
        assert "only a body, no headers" in nested_file.read_text()


# ============================================================================
# YAML frontmatter passthrough + round-trip fidelity
# ============================================================================

# Frontmatter with the quirks that previously broke md_tools: a YAML comment that
# looks like an H1 heading, comma-bearing quoted values, and nested keys.
FM_DOC = (
    "---\n"
    "name: test-skill\n"
    'description: "quirky: value, with comma"\n'
    "# a comment that looks like an H1 heading\n"
    "nested:\n"
    "  key: val\n"
    "---\n"
    "\n"
    "# Test Skill\n"
    "\n"
    "## Section A\n"
    "\n"
    "Content A.\n"
    "\n"
    "## Section B\n"
    "\n"
    "Content B.\n"
)

_fm_split = _mod._frontmatter_split


def _fm_region(text):
    """The opaque frontmatter prefix of a document (for byte-identity assertions)."""
    return _fm_split(text)[0]


@pytest.fixture
def fm_file(tmp_path):
    f = tmp_path / "skill.md"
    f.write_text(FM_DOC)
    return f


class TestFrontmatter:
    """Frontmatter is held off-tree as an opaque, byte-verbatim prefix."""

    def test_split_basic(self):
        raw, rest = _fm_split(FM_DOC)
        assert raw.startswith("---\n") and raw.rstrip("\n").endswith("---")
        assert "name: test-skill" in raw
        assert rest.startswith("# Test Skill")          # blank run absorbed into raw

    def test_split_none_when_absent(self):
        assert _fm_split("# Heading\n\nbody\n") == ("", "# Heading\n\nbody\n")

    def test_split_unclosed_fence_is_not_frontmatter(self):
        t = "---\nname: x\n# H\n\nb\n"                   # no closing fence
        assert _fm_split(t) == ("", t)

    def test_roundtrip_byte_identical(self):
        tree = MarkdownTree(); tree.parse(FM_DOC)
        assert tree.dump() == FM_DOC

    def test_h1_lookalike_comment_not_a_heading(self):
        """A `# comment` inside YAML must never become an addressable section."""
        tree = MarkdownTree(); tree.parse(FM_DOC)
        titles = [c.title for c in tree.root.children[0].children]
        assert "a comment that looks like an H1 heading" not in titles
        assert tree.root.children[0].title == "Test Skill"

    def test_h1_lookalike_absent_from_list_cli(self, fm_file):
        out = subprocess.run([*MD_TOOLS, "list", str(fm_file)],
                             capture_output=True, text=True, check=True).stdout
        assert "comment that looks like an H1" not in out

    def test_empty_frontmatter_roundtrips(self):
        t = "---\n---\n\n# T\n\nb\n"
        tree = MarkdownTree(); tree.parse(t)
        assert tree.dump() == t

    def test_bom_preserved(self):
        t = "﻿---\nname: x\n---\n\n# T\n\nb\n"
        tree = MarkdownTree(); tree.parse(t)
        assert tree.dump() == t

    # --- per-verb: the frontmatter region survives body mutations byte-identical ---

    def test_insert_preserves_frontmatter(self, fm_file):
        before = _fm_region(fm_file.read_text())
        subprocess.run([*MD_TOOLS, "insert", str(fm_file), "Test Skill",
                        "# Section C\n\nNew."], check=True)
        assert _fm_region(fm_file.read_text()) == before

    def test_replace_preserves_frontmatter(self, fm_file):
        before = _fm_region(fm_file.read_text())
        subprocess.run([*MD_TOOLS, "replace", str(fm_file), "Test Skill:/:Section A",
                        "Rewritten body."], check=True)
        assert _fm_region(fm_file.read_text()) == before

    def test_delete_preserves_frontmatter(self, fm_file):
        before = _fm_region(fm_file.read_text())
        subprocess.run([*MD_TOOLS, "delete", str(fm_file), "Test Skill:/:Section B"],
                       check=True)
        assert _fm_region(fm_file.read_text()) == before

    def test_move_reorder_preserves_frontmatter(self, fm_file):
        before = _fm_region(fm_file.read_text())
        subprocess.run([*MD_TOOLS, "move", str(fm_file), "Test Skill:/:Section B",
                        "--parent", "Test Skill", "--after-sibling", "^"], check=True)
        assert _fm_region(fm_file.read_text()) == before

    def test_reshape_preserves_frontmatter(self, fm_file):
        before = _fm_region(fm_file.read_text())
        subprocess.run([*MD_TOOLS, "reshape", str(fm_file), "Test Skill",
                        "--strip-all-body-text"], check=True)
        assert _fm_region(fm_file.read_text()) == before

    # --- FILE-BOUND invariant: frontmatter never travels with a moved section ---

    def test_extract_output_has_no_frontmatter(self, fm_file, tmp_path):
        out = tmp_path / "extracted.md"
        subprocess.run([*MD_TOOLS, "extract", str(fm_file), "Test Skill:/:Section A",
                        str(out)], check=True)
        assert _fm_region(out.read_text()) == ""        # target does NOT inherit source FM
        assert "Content A." in out.read_text()

    def test_copy_output_has_no_frontmatter(self, fm_file, tmp_path):
        out = tmp_path / "copied.md"
        subprocess.run([*MD_TOOLS, "copy", str(fm_file), "Test Skill:/:Section A",
                        str(out)], check=True)
        assert _fm_region(out.read_text()) == ""

    def test_move_cross_file_is_file_bound(self, tmp_path):
        """Source keeps its frontmatter; target keeps ITS OWN and does not inherit."""
        src = tmp_path / "src.md"; src.write_text(FM_DOC)
        tgt = tmp_path / "tgt.md"
        tgt.write_text("---\nname: target-doc\n---\n\n# Target\n\n## Existing\n\nx.\n")
        tgt_fm_before = _fm_region(tgt.read_text())
        subprocess.run([*MD_TOOLS, "move", str(src), "Test Skill:/:Section B",
                        "--target", str(tgt), "--parent", "Target"], check=True)
        assert _fm_region(src.read_text()) == _fm_region(FM_DOC)     # source FM intact
        assert _fm_region(tgt.read_text()) == tgt_fm_before          # target FM intact
        assert "name: test-skill" not in _fm_region(tgt.read_text()) # no source-FM bleed
        assert "Content B." in tgt.read_text()                       # section did move


class TestRoundTripFidelity:
    """parse->dump preserves content (no data loss): preamble + trailing newline.
    Exact inter-block blank-line SPACING is explicitly out of scope (cosmetic)."""

    def test_preamble_before_first_heading_preserved(self):
        """Prose before the first heading was previously DROPPED (data loss)."""
        tree = MarkdownTree(); tree.parse("intro paragraph\n\n# Title\n\nbody\n")
        assert "intro paragraph" in tree.root.content
        assert tree.dump() == "intro paragraph\n\n# Title\n\nbody\n"

    def test_unclosed_fence_content_preserved(self):
        """Unclosed leading `---` is body; its lines must survive (spacing may reflow)."""
        out = MarkdownTree_dump("---\nname: x\n# H\n\nbody\n")
        assert "---" in out and "name: x" in out and "# H" in out and "body" in out

    def test_trailing_newline_preserved(self):
        tree = MarkdownTree(); tree.parse("# T\n\nbody\n")
        assert tree.dump() == "# T\n\nbody\n"

    def test_no_trailing_newline_preserved(self):
        tree = MarkdownTree(); tree.parse("# T\n\nbody")
        assert tree.dump() == "# T\n\nbody"

    def test_multiple_trailing_newlines_preserved(self):
        tree = MarkdownTree(); tree.parse("# T\n\nbody\n\n")
        assert tree.dump() == "# T\n\nbody\n\n"

    def test_crlf_frontmatter_preserved_body_content_survives(self):
        """Tested contract (D15): the frontmatter region's CRLF is byte-PRESERVED.
        Body line-endings are pre-existing/unspecified under Option 1 — md_tools may
        rewrite them (partial CR residue), but no body CONTENT is lost. The fix
        guarantees frontmatter fidelity, NOT whole-file byte-identity on CRLF input."""
        t = "---\r\nname: x\r\n---\r\n\r\n# T\r\n\r\nbody\r\n"
        raw = _fm_region(t)
        tree = MarkdownTree(); tree.parse(t)
        out = tree.dump()
        assert _fm_region(out) == raw                   # frontmatter CRLF byte-preserved
        assert "name: x" in out and "# T" in out and "body" in out  # no body lost

    def test_lead_rule_pair_heading_swallowed_but_verbatim(self):
        """Documented behavior (D14, shared with the mdsync reference impl): a leading
        `---`/heading/`---` makes the enclosed region opaque — the enclosed heading
        round-trips VERBATIM but is unaddressable. No data loss."""
        t = "---\n# Real Heading\n---\n# Title\n\nbody\n"
        tree = MarkdownTree(); tree.parse(t)
        assert tree.dump() == t                          # verbatim
        titles = [c.title for c in tree.root.children]
        assert "Real Heading" not in titles              # enclosed heading unaddressable
        assert titles == ["Title"]

    def test_real_files_round_trip_byte_identical(self):
        repo = Path(__file__).resolve().parent.parent
        for rel in ["README.md", "docs/md_tools_SKILL.md", "docs/md_tools_USAGE.md",
                    "tests/fixtures/frontmatter_skill.md"]:
            src = (repo / rel).read_text(encoding="utf-8")
            tree = MarkdownTree(); tree.parse(src)
            assert tree.dump() == src, f"{rel} not byte-identical"

    def test_real_file_no_content_lost(self):
        """A file with runs of blank lines is reflowed on dump (the one cosmetic
        residual); assert NO content is lost even though it is not byte-identical."""
        repo = Path(__file__).resolve().parent.parent
        src = (repo / "tests/fixtures/blank_runs.md").read_text(encoding="utf-8")
        tree = MarkdownTree(); tree.parse(src)
        out = tree.dump()
        # every non-blank source line survives (order preserved)
        src_lines = [l for l in src.splitlines() if l.strip()]
        out_lines = [l for l in out.splitlines() if l.strip()]
        assert src_lines == out_lines


def MarkdownTree_dump(text):
    tree = MarkdownTree(); tree.parse(text); return tree.dump()


class TestCLIConvertBullets:
    """convert (default --from bullets): a section's top-level `- ` bullets -> child
    headings, split heading|body at --body-marker (default '\\n')."""

    LOG = ("# Doc\n\n## Log\n\nIntro line.\n\n"
           "- 2026-06-08 14:18  projA  thread one  summary one\n"
           "- 2026-06-07 09:00  projB  thread two  summary two\n")

    def test_default_marker_whole_line_heading(self, tmp_path):
        """Default body-marker '\\n': a one-line bullet becomes the whole heading (no body)."""
        f = tmp_path / "log.md"; f.write_text(self.LOG)
        subprocess.run([*MD_TOOLS, "convert", str(f), "Doc:/:Log"], check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        log = tree.find_node_by_path("Doc:/:Log")
        assert [c.title for c in log.children] == [
            "2026-06-08 14:18  projA  thread one  summary one",
            "2026-06-07 09:00  projB  thread two  summary two"]
        assert not log.children[0].content                # whole line is the heading, no body
        assert "Intro line." in "\n".join(log.content)    # intro preserved

    def test_multiline_bullet_continuation_is_body(self, tmp_path):
        f = tmp_path / "ml.md"
        f.write_text("# Doc\n\n## Log\n\n- First item\n  continuation a\n  continuation b\n- Second item\n")
        subprocess.run([*MD_TOOLS, "convert", str(f), "Doc:/:Log"], check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        log = tree.find_node_by_path("Doc:/:Log")
        assert [c.title for c in log.children] == ["First item", "Second item"]
        assert "continuation a" in "\n".join(log.children[0].content)

    def test_explicit_body_marker_split(self, tmp_path):
        """--body-marker splits heading|body at the first occurrence."""
        f = tmp_path / "bm.md"
        f.write_text("# Doc\n\n## Log\n\n- Title One :: body one\n- Title Two :: body two\n")
        subprocess.run([*MD_TOOLS, "convert", str(f), "Doc:/:Log", "--body-marker", " :: "], check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        log = tree.find_node_by_path("Doc:/:Log")
        assert [c.title for c in log.children] == ["Title One", "Title Two"]
        assert "body one" in "\n".join(log.children[0].content)

    def test_checkbox_to_trailing(self, tmp_path):
        """--checkbox-to-trailing relocates a task-list checkbox to the canonical trailing tag."""
        f = tmp_path / "cb.md"
        f.write_text("# Doc\n\n## Tasks\n\n- [ ] Do the thing\n- [x] Done thing\n")
        subprocess.run([*MD_TOOLS, "convert", str(f), "Doc:/:Tasks", "--checkbox-to-trailing"], check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        tasks = tree.find_node_by_path("Doc:/:Tasks")
        assert [c.title for c in tasks.children] == ["Do the thing  [ ]", "Done thing  [x]"]

    def test_level_override(self, tmp_path):
        f = tmp_path / "lvl.md"; f.write_text(self.LOG)
        subprocess.run([*MD_TOOLS, "convert", str(f), "Doc:/:Log", "--level", "4"], check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        log = tree.find_node_by_path("Doc:/:Log")
        assert log.children and all(c.level == 4 for c in log.children)

    def test_level_skip_under_h1_parses_as_siblings(self, tmp_path):
        # Bullets directly under the H1 forced to a SKIPPED level (1 -> 3) must parse as
        # SIBLINGS, not left-nested — the skipped-outline-level parse fix (was a documented
        # convert-bullets Gotcha before that fix landed).
        f = tmp_path / "h1.md"; f.write_text("# Root\n\n- alpha\n- beta\n- gamma\n")
        subprocess.run([*MD_TOOLS, "convert", str(f), "Root", "--level", "3"], check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        root = tree.find_node_by_path("Root")
        assert [c.title for c in root.children] == ["alpha", "beta", "gamma"]
        assert all(c.level == 3 for c in root.children)

    def test_bullets_requires_section(self, tmp_path):
        """bullets mode refuses whole-file (no SECTION) by design."""
        f = tmp_path / "ns.md"; f.write_text(self.LOG); before = f.read_text()
        r = subprocess.run([*MD_TOOLS, "convert", str(f)], capture_output=True, text=True)
        assert r.returncode != 0
        assert f.read_text() == before
        assert "requires a SECTION" in r.stderr

    def test_dry_run_does_not_write(self, tmp_path):
        f = tmp_path / "log.md"; f.write_text(self.LOG); before = f.read_text()
        r = subprocess.run([*MD_TOOLS, "convert", str(f), "Doc:/:Log", "--dry-run"],
                           capture_output=True, text=True)
        assert f.read_text() == before
        assert "2026-06-08 14:18  projA  thread one  summary one" in r.stdout


# ============================================================================
# 5. Write-hardening: atomic writes, flock serialization, and the new verbs
# ============================================================================

import concurrent.futures


class TestAtomicWrite:

    def test_writes_content_and_leaves_no_temp(self, tmp_path):
        f = tmp_path / "a.md"
        _mod.atomic_write(str(f), "# Hello\n\nbody\n")
        assert f.read_text() == "# Hello\n\nbody\n"
        # The temp file is created in the same dir and renamed away — no residue.
        assert [p.name for p in tmp_path.iterdir()] == ["a.md"]

    def test_overwrite_is_clean_not_torn(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("old contents, deliberately longer than the replacement\n")
        _mod.atomic_write(str(f), "new\n")
        assert f.read_text() == "new\n"  # fully replaced, not appended/truncated-in-place


class TestFileLock:

    def test_lock_target_is_the_parent_directory(self, tmp_path):
        f = tmp_path / "x.md"; f.write_text("# x\n")
        # We flock the data file's parent directory, not a lock file.
        assert _mod._lock_dir_for(str(f)) == str(tmp_path)

    def test_locked_write_creates_no_lock_file(self, tmp_path):
        f = tmp_path / "x.md"; f.write_text("# Doc\n\n## A\n\nbody\n")
        subprocess.run([*MD_TOOLS, "item-append", str(f), "A", "- added"], check=True)
        # directory-flock leaves no .lock artifact behind in the edited dir
        assert sorted(p.name for p in tmp_path.iterdir()) == ["x.md"]

    def test_locking_opt_out_via_env(self, tmp_path):
        """The opt-out / OS-dependent seam: MD_TOOLS_LOCK=0 makes locking a no-op,
        but atomic writes still apply so the op succeeds normally."""
        import os as _os
        f = tmp_path / "x.md"; f.write_text("# Doc\n\n## A\n\nbody\n")
        env = dict(_os.environ, MD_TOOLS_LOCK="0")
        subprocess.run([*MD_TOOLS, "item-append", str(f), "A", "- added"], env=env, check=True)
        assert "- added" in f.read_text()

    def test_context_manager_acquires_and_releases(self, tmp_path):
        f = tmp_path / "x.md"; f.write_text("# x\n")
        with _mod.file_lock(str(f)):
            pass  # acquire + release with no error
        with _mod.file_lock(str(f)):  # re-acquirable after release
            pass

    def test_concurrent_item_append_no_lost_updates(self, tmp_path):
        """The silent-loss regression this whole thread targets: N concurrent
        read-modify-write appends to the SAME section must ALL land. The flock
        serializes them; without it, racers read the same base tree and clobber
        each other's appends."""
        f = tmp_path / "race.md"
        f.write_text("# Doc\n\n## Log\n\nstart\n")
        N = 12

        def worker(k):
            return subprocess.run(
                [*MD_TOOLS, "item-append", str(f), "Log", f"- item-{k:02d}"],
                capture_output=True, text=True).returncode

        with concurrent.futures.ThreadPoolExecutor(max_workers=N) as ex:
            rcs = list(ex.map(worker, range(N)))
        assert all(rc == 0 for rc in rcs)
        text = f.read_text()
        for k in range(N):
            assert f"- item-{k:02d}" in text, f"lost append item-{k:02d}"


class TestComposerReentrancy:

    def test_extract_holds_two_locks_without_deadlock(self, tmp_path):
        """extract locks BOTH files and calls the *_bare workers directly; a wrapped
        sub-verb would re-acquire LOCK_EX on the source and self-deadlock."""
        src = tmp_path / "src.md"; src.write_text(SIMPLE_DOC)
        out = tmp_path / "out.md"
        r = subprocess.run([*MD_TOOLS, "extract", str(src), "Section A", str(out)], timeout=20)
        assert r.returncode == 0
        assert "Section A" in out.read_text()
        assert "Section A" not in src.read_text()   # removed from source


class TestCLIGsub:
    """gsub = the Python-regex find/replace verb (= subst --regex); positional PATTERN REPL,
    no s/// delimiter. Also covers subst's --regex flag and literal-default contrast."""

    DOC = ("---\ntitle: keep\nfoo: oldval\n---\n# Doc\n\n## Alpha\n\n"
           "old old old\n\n## Beta\n\nold here\n")

    def test_first_per_line_default(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text(self.DOC)
        subprocess.run([*MD_TOOLS, "gsub", str(f), "old", "NEW"], check=True)
        assert "NEW old old" in f.read_text()       # default: only the first on the line

    def test_all_flag(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text(self.DOC)
        subprocess.run([*MD_TOOLS, "gsub", str(f), "old", "NEW", "--all"], check=True)
        assert "NEW NEW NEW" in f.read_text()

    def test_frontmatter_is_opaque(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text(self.DOC)
        subprocess.run([*MD_TOOLS, "gsub", str(f), "old", "NEW", "--all"], check=True)
        assert "foo: oldval" in f.read_text()       # YAML frontmatter untouched

    def test_case_insensitive(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# D\n\nOLD value old\n")
        subprocess.run([*MD_TOOLS, "gsub", str(f), "old", "x", "--all", "--ignore-case"], check=True)
        assert "x value x" in f.read_text()

    def test_section_scope_only_touches_that_subtree(self, tmp_path):
        f = tmp_path / "s.md"
        f.write_text("# Doc\n\n## Alpha\n\nword\n\n## Beta\n\nword\n")
        subprocess.run([*MD_TOOLS, "gsub", str(f), "word", "TERM", "--section", "Beta"], check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        assert "word" in "\n".join(tree.find_node_by_path("Doc:/:Alpha").content)
        assert "TERM" in "\n".join(tree.find_node_by_path("Doc:/:Beta").content)

    def test_dry_run_does_not_write(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text(self.DOC)
        before = f.read_text()
        r = subprocess.run([*MD_TOOLS, "gsub", str(f), "old", "NEW", "--all", "--dry-run"],
                           capture_output=True, text=True)
        assert f.read_text() == before
        assert "NEW" in r.stdout

    # --- gsub IS the regex tool (wildcards + backreferences); no s/// delimiter to collide ---

    def test_slashes_are_literal_in_pattern(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# D\n\na/b/c path\n")
        subprocess.run([*MD_TOOLS, "gsub", str(f), "a/b/c", "X"], check=True)
        assert "X path" in f.read_text()            # positional: no s/// delimiter to escape

    def test_regex_alternation(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# D\n\na x b x c\n")
        subprocess.run([*MD_TOOLS, "gsub", str(f), "a|b", "Z", "--all"], check=True)
        assert "Z x Z x c" in f.read_text()         # alternation is live (regex)

    def test_backreferences(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# D\n\nfoo=1 bar=2\n")
        subprocess.run([*MD_TOOLS, "gsub", str(f), r"(\w+)=(\d)", r"\2:\1", "--all"], check=True)
        assert "1:foo 2:bar" in f.read_text()

    # --- subst --regex is the same engine; subst (default) stays literal ---

    def test_subst_regex_flag_equals_gsub(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# D\n\nfoo=1\n")
        subprocess.run([*MD_TOOLS, "subst", str(f), r"(\w+)=(\d)", r"\2:\1", "--regex", "--all"], check=True)
        assert "1:foo" in f.read_text()

    def test_subst_default_literal_treats_metachars_literally(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# D\n\na.b and axb\n")
        subprocess.run([*MD_TOOLS, "subst", str(f), "a.b", "Z", "--all"], check=True)
        assert "Z and axb" in f.read_text()         # literal: a.b matched, axb did NOT


class TestCLISubst:
    """`subst` = LITERAL fixed-string substitution (positional OLD NEW; no s/// delimiter)."""

    def test_metachars_in_pattern_are_literal(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# D\n\nkeep a(b)|c and a and b\n")
        subprocess.run([*MD_TOOLS, "subst", str(f), "a(b)|c", "HIT"], check=True)
        body = f.read_text()
        assert "keep HIT and a and b" in body     # the literal "a(b)|c" matched
        assert "a and b" in body                  # bare a/b were NOT alternation-matched

    def test_replacement_is_verbatim(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# D\n\nfind here\n")
        subprocess.run([*MD_TOOLS, "subst", str(f), "find", r"a\1|b(c)"], check=True)
        assert r"a\1|b(c) here" in f.read_text()   # backslashes/metachars inserted verbatim

    def test_first_per_line_default_and_all_flag(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# D\n\nold old old\n")
        subprocess.run([*MD_TOOLS, "subst", str(f), "old", "N"], check=True)
        assert "N old old" in f.read_text()        # default: first match per line
        f.write_text("# D\n\nold old old\n")
        subprocess.run([*MD_TOOLS, "subst", str(f), "old", "N", "--all"], check=True)
        assert "N N N" in f.read_text()

    def test_ignore_case(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# D\n\nOLD value old\n")
        subprocess.run([*MD_TOOLS, "subst", str(f), "old", "x", "--all", "--ignore-case"], check=True)
        assert "x value x" in f.read_text()

    def test_slashes_no_delimiter_footgun(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# D\n\npath a/b/c here\n")
        subprocess.run([*MD_TOOLS, "subst", str(f), "a/b/c", "X/Y"], check=True)
        assert "X/Y here" in f.read_text()         # slashes are just data, no delimiter

    def test_section_scope(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# Doc\n\n## Alpha\n\nword\n\n## Beta\n\nword\n")
        subprocess.run([*MD_TOOLS, "subst", str(f), "word", "TERM", "--section", "Beta"], check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        assert "word" in "\n".join(tree.find_node_by_path("Doc:/:Alpha").content)
        assert "TERM" in "\n".join(tree.find_node_by_path("Doc:/:Beta").content)

    def test_frontmatter_opaque(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("---\nfoo: old\n---\n# D\n\nold body\n")
        subprocess.run([*MD_TOOLS, "subst", str(f), "old", "NEW", "--all"], check=True)
        assert "foo: old" in f.read_text()         # YAML frontmatter untouched

    def test_dry_run_does_not_write(self, tmp_path):
        f = tmp_path / "s.md"; f.write_text("# D\n\nold\n")
        before = f.read_text()
        r = subprocess.run([*MD_TOOLS, "subst", str(f), "old", "NEW", "--dry-run"],
                           capture_output=True, text=True)
        assert f.read_text() == before and "NEW" in r.stdout

    def test_nonmatch_no_mass_match(self, tmp_path):
        # Regression for the CLAUDE.md corruption: a |-heavy literal that doesn't occur
        # must NOT match empty-string at every line — file stays byte-identical.
        f = tmp_path / "s.md"; f.write_text(SIMPLE_DOC)
        before = f.read_text()
        r = subprocess.run([*MD_TOOLS, "subst", str(f), "| a | b |", "X"],
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert f.read_text() == before


class TestCLIItemAppend:

    def test_append_bottom(self, tmp_path):
        f = tmp_path / "i.md"; f.write_text("# Doc\n\n## L\n\n- one\n- two\n")
        subprocess.run([*MD_TOOLS, "item-append", str(f), "L", "- three"], check=True)
        assert f.read_text().rstrip().endswith("- three")

    def test_append_top(self, tmp_path):
        f = tmp_path / "i.md"; f.write_text("# Doc\n\n## L\n\n- one\n")
        subprocess.run([*MD_TOOLS, "item-append", str(f), "L", "- zero", "--top"], check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        body = "\n".join(tree.find_node_by_path("Doc:/:L").content)
        assert body.splitlines()[0].strip() == "- zero"

    def test_stdin(self, tmp_path):
        f = tmp_path / "i.md"; f.write_text("# Doc\n\n## L\n\n- one\n")
        subprocess.run([*MD_TOOLS, "item-append", str(f), "L", "--stdin"],
                       input="- piped\n", text=True, check=True)
        assert "- piped" in f.read_text()


class TestCLILineAppend:

    def test_creates_and_appends_with_newline(self, tmp_path):
        f = tmp_path / "log.md"  # does not exist yet
        subprocess.run([*MD_TOOLS, "line-append", str(f), "first"], check=True)
        subprocess.run([*MD_TOOLS, "line-append", str(f), "second"], check=True)
        assert f.read_text() == "first\nsecond\n"


class TestCLIRename:

    def test_rename_preserves_body_and_children(self, tmp_path):
        f = tmp_path / "r.md"
        f.write_text("# Doc\n\n## Old\n\nbody\n\n### Child\n\nc\n")
        subprocess.run([*MD_TOOLS, "rename", str(f), "Old", "--to", "New"], check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        node = tree.find_node_by_path("Doc:/:New")
        assert node is not None
        assert "body" in "\n".join(node.content)
        assert [c.title for c in node.children] == ["Child"]

    def test_rejects_separator_in_title(self, tmp_path):
        f = tmp_path / "r.md"; f.write_text("# Doc\n\n## Old\n\nbody\n")
        r = subprocess.run([*MD_TOOLS, "rename", str(f), "Old", "--to", "A:/:B"],
                           capture_output=True, text=True)
        assert r.returncode == 1
        assert "## Old" in f.read_text()  # left unchanged


# ============================================================================
# Partial-Path Resolution (contiguous right-anchored exact->prefix->substring)
# ============================================================================

PARTIAL_DOC = textwrap.dedent("""\
    # STATUS

    ## 2. Active Threads

    ### cluster-env-setup  [implement]

    Body.

    #### sub-task  [ ]

    Body.

    ### twin  [ ]

    Body.

    ### Setup

    Body.

    ### Setup and Config

    Body.

    ### widget  [implement]

    Body.

    ### thing-a  [implement] [v1]

    Body.

    ### thing-b  *[ ]

    Body.

    ### [ ] orphan-task

    Body.

    ### prioritized-item  [ ] (#2)

    Body.

    ### my-special-widget  [ ]

    Body.

    ## 7. Inbox

    ### cluster-env-setup: extra notes  [ ]

    Body.

    ### twin  [x]

    Body.
""")


def _walk(node, prefix=()):
    for child in node.children:
        yield child, prefix + (child.title,)
        yield from _walk(child, prefix + (child.title,))


def _title_of(tree, short):
    """Exact parsed title of the first node whose title starts with `short`."""
    for node, _ in _walk(tree.root):
        if node.title.startswith(short):
            return node.title
    raise AssertionError(f"no node titled like {short!r}")


@pytest.fixture
def partial_tree():
    tree = MarkdownTree()
    tree.parse(PARTIAL_DOC)
    return tree


class TestPartialPathResolution:

    # T1 — omit the H1 root; ancestor context disambiguates a colliding leaf.
    # Also: a redundant leading root is dropped, so the fully-rooted partial form
    # resolves identically.
    def test_omit_root_disambiguates(self, partial_tree):
        for loc in ("2. Active Threads:/:cluster-env-setup",
                    "STATUS:/:2. Active Threads:/:cluster-env-setup"):
            node, err = find_node_with_suggestions(partial_tree, loc)
            assert err is False, loc
            assert node is not None, loc
            assert node.title == "cluster-env-setup  [implement]", loc

    # T2 — bare colliding leaf is ambiguous -> refuse with candidates
    def test_bare_leaf_collision_refuses(self, partial_tree, capsys):
        node, err = find_node_with_suggestions(partial_tree, "cluster-env-setup")
        assert node is None and err is True
        assert "Ambiguous" in capsys.readouterr().err

    # T3 — bare leaf, unique -> resolves (prefix tier, tag stripped)
    def test_bare_leaf_unique(self, partial_tree):
        node, err = find_node_with_suggestions(partial_tree, "widget")
        assert err is False and node.title == "widget  [implement]"

    # T4 — state tag absorbed: bare name AND full-tag locator hit the same node
    def test_state_tag_absorbed_both_forms(self, partial_tree):
        n1, _ = find_node_with_suggestions(partial_tree, "widget")
        n2, _ = find_node_with_suggestions(
            partial_tree, _title_of(partial_tree, "widget"))
        assert n1 is not None and n1 is n2

    # T5 — exact-prefix-of-sibling: exact tier picks the shorter
    def test_exact_prefix_of_sibling(self, partial_tree):
        node, err = find_node_with_suggestions(partial_tree, "Setup")
        assert err is False and node.title == "Setup"

    # T6 — genuine middle-level gap (skip a NON-root ancestor) -> no match.
    # 'sub-task' lives under '2. Active Threads:/:cluster-env-setup'; naming the
    # grandparent + grandchild while skipping the parent is a real gap (the root
    # is droppable, but a non-root middle level is not).
    def test_gapped_no_match(self, partial_tree):
        node, err = find_node_with_suggestions(
            partial_tree, "2. Active Threads:/:sub-task")
        assert node is None and err is True

    # T7 — fully-rooted exact path via Step 0 fast path
    def test_fully_rooted_exact(self, partial_tree):
        target, _ = find_node_with_suggestions(partial_tree, "widget")
        node, err = find_node_with_suggestions(
            partial_tree, build_node_path(target))
        assert err is False and node is target

    # T8 — case-insensitive component match
    def test_case_insensitive(self, partial_tree):
        node, err = find_node_with_suggestions(
            partial_tree, "2. active threads:/:cluster-env-setup")
        assert err is False
        assert node.title == "cluster-env-setup  [implement]"

    # T9 — interior node WITH children is resolvable (e.g. a move target)
    def test_interior_node_with_children(self, partial_tree):
        node, err = find_node_with_suggestions(partial_tree, "2. Active Threads")
        assert err is False
        assert node.title == "2. Active Threads"
        assert len(node.children) > 0

    # T10 — garbage -> structured no-match
    def test_no_match_garbage(self, partial_tree):
        node, err = find_node_with_suggestions(partial_tree, "nonexistent-xyzzy")
        assert node is None and err is True

    # T11 — unique substring resolves (neither exact nor prefix)
    def test_unique_substring(self, partial_tree):
        node, err = find_node_with_suggestions(partial_tree, "special")
        assert err is False and node.title == "my-special-widget  [ ]"

    # T12 — regression: exact full path + leaf shorthand still resolve
    def test_regression_exact_and_shorthand(self, nested_tree):
        n1, e1 = find_node_with_suggestions(
            nested_tree, "Project:/:Active Work:/:TODO: First Item")
        assert e1 is False and n1.title == "TODO: First Item"
        n2, e2 = find_node_with_suggestions(nested_tree, "Key Decisions")
        assert e2 is False and n2.title == "Key Decisions"

    # T13 — empty / blank-only locator -> no match (no crash)
    def test_empty_locator(self, partial_tree):
        for bad in [":/:", "   ", ""]:
            node, err = find_node_with_suggestions(partial_tree, bad)
            assert node is None and err is True

    # T14 — stale trailing tag in the locator strips away -> resolves
    def test_stale_tag_strips(self, partial_tree):
        node, err = find_node_with_suggestions(partial_tree, "widget  [queued]")
        assert err is False and node.title == "widget  [implement]"

    # T15 — tag-specific exact: a literal tagged title addresses by tag
    def test_tag_specific_exact(self, partial_tree):
        x_title = next(n.title for n, _ in _walk(partial_tree.root)
                       if n.title.startswith("twin") and "[x]" in n.title)
        node, err = find_node_with_suggestions(partial_tree, x_title)
        assert err is False and node.title == x_title
        n2, e2 = find_node_with_suggestions(partial_tree, "twin")
        assert n2 is None and e2 is True  # bare 'twin' is ambiguous

    # T16 — decoration variants ('*[ ]', '[v1*]', '[a] [b]') all strip away
    def test_decoration_variants_stripped(self, partial_tree):
        for short in ("thing-a", "thing-b"):
            node, err = find_node_with_suggestions(partial_tree, short)
            assert err is False, short
            assert node.title.startswith(short), (short, node.title)

    # T17 — a trailing '(#)' / '(after:)' marker paren strips the same as a
    # bracket, so it no longer blocks resolution of the bare name.
    def test_marker_paren_stripped_resolves(self, partial_tree):
        node, err = find_node_with_suggestions(partial_tree, "prioritized-item")
        assert err is False
        assert node.title == "prioritized-item  [ ] (#2)"

    # T19 — _strip_state_tags drops trailing marker parens (the de-marker
    # normalizer rule): '(#...)' priority + '(after:...)' hint parens strip like
    # brackets; a mid-title paren and a leading checkbox behave as before.
    def test_strip_state_tags_drops_marker_parens(self):
        assert _strip_state_tags("prioritized-item  [ ] (#2)") == "prioritized-item"
        assert _strip_state_tags("thread  (#)") == "thread"
        assert _strip_state_tags("foo  (after: bar)") == "foo"
        assert _strip_state_tags("foo  [implement] (#1)") == "foo"
        assert _strip_state_tags("[ ] orphan") == "orphan"
        assert _strip_state_tags("Foo (bar) baz") == "Foo (bar) baz"

    def test_strip_state_tags_keeps_paren_before_first_bracket(self):
        """A paren group ahead of the state bracket is part of the NAME, not a marker."""
        assert _strip_state_tags("Universal refactor (/refactor skill)  [queued]") == \
            "Universal refactor (/refactor skill)"
        assert _strip_state_tags("verbs (add-todo, add-thread)  [ ] (#)") == \
            "verbs (add-todo, add-thread)"
        assert _mod._marker_groups("verbs (add-todo, add-thread)  *[ ] [v1] (#)") == \
            ("verbs (add-todo, add-thread)", ["*[ ]", "[v1]", "(#)"])
        assert _mod._marker_groups("name  (after: x)") == ("name", ["(after: x)"])

    # T18 — malformed leading-bracket heading resolves by name (insurance strip)
    def test_leading_bracket_malformed_resolves(self, partial_tree):
        node, err = find_node_with_suggestions(partial_tree, "orphan-task")
        assert err is False
        assert node.title == "[ ] orphan-task"


# ============================================================================
# SELECT → TRANSFORM → EMIT core (function-space redesign)
# ============================================================================

LEVEL_SKIP_DOC = textwrap.dedent("""\
    # Root

    ## Section

    #### Deep Child

    Deep body.
""")

CANON_STATUS_PATH = Path(__file__).resolve().parent / "fixtures" / "canonical_status.md"


def _parse(doc):
    t = MarkdownTree()
    t.parse(doc)
    return t


def _node(tree, title_prefix):
    """First node whose stripped title starts with title_prefix."""
    def walk(n):
        for c in n.children:
            if c.title.startswith(title_prefix):
                return c
            r = walk(c)
            if r:
                return r
        return None
    return walk(tree.root)


def _h1s(text):
    return [ln[2:] for ln in text.splitlines() if ln.startswith("# ")]


def _all_headings(text):
    return [ln for ln in text.splitlines() if ln.lstrip().startswith("#")]


# --- T1: collect_children ---------------------------------------------------

class TestCollectChildren:

    def test_depth_1_immediate_children(self, nested_tree):
        proj = _node(nested_tree, "Project") or nested_tree.root.children[0]
        kids = collect_children(proj, 1)
        assert [k.title for k in kids] == ["Active Work", "Key Decisions"]

    def test_depth_2_grandchildren_flat(self, nested_tree):
        proj = nested_tree.root.children[0]
        gks = collect_children(proj, 2)
        assert [g.title for g in gks] == [
            "TODO: First Item", "TODO: Second Item", "TODO: Third Item"]

    def test_depth_beyond_tree_is_empty(self, nested_tree):
        proj = nested_tree.root.children[0]
        assert collect_children(proj, 3) == []

    def test_depth_zero_returns_self(self, nested_tree):
        proj = nested_tree.root.children[0]
        assert collect_children(proj, 0) == [proj]

    def test_level_skip_counts_tree_depth_not_heading_level(self):
        tree = _parse(LEVEL_SKIP_DOC)
        section = _node(tree, "Section")
        # Deep Child is a #### directly under a ## (### skipped) → still depth 1.
        kids = collect_children(section, 1)
        assert [k.title for k in kids] == ["Deep Child"]


# --- T2: select_keep --------------------------------------------------------

class TestSelectKeep:

    def test_shallow_allowlist(self, nested_tree):
        head = nested_tree.root.children[0]  # Project
        survivors = select_keep(head, ["Key Decisions"])
        assert [s.title for s in survivors] == ["Key Decisions"]

    def test_deep_keep_materializes_scaffold_drops_siblings(self):
        tree = _parse(CANON_STATUS_PATH.read_text())
        head = tree.root.children[0]  # STATUS
        survivors = select_keep(head, ["1. Prioritization:/:Goal"])
        # Only Prioritization survives at top level (scaffold ancestor)…
        assert [s.title for s in survivors] == ["1. Prioritization"]
        prio = survivors[0]
        # …carrying ONLY Goal (Focus + Thread Order dropped).
        assert [c.title for c in prio.children] == ["Goal"]

    def test_deep_keep_keeps_scaffold_ancestor_intro_body(self):
        # O4: a scaffold ancestor that HAS an intro body keeps it by default.
        tree = _parse(CANON_STATUS_PATH.read_text())
        head = tree.root.children[0]
        survivors = select_keep(
            head, ["2. Active Threads:/:Thread Alpha:/:todo a1"])
        active = survivors[0]                       # §2 (scaffold, no intro body)
        alpha = active.children[0]                  # Thread Alpha (scaffold WITH body)
        assert alpha.title.startswith("Thread Alpha")
        assert alpha.content and "Intro for alpha." in "\n".join(alpha.content)
        assert [c.title for c in alpha.children] == ["todo a1  [ ]"]

    def test_path_not_found_skips_and_warns(self, nested_tree, capsys):
        head = nested_tree.root.children[0]
        survivors = select_keep(head, ["Key Decisions", "No Such"])
        assert [s.title for s in survivors] == ["Key Decisions"]
        assert "not found" in capsys.readouterr().err


# --- T3: select_omit --------------------------------------------------------

class TestSelectOmit:

    def test_shallow_denylist(self, nested_tree):
        head = nested_tree.root.children[0]
        survivors = select_omit(head, ["Active Work"])
        assert [s.title for s in survivors] == ["Key Decisions"]

    def test_deep_omit(self):
        tree = _parse(CANON_STATUS_PATH.read_text())
        head = tree.root.children[0]
        select_omit(head, ["1. Prioritization:/:Thread Order"])
        prio = _node(tree, "1. Prioritization")
        assert [c.title for c in prio.children] == ["Goal", "Focus"]

    def test_path_not_found_graceful(self, nested_tree, capsys):
        head = nested_tree.root.children[0]
        survivors = select_omit(head, ["No Such"])
        assert [s.title for s in survivors] == ["Active Work", "Key Decisions"]
        assert "not found" in capsys.readouterr().err


# --- T5: strip_bodies (target / child / all) --------------------------------

STRIP_DOC = "# X\n\nbody x.\n\n## Y\n\nbody y.\n\n### Z\n\nbody z.\n"


class TestStripBodies:

    def test_strip_all(self):
        x = _parse(STRIP_DOC).root.children[0]
        strip_bodies(x, "all")
        assert x.content == []
        assert x.children[0].content == []          # Y
        assert x.children[0].children[0].content == []  # Z
        # headings preserved
        assert [c.title for c in x.children] == ["Y"]

    def test_strip_target_only_self(self):
        x = _parse(STRIP_DOC).root.children[0]
        strip_bodies(x, "target")
        assert x.content == []
        assert x.children[0].content == ["body y."]  # descendant kept

    def test_strip_child_keeps_self_drops_descendants(self):
        x = _parse(STRIP_DOC).root.children[0]
        strip_bodies(x, "child")
        assert x.content == ["body x."]              # node body kept
        assert x.children[0].content == []           # Y stripped
        assert x.children[0].children[0].content == []  # Z stripped

    def test_strip_all_via_cli_keeps_heading(self):
        # `read X --strip-all-body-text` keeps X's heading + strips its subtree's
        # bodies (X is the unit when no keep/omit/children is given).
        out = subprocess.run(
            [*MD_TOOLS, "read", str(CANON_STATUS_PATH),
             "2. Active Threads:/:Thread Alpha", "--strip-all-body-text"],
            capture_output=True, text=True, check=True).stdout
        heads = _all_headings(out)
        assert "# Thread Alpha  [implement]" in heads
        assert "## todo a1  [ ]" in heads
        assert "Do a1." not in out and "Intro for alpha." not in out


# --- T4: strip_markers ------------------------------------------------------

class TestStripMarkers:

    def test_recursive_strip(self):
        tree = _parse(CANON_STATUS_PATH.read_text())
        alpha = _node(tree, "Thread Alpha")
        strip_markers(alpha)
        assert alpha.title == "Thread Alpha"
        assert [c.title for c in alpha.children] == ["todo a1", "todo a2"]

    def test_idempotent(self):
        n = MarkdownTree(); n.parse("# x  [implement] [v1]\n")
        node = n.root.children[0]
        strip_markers(node)
        once = node.title
        strip_markers(node)
        assert node.title == once == "x"

    def test_preserves_mid_title_link_and_backticks(self):
        n = MarkdownTree(); n.parse("# See `code` and [a](b)  [ ]\n")
        node = n.root.children[0]
        strip_markers(node)
        assert node.title == "See `code` and [a](b)"

    def test_strips_non_marker_trailing_paren_intended(self):
        # Collateral but INTENDED for blind exports (syntax-based strip).
        n = MarkdownTree(); n.parse("# Title (note)\n")
        node = n.root.children[0]
        strip_markers(node)
        assert node.title == "Title"


# --- T6: build_view canonical-order determinism -----------------------------

class TestBuildViewDeterminism:

    def test_keep_then_children_thread_pool(self):
        tree = _parse(CANON_STATUS_PATH.read_text())
        nodes = build_view(tree, ".", keep=["2. Active Threads", "3. Inactive Threads"],
                           children=True, strip_markers_flag=True)
        # ### threads lifted (## wrappers dropped), markers stripped.
        assert [n.title for n in nodes] == ["Thread Alpha", "Thread Beta", "Thread Gamma"]
        # each still carries its #### TODOs nested
        assert [c.title for c in nodes[0].children] == ["todo a1", "todo a2"]

    def test_keep_deep_no_lift_goals_only(self):
        tree = _parse(CANON_STATUS_PATH.read_text())
        nodes = build_view(
            tree, ".",
            keep=["0. Project Overview", "1. Prioritization:/:Goal",
                  "1. Prioritization:/:Focus", "4. Deliverables and Deadlines",
                  "5. Blockers"],
            strip_markers_flag=True)
        assert [n.title for n in nodes] == [
            "0. Project Overview", "1. Prioritization",
            "4. Deliverables and Deadlines", "5. Blockers"]
        prio = nodes[1]
        assert [c.title for c in prio.children] == ["Goal", "Focus"]

    def test_keep_then_omit_within_kept(self):
        # §5 edge: both given → keep then omit-within-kept.
        tree = _parse(CANON_STATUS_PATH.read_text())
        nodes = build_view(tree, ".", keep=["1. Prioritization"],
                           omit=["1. Prioritization:/:Thread Order"],
                           strip_markers_flag=True)
        assert [n.title for n in nodes] == ["1. Prioritization"]
        assert [c.title for c in nodes[0].children] == ["Goal", "Focus"]

    def test_flag_order_invariance(self):
        # build_view fixes the pipeline order; kwargs are order-free by construction.
        kw = dict(keep=["2. Active Threads", "3. Inactive Threads"],
                  children=True, depth=2, strip_markers_flag=True)
        a = build_view(_parse(CANON_STATUS_PATH.read_text()), ".", **kw)
        b = build_view(_parse(CANON_STATUS_PATH.read_text()), ".",
                       strip_markers_flag=True, depth=2, children=True,
                       keep=["2. Active Threads", "3. Inactive Threads"])
        assert [n.title for n in a] == [n.title for n in b] == [
            "todo a1", "todo a2", "todo b1", "todo g1"]


# --- T7: EMIT placement (CLI) ----------------------------------------------

class TestEmitPlacement:

    def test_bare_read_stays_native(self):
        out = subprocess.run(
            [*MD_TOOLS, "read", str(CANON_STATUS_PATH), "2. Active Threads:/:Thread Alpha"],
            capture_output=True, text=True, check=True).stdout
        # native level + markers preserved
        assert "### Thread Alpha  [implement]" in out
        assert "#### todo a1  [ ]" in out

    def test_read_select_form_relevels(self):
        out = subprocess.run(
            [*MD_TOOLS, "read", str(CANON_STATUS_PATH), ".",
             "--keep-sections", "2. Active Threads", "--children", "--strip-markers"],
            capture_output=True, text=True, check=True).stdout
        assert "# Thread Alpha" in _all_headings(out)
        assert "## todo a1" in _all_headings(out)
        assert "[implement]" not in out  # markers stripped

    def test_copy_node_set_releveled_new_file(self, tmp_path):
        out = tmp_path / "view.md"
        subprocess.run(
            [*MD_TOOLS, "copy", str(CANON_STATUS_PATH), ".", str(out),
             "--keep-sections", "2. Active Threads:,:3. Inactive Threads",
             "--children", "--strip-markers"],
            check=True)
        text = out.read_text()
        assert _h1s(text) == ["Thread Alpha", "Thread Beta", "Thread Gamma"]

    def test_move_under_parent(self, tmp_path):
        f = tmp_path / "s.md"
        f.write_text(CANON_STATUS_PATH.read_text())
        subprocess.run(
            [*MD_TOOLS, "move", str(f), "5. Blockers", "--parent", "4. Deliverables and Deadlines"],
            check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        assert tree.find_node_by_path(
            "STATUS:/:4. Deliverables and Deadlines:/:5. Blockers") is not None

    def test_move_parent_dot_is_the_h1(self, tmp_path):
        f = tmp_path / "s.md"
        f.write_text("# Doc\n\n## A\n\n### Nested\n\nbody.\n\n## B\n\nb.\n")
        subprocess.run([*MD_TOOLS, "move", str(f), "Nested", "--parent", "."], check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        assert [c.title for c in tree.root.children[0].children] == ["A", "B", "Nested"]
        assert tree.find_node_by_path("Doc:/:A").children == []

    def test_reorder_parent_dot_is_the_h1(self, tmp_path):
        f = tmp_path / "s.md"
        f.write_text("# Doc\n\n## A\n\na.\n\n## B\n\nb.\n")
        subprocess.run([*MD_TOOLS, "reorder", str(f), "B:,:A", "--parent", "."], check=True)
        tree = MarkdownTree(); tree.parse(f.read_text())
        assert [c.title for c in tree.root.children[0].children] == ["B", "A"]

    def test_multi_node_extract_via_children(self, tmp_path):
        src = tmp_path / "src.md"
        src.write_text(CANON_STATUS_PATH.read_text())
        out = tmp_path / "out.md"
        subprocess.run(
            [*MD_TOOLS, "extract", str(src), "2. Active Threads", str(out), "--children"],
            check=True)
        # both threads present in output…
        otree = MarkdownTree(); otree.parse(out.read_text())
        out_titles = [c.title for c in otree.root.children]
        assert any(t.startswith("Thread Alpha") for t in out_titles)
        assert any(t.startswith("Thread Beta") for t in out_titles)
        # …removed from source, which still re-parses well-formed
        stree = MarkdownTree(); stree.parse(src.read_text())
        active = stree.find_node_by_path("STATUS:/:2. Active Threads")
        assert active is not None and active.children == []
        # other sections intact
        assert stree.find_node_by_path("STATUS:/:3. Inactive Threads") is not None

    def test_clamp_collapse_boundary_warns(self, tmp_path):
        deep = tmp_path / "deep.md"
        deep.write_text("# R\n\n## A\n\n### B\n\n#### C\n\n##### D\n\n###### E\n\nbody.\n")
        tgt = tmp_path / "t.md"
        tgt.write_text("# T\n\n## P1\n\n### P2\n\n#### P3\n\n##### P4\n\n###### P5\n\nx.\n")
        res = subprocess.run(
            [*MD_TOOLS, "move", str(deep), "A", "--target", str(tgt),
             "--parent", "P1:/:P2:/:P3:/:P4:/:P5"],
            capture_output=True, text=True)
        assert res.returncode == 0
        assert "max markdown depth (6)" in res.stderr


# --- T8: the 3 prioritize views golden against the canonical fixture --------

class TestPrioritizeViewsGolden:

    def _view(self, *flags):
        return subprocess.run(
            [*MD_TOOLS, "read", str(CANON_STATUS_PATH), ".", *flags],
            capture_output=True, text=True, check=True).stdout

    def test_goals_only(self):
        out = self._view(
            "--keep-sections",
            "0. Project Overview:,:1. Prioritization:/:Goal:,:"
            "1. Prioritization:/:Focus:,:4. Deliverables and Deadlines:,:5. Blockers",
            "--strip-markers")
        assert _h1s(out) == [
            "0. Project Overview", "1. Prioritization",
            "4. Deliverables and Deadlines", "5. Blockers"]
        assert "Thread Order" not in out   # §1 sub-section dropped
        assert "Thread Alpha" not in out   # §2 dropped
        assert "[blocked]" not in out      # markers stripped
        assert "Goal" in out and "Focus" in out

    def test_thread_pool(self):
        out = self._view(
            "--keep-sections", "2. Active Threads:,:3. Inactive Threads",
            "--children", "--strip-markers")
        assert _h1s(out) == ["Thread Alpha", "Thread Beta", "Thread Gamma"]
        assert "## todo a1" in _all_headings(out)
        assert "[implement]" not in out and "[wip]" not in out
        assert "0. Project Overview" not in out

    def test_todos_only(self):
        out = self._view(
            "--keep-sections", "2. Active Threads:,:3. Inactive Threads",
            "--children", "--depth", "2", "--strip-markers")
        assert _h1s(out) == ["todo a1", "todo a2", "todo b1", "todo g1"]
        assert "Thread Alpha" not in out   # ### dropped
        assert "[ ]" not in out


# --- M1: keep/omit on extract + move ----------------------------------------

def _src(tmp_path, name="s.md"):
    f = tmp_path / name
    f.write_text(CANON_STATUS_PATH.read_text())
    return f


class TestExtractSelect:

    def test_keep_deep_leaf_removed_containers_retained(self, tmp_path):
        src = _src(tmp_path)
        out = tmp_path / "out.md"
        subprocess.run([*MD_TOOLS, "extract", str(src), ".", str(out),
                        "--keep-sections", "1. Prioritization:/:Goal"], check=True)
        # output = the keep view (relative path preserved)
        otree = MarkdownTree(); otree.parse(out.read_text())
        assert otree.find_node_by_path("1. Prioritization:/:Goal") is not None
        # source: Goal removed; Prioritization + Focus + Thread Order + body retained
        stree = MarkdownTree(); stree.parse(src.read_text())
        assert stree.find_node_by_path("STATUS:/:1. Prioritization:/:Goal") is None
        assert stree.find_node_by_path("STATUS:/:1. Prioritization:/:Focus") is not None
        assert stree.find_node_by_path("STATUS:/:1. Prioritization:/:Thread Order") is not None

    def test_omit_is_inverse_of_keep(self, tmp_path):
        src = _src(tmp_path)
        out = tmp_path / "out.md"
        subprocess.run([*MD_TOOLS, "extract", str(src), "1. Prioritization", str(out),
                        "--omit-sections", "Thread Order"], check=True)
        # output gets everything under §1 EXCEPT Thread Order
        otree = MarkdownTree(); otree.parse(out.read_text())
        out_titles = [c.title for c in otree.root.children]
        assert any("Goal" in t for t in out_titles) and any("Focus" in t for t in out_titles)
        assert not any("Thread Order" in t for t in out_titles)
        # source keeps ONLY the omitted under §1
        stree = MarkdownTree(); stree.parse(src.read_text())
        prio = stree.find_node_by_path("STATUS:/:1. Prioritization")
        assert [c.title for c in prio.children] == ["Thread Order"]

    def test_omit_typo_leaves_source_unchanged(self, tmp_path):
        src = _src(tmp_path)
        before = src.read_text()
        out = tmp_path / "out.md"
        r = subprocess.run([*MD_TOOLS, "extract", str(src), "1. Prioritization", str(out),
                            "--omit-sections", "No Such Section"],
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert src.read_text() == before          # source untouched, not wiped
        assert "left unchanged" in r.stderr

    def test_children_multi_node_regression(self, tmp_path):
        src = _src(tmp_path)
        out = tmp_path / "out.md"
        subprocess.run([*MD_TOOLS, "extract", str(src), "2. Active Threads", str(out),
                        "--children"], check=True)
        otree = MarkdownTree(); otree.parse(out.read_text())
        titles = [c.title for c in otree.root.children]
        assert any(t.startswith("Thread Alpha") for t in titles)
        assert any(t.startswith("Thread Beta") for t in titles)
        stree = MarkdownTree(); stree.parse(src.read_text())
        active = stree.find_node_by_path("STATUS:/:2. Active Threads")
        assert active is not None and active.children == []

    def test_transform_flags_shape_the_output(self, tmp_path):
        # TRANSFORM flags apply to the emitted (output) view; source is just removed.
        src = _src(tmp_path)
        out = tmp_path / "out.md"
        subprocess.run([*MD_TOOLS, "extract", str(src), "2. Active Threads", str(out),
                        "--children", "--depth", "2", "--strip-markers"], check=True)
        text = out.read_text()
        assert "# todo a1" in _all_headings(text)   # depth-2 lift, re-leveled
        assert "[implement]" not in text and "[wip]" not in text  # markers stripped
        # the §2 wrapper retained in source (only its lifted TODO grandchildren removed)
        stree = MarkdownTree(); stree.parse(src.read_text())
        assert stree.find_node_by_path("STATUS:/:2. Active Threads") is not None

    def test_strip_body_scopes_distinct_on_extract(self, tmp_path):
        # --strip-target: node body gone, descendant kept; --strip-child: inverse.
        for scope, head_body, child_body in [("target", 0, 1), ("child", 1, 0)]:
            src = _src(tmp_path, f"s_{scope}.md")
            out = tmp_path / f"o_{scope}.md"
            subprocess.run([*MD_TOOLS, "extract", str(src),
                            "2. Active Threads:/:Thread Alpha", str(out),
                            f"--strip-{scope}-body-text"], check=True)
            text = out.read_text()
            assert ("Intro for alpha." in text) == bool(head_body)   # Thread Alpha's own body
            assert ("Do a1." in text) == bool(child_body)            # a descendant body


class TestMoveSelect:

    def test_keep_relocates_leaf_source_keeps_rest(self, tmp_path):
        src = _src(tmp_path)
        subprocess.run([*MD_TOOLS, "move", str(src), "1. Prioritization",
                        "--keep-sections", "Goal",
                        "--parent", "4. Deliverables and Deadlines"], check=True)
        tree = MarkdownTree(); tree.parse(src.read_text())
        # Goal relocated under §4
        assert tree.find_node_by_path("STATUS:/:4. Deliverables and Deadlines:/:Goal") is not None
        # §1 lost Goal, kept Focus + Thread Order
        assert tree.find_node_by_path("STATUS:/:1. Prioritization:/:Goal") is None
        assert tree.find_node_by_path("STATUS:/:1. Prioritization:/:Focus") is not None

    def test_omit_relocates_complement(self, tmp_path):
        src = _src(tmp_path)
        # move everything under §1 except Goal into §4; §1 keeps Goal
        subprocess.run([*MD_TOOLS, "move", str(src), "1. Prioritization",
                        "--omit-sections", "Goal",
                        "--parent", "4. Deliverables and Deadlines"], check=True)
        tree = MarkdownTree(); tree.parse(src.read_text())
        prio = tree.find_node_by_path("STATUS:/:1. Prioritization")
        assert [c.title for c in prio.children] == ["Goal"]
        assert tree.find_node_by_path("STATUS:/:4. Deliverables and Deadlines:/:Focus") is not None


# --- M2: reshape (in-place SELECT/TRANSFORM) --------------------------------

class TestReshapeInPlace:

    def test_strip_all_is_heading_skeleton(self, tmp_path):
        src = _src(tmp_path)
        subprocess.run([*MD_TOOLS, "reshape", str(src), "2. Active Threads:/:Thread Alpha",
                        "--strip-all-body-text"], check=True)
        tree = MarkdownTree(); tree.parse(src.read_text())
        alpha = _node(tree, "Thread Alpha")  # title carries a [implement] tag
        assert [c.title.split()[0] for c in alpha.children] == ["todo", "todo"]  # headings kept
        assert "Do a1." not in tree.dump() and "Intro for alpha." not in tree.dump()

    def test_keep_prunes_in_place(self, tmp_path):
        src = _src(tmp_path)
        subprocess.run([*MD_TOOLS, "reshape", str(src), "1. Prioritization",
                        "--keep-sections", "Goal"], check=True)
        tree = MarkdownTree(); tree.parse(src.read_text())
        prio = tree.find_node_by_path("STATUS:/:1. Prioritization")
        assert [c.title for c in prio.children] == ["Goal"]

    def test_omit_deletes_in_place(self, tmp_path):
        src = _src(tmp_path)
        subprocess.run([*MD_TOOLS, "reshape", str(src), "1. Prioritization",
                        "--omit-sections", "Thread Order"], check=True)
        tree = MarkdownTree(); tree.parse(src.read_text())
        prio = tree.find_node_by_path("STATUS:/:1. Prioritization")
        assert [c.title for c in prio.children] == ["Goal", "Focus"]

    def test_flatten_in_place(self, tmp_path):
        src = _src(tmp_path)
        subprocess.run([*MD_TOOLS, "reshape", str(src), "1. Prioritization",
                        "--flatten"], check=True)
        tree = MarkdownTree(); tree.parse(src.read_text())
        prio = tree.find_node_by_path("STATUS:/:1. Prioritization")
        # every descendant becomes a flat direct child (Thread Order's child lifted too)
        titles = [c.title for c in prio.children]
        assert "Goal" in titles and "Focus" in titles and "Thread Order" in titles
        assert any(t.startswith("thread alpha first") for t in titles)
        assert all(c.children == [] for c in prio.children)  # no nesting left

    def test_no_flag_errors(self, tmp_path):
        src = _src(tmp_path)
        before = src.read_text()
        r = subprocess.run([*MD_TOOLS, "reshape", str(src), "1. Prioritization"],
                           capture_output=True, text=True)
        assert r.returncode == 1
        assert "nothing to do" in r.stderr
        assert src.read_text() == before

    def test_abridge_is_reshape_strip_all_alias(self, tmp_path):
        # `abridge FILE SECTION` is a convenience alias for reshape --strip-all-body-text:
        # strips the section's subtree to a heading skeleton in place.
        src = _src(tmp_path)
        subprocess.run([*MD_TOOLS, "abridge", str(src), "2. Active Threads:/:Thread Alpha"],
                       check=True)
        tree = MarkdownTree(); tree.parse(src.read_text())
        alpha = _node(tree, "Thread Alpha")
        assert [c.title.split()[0] for c in alpha.children] == ["todo", "todo"]  # headings kept
        assert "Do a1." not in tree.dump() and "Intro for alpha." not in tree.dump()  # bodies gone

    def test_keep_resolving_nothing_leaves_section_intact(self, tmp_path):
        # reshape --keep with an all-typo path must NOT empty the section.
        src = _src(tmp_path)
        before = src.read_text()
        r = subprocess.run([*MD_TOOLS, "reshape", str(src), "1. Prioritization",
                            "--keep-sections", "No Such Path"], capture_output=True, text=True)
        assert r.returncode == 0
        assert src.read_text() == before
        assert "left unchanged" in r.stderr


class TestExtractAbridge:
    """extract-abridge = copy (full) to OUTPUT + reshape source to a heading skeleton."""

    def test_output_full_source_breadcrumbs(self, nested_file, tmp_path):
        out = tmp_path / "out.md"
        subprocess.run([*MD_TOOLS, "extract-abridge", str(nested_file), "Active Work", str(out)],
                       check=True)
        # OUTPUT keeps full content
        otree = MarkdownTree(); otree.parse(out.read_text())
        assert "Description of first" in otree.dump()
        # SOURCE: section stays as a heading skeleton (breadcrumbs), bodies stripped
        stree = MarkdownTree(); stree.parse(nested_file.read_text())
        active = stree.find_node_by_path("Project:/:Active Work")
        assert active is not None and len(active.children) == 3   # headings kept
        assert "Description of first" not in stree.dump()         # bodies stripped


class TestRootDestination:
    """insert takes the destination as a required positional, so there is no
    parent-less form to disambiguate. "." addresses the document root: the single
    H1 when there is one (payload becomes a `##` under it), otherwise the
    synthetic container. On a multi-H1 file "." therefore ADDS another top-level
    title — allowed, because naming "." is an explicit request rather than the
    accident a parent-less insert used to be, but warned about because it grows
    the H1 count on an already non-canonical file."""

    def test_dot_creates_h2_under_single_h1(self, simple_file):
        subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), ".", "# Section D\n\nNew content."],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        assert len(tree.root.children) == 1            # single H1 root, no second H1
        h1 = tree.root.children[0]
        assert h1.title == "Root"
        new = h1.children[-1]
        assert new.title == "Section D"
        assert new.level == 2                          # `## `, not a sibling `# `

    def test_dot_after_sibling_resolves_h1_children(self, simple_file):
        """--after-sibling with "." resolves against the H1's children (the `##`
        sections), not the synthetic root's child set."""
        subprocess.run(
            [*MD_TOOLS, "insert", str(simple_file), ".", "# Section A2\n\nBody.",
             "--after-sibling", "Section A"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(simple_file.read_text())
        h1 = tree.root.children[0]
        titles = [c.title for c in h1.children]
        assert titles == ["Section A", "Section A2", "Section B", "Section C"]

    def test_dot_on_multiroot_warns_but_proceeds(self, tmp_path):
        f = tmp_path / "multi.md"
        f.write_text("# Alpha\n\nA.\n\n# Beta\n\nB.\n")
        result = subprocess.run(
            [*MD_TOOLS, "insert", str(f), ".", "# Gamma\n\ng."],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "top-level titles" in result.stderr
        tree = MarkdownTree()
        tree.parse(f.read_text())
        assert [c.title for c in tree.root.children] == ["Alpha", "Beta", "Gamma"]

    def test_named_destination_on_multiroot_nests(self, tmp_path):
        """Naming a section instead of "." nests normally on a multi-H1 file and
        warns about nothing."""
        f = tmp_path / "multi.md"
        f.write_text("# Alpha\n\nA.\n\n# Beta\n\nB.\n")
        result = subprocess.run(
            [*MD_TOOLS, "insert", str(f), "Beta", "# Gamma\n\ng."],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "top-level titles" not in result.stderr
        tree = MarkdownTree()
        tree.parse(f.read_text())
        assert [c.title for c in tree.root.children] == ["Alpha", "Beta"]
        beta = tree.root.children[1]
        assert [c.title for c in beta.children] == ["Gamma"]

    def test_dot_on_rootless_file_creates_first_heading(self, tmp_path):
        f = tmp_path / "rootless.md"
        f.write_text("Just prose, no headings at all.\n")
        subprocess.run(
            [*MD_TOOLS, "insert", str(f), ".", "# First Heading\n\nBody."],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(f.read_text())
        assert [c.title for c in tree.root.children] == ["First Heading"]


class TestSymlinkWrite:
    """A write to a symlinked path must modify the REAL target and PRESERVE the
    symlink (realpath, not abspath, in atomic_write/_lock_dir_for). Regression for
    the os.replace-clobbers-the-symlink bug that detached ~/.claude/STATUS.md."""

    def test_insert_through_symlink_preserves_link(self, tmp_path):
        real = (tmp_path / "real") ; real.mkdir()
        target = real / "STATUS.md" ; target.write_text(SIMPLE_DOC)
        link = (tmp_path / "link") ; link.mkdir()
        sl = link / "STATUS.md" ; os.symlink(target, sl)
        subprocess.run(
            [*MD_TOOLS, "insert", str(sl), "Root", "# Section D\n\nNew."],
            check=True,
        )
        assert sl.is_symlink()                                  # link NOT replaced
        assert os.path.realpath(sl) == os.path.realpath(target)
        assert "Section D" in target.read_text()               # change hit real file
        assert "Section D" in sl.read_text()

    def test_subst_through_symlink_preserves_link(self, tmp_path):
        target = tmp_path / "real_STATUS.md" ; target.write_text(SIMPLE_DOC)
        sl = tmp_path / "link_STATUS.md" ; os.symlink(target, sl)
        subprocess.run([*MD_TOOLS, "subst", str(sl), "Content A.", "Edited A."], check=True)
        assert sl.is_symlink()
        assert "Edited A." in target.read_text()

    def test_delete_through_symlink_preserves_link(self, tmp_path):
        target = tmp_path / "real_d.md" ; target.write_text(SIMPLE_DOC)
        sl = tmp_path / "link_d.md" ; os.symlink(target, sl)
        subprocess.run([*MD_TOOLS, "delete", str(sl), "Section B"], check=True)
        assert sl.is_symlink()
        assert "Section B" not in target.read_text()


class TestSkippedOutlineLevels:
    """A skipped outline level (no # before ##, or #### directly under ## with no ###)
    must NOT make same-level headings nest into a chain. The parser nests by heading
    level (parent = nearest preceding heading with a strictly smaller level), so
    skipped-level siblings stay siblings. Regression for the parse stack-pop rule."""

    def test_h2_skip_to_h4_items_are_siblings(self):
        """The canonical STATUS_SCHEMA shape: #### items directly under a ## section
        (no ###) are SIBLINGS under the ##, not a i1 -> i2 chain."""
        tree = MarkdownTree()
        tree.parse("# Root\n\n## Sec\n\ns\n\n#### i1\n\n1\n\n#### i2\n\n2\n")
        sec = tree.root.children[0].children[0]
        assert sec.title == "Sec"
        assert [c.title for c in sec.children] == ["i1", "i2"]   # siblings, not nested

    def test_h1_skip_to_h3_are_siblings(self):
        """# then two ### (H2 skipped): the ### headings are siblings under Root."""
        tree = MarkdownTree()
        tree.parse("# Root\n\n### A\n\na\n\n### B\n\nb\n")
        root = tree.root.children[0]
        assert [c.title for c in root.children] == ["A", "B"]

    def test_skip_level_roundtrip_preserves_content(self):
        """parse -> dump of a skipped-level doc preserves every heading line (the items
        keep their original heading level; the skip is reproduced, not normalized away)."""
        src = "# Root\n\n## Sec\n\n#### i1\n\nx\n\n#### i2\n\ny\n"
        tree = MarkdownTree()
        tree.parse(src)
        out = tree.dump()
        for line in ("# Root", "## Sec", "#### i1", "#### i2"):
            assert line in out
        # re-parse the dump: the items are still siblings (stable round-trip)
        tree2 = MarkdownTree()
        tree2.parse(out)
        sec2 = tree2.root.children[0].children[0]
        assert [c.title for c in sec2.children] == ["i1", "i2"]

    def test_collect_children_returns_all_skipped_level_siblings(self):
        """collect_children(Sec, depth=1) returns BOTH #### items (tree-depth-1 children),
        not just the first -- the incompleteness the old chain-nesting caused is gone."""
        tree = MarkdownTree()
        tree.parse("# Root\n\n## Sec\n\n#### i1\n\n1\n\n#### i2\n\n2\n")
        sec = tree.root.children[0].children[0]
        assert [c.title for c in collect_children(sec, depth=1)] == ["i1", "i2"]


# ============================================================================
# Phase 1: shared EMIT back-end (place_view + commit) — cross-verb consistency.
# copy/extract/move/replace now place-and-merge by marker-transparent title-match
# instead of copy/extract dump-and-appending a re-leveled duplicate (I1/I2/I4), and
# every section write routes through commit (backup-if-exists I3, one trailing
# newline I12). See markdowns/plans_draft/..._PHASE_1__MD_TOOLS_EMITCONSISTENCY_*.
# ============================================================================


def _striplo(t):
    return _strip_state_tags(t).strip().lower()


def _shared_under_container(dest_path):
    """Parse dest; return (the Container node, [its Shared children, marker-stripped-match])."""
    tree = MarkdownTree(); tree.parse(Path(dest_path).read_text())
    container = tree.find_node_by_path("D:/:Container")
    shareds = [c for c in container.children if _striplo(c.title) == "shared"]
    return tree, container, shareds


def _run_emit_verb(verb, tmp_path, *, dest_shared_suffix="", incoming_body="",
                   on_conflict=None, append=False):
    """Place a `### Shared` (carrying `#### kidA`, optional leading body) into a
    destination `## Container` that already holds `### Shared` / `#### kidB`, via `verb`.
    Returns the dest path. copy/extract/move all merge a whole section by title; replace
    merges a content fragment's headers — all share _merge_node_into, so the OUTCOME is
    the same Container/Shared/{kidB,kidA} (the point of the consistency suite)."""
    dest = tmp_path / "dest.md"
    dest.write_text(f"# D\n\n## Container\n\n### Shared{dest_shared_suffix}\n\n#### kidB\n\nb.\n")
    body = f"\n{incoming_body}\n" if incoming_body else "\n"
    src = tmp_path / "src.md"
    src.write_text(f"# S\n\n### Shared{body}\n#### kidA\n\na.\n")
    flags = []
    if on_conflict:
        flags += ["--on-conflict", on_conflict]
    if append:
        flags += ["--append"]
    if verb in ("copy", "extract"):
        subprocess.run([*MD_TOOLS, verb, str(src), "Shared", str(dest),
                        "--parent", "Container", *flags], check=True)
    elif verb == "move":
        # move always merges (no --on-conflict); used only for the default-merge cases.
        subprocess.run([*MD_TOOLS, "move", str(src), "Shared",
                        "--target", str(dest), "--parent", "Container"], check=True)
    elif verb == "replace":
        # replace merges a content fragment's headers into Container's children; the
        # fragment re-declares `### Shared` so it merges into the existing Shared.
        frag = "### Shared\n" + (f"\n{incoming_body}\n" if incoming_body else "\n") + "\n#### kidA\n\na."
        rflags = ["--full-subtree"] if on_conflict == "full-subtree" else []
        subprocess.run([*MD_TOOLS, "replace", str(dest), "Container", frag, *rflags], check=True)
    return dest


class TestCrossVerbPlacementConsistency:
    """The death certificate for I1: copy/extract/move/replace merge IDENTICALLY into an
    existing same-(marker-stripped)-title destination instead of duplicating."""

    @pytest.mark.parametrize("verb", ["copy", "extract", "move", "replace"])
    def test_merge_default_no_dup_across_verbs(self, verb, tmp_path):
        dest = _run_emit_verb(verb, tmp_path)
        _, container, shareds = _shared_under_container(dest)
        assert len(shareds) == 1, f"{verb}: duplicated Shared instead of merging"
        kids = sorted(_striplo(c.title) for c in shareds[0].children)
        assert kids == ["kida", "kidb"], f"{verb}: both children must survive the merge"
        # placed at the correct level: Container ## (2) -> Shared ### (3) -> kids #### (4)
        assert shareds[0].level == container.level + 1
        assert all(c.level == shareds[0].level + 1 for c in shareds[0].children)

    @pytest.mark.parametrize("verb", ["copy", "extract", "move", "replace"])
    def test_merge_children_only_leaves_target_header_untouched(self, verb, tmp_path):
        # G1-sub: the incoming Shared carries NO body (children-only), so the target's
        # header — including a user `(#)` pin and `[v2]` tier — must survive untouched.
        dest = _run_emit_verb(verb, tmp_path, dest_shared_suffix="  [v2] (#)")
        _, _, shareds = _shared_under_container(dest)
        assert len(shareds) == 1
        assert shareds[0].title == "Shared  [v2] (#)", f"{verb}: marker zone was clobbered"
        kids = sorted(_striplo(c.title) for c in shareds[0].children)
        assert kids == ["kida", "kidb"]

    @pytest.mark.parametrize("verb", ["copy", "extract", "move", "replace"])
    def test_merge_with_leading_prose_refreshes_header_and_body(self, verb, tmp_path):
        # Incoming Shared carries body prose -> clobber_body: the target body refreshes and
        # the header is rewritten to the incoming title (so a stale dest marker drops).
        dest = _run_emit_verb(verb, tmp_path, dest_shared_suffix="  [v2]",
                              incoming_body="NEW shared body.")
        _, _, shareds = _shared_under_container(dest)
        assert len(shareds) == 1
        assert shareds[0].title == "Shared", f"{verb}: header not refreshed to incoming"
        assert "NEW shared body." in "\n".join(shareds[0].content)
        kids = sorted(_striplo(c.title) for c in shareds[0].children)
        assert kids == ["kida", "kidb"]

    @pytest.mark.parametrize("verb", ["copy", "extract"])
    def test_clobber_body_keeps_unnamed_children(self, verb, tmp_path):
        dest = _run_emit_verb(verb, tmp_path, incoming_body="REFRESHED.",
                              on_conflict="clobber-body")
        _, _, shareds = _shared_under_container(dest)
        assert len(shareds) == 1
        assert "REFRESHED." in "\n".join(shareds[0].content)
        # clobber-body keeps the unnamed kidB, adds kidA
        kids = sorted(_striplo(c.title) for c in shareds[0].children)
        assert kids == ["kida", "kidb"]

    @pytest.mark.parametrize("verb", ["copy", "extract", "replace"])
    def test_full_subtree_drops_unnamed_children(self, verb, tmp_path):
        dest = _run_emit_verb(verb, tmp_path, on_conflict="full-subtree")
        _, _, shareds = _shared_under_container(dest)
        assert len(shareds) == 1
        # full-subtree replaces the child set: only the incoming kidA, kidB dropped
        kids = sorted(_striplo(c.title) for c in shareds[0].children)
        assert kids == ["kida"], f"{verb}: full-subtree must drop the unnamed kidB"

    @pytest.mark.parametrize("verb", ["copy", "extract"])
    def test_append_opt_in_preserves_legacy_dup(self, verb, tmp_path):
        dest = _run_emit_verb(verb, tmp_path, append=True)
        _, _, shareds = _shared_under_container(dest)
        assert len(shareds) == 2, f"{verb}: --append must place a duplicate (legacy behavior)"

    def test_level_correctness_deep_parent(self, tmp_path):
        # Merge into a Shared nested two levels deep; kids must land at Shared.level+1,
        # never re-leveled to the document root.
        dest = tmp_path / "d.md"
        dest.write_text("# D\n\n## L2\n\n### L3\n\n#### Shared\n\n##### kidB\n\nb.\n")
        src = tmp_path / "s.md"
        src.write_text("# S\n\n#### Shared\n\n##### kidA\n\na.\n")
        subprocess.run([*MD_TOOLS, "copy", str(src), "Shared", str(dest),
                        "--parent", "L2:/:L3"], check=True)
        tree = MarkdownTree(); tree.parse(dest.read_text())
        shared = tree.find_node_by_path("D:/:L2:/:L3:/:Shared")
        assert shared is not None and shared.level == 4          # #### under ### L3
        kids = sorted(_striplo(c.title) for c in shared.children)
        assert kids == ["kida", "kidb"]
        assert all(c.level == 5 for c in shared.children)        # ##### under #### Shared


class TestCopyMergeNoDup:

    def test_copy_into_existing_same_title_merges(self, tmp_path):
        # The original "two children into one thread" scenario, as a one-call merge.
        arc = tmp_path / "arc.md"
        arc.write_text("# ARC\n\n## Thread Alpha  [implement]\n\n### Done one  [x]\n\no.\n")
        src = tmp_path / "src.md"
        src.write_text("# SRC\n\n## Thread Alpha  [implement]\n\n### Done two  [x]\n\nt.\n")
        subprocess.run([*MD_TOOLS, "copy", str(src), "Thread Alpha", str(arc)], check=True)
        tree = MarkdownTree(); tree.parse(arc.read_text())
        alphas = [c for c in tree.root.children[0].children if _striplo(c.title) == "thread alpha"]
        assert len(alphas) == 1                                  # one merged thread, not two
        kids = sorted(_striplo(c.title) for c in alphas[0].children)
        assert kids == ["done one", "done two"]

    def test_copy_to_fresh_file_unchanged(self, tmp_path):
        # The dominant case MUST stay byte-for-byte: a copy to a NON-EXISTENT output
        # re-levels the section to the new-file root, one trailing newline, no merge.
        src = tmp_path / "s.md"
        src.write_text("# Doc\n\n## Section A\n\nContent A.\n\n### A1\n\nNested.\n")
        out = tmp_path / "fresh.md"
        subprocess.run([*MD_TOOLS, "copy", str(src), "Section A", str(out)], check=True)
        assert out.read_text() == "# Section A\n\nContent A.\n\n## A1\n\nNested.\n"


class TestCommitContract:

    def test_copy_to_existing_creates_backup(self, tmp_path, monkeypatch):
        # I3: copy/extract now back up an EXISTING output before overwriting it.
        calls = []
        monkeypatch.setattr(_mod, "create_backup", lambda p, t: calls.append(os.path.realpath(p)))
        src = tmp_path / "s.md"; src.write_text("# S\n\n## A\n\nx.\n")
        dest = tmp_path / "d.md"; dest.write_text("# D\n\n## B\n\ny.\n")
        _mod.copy_section(str(src), "A", str(dest))
        assert os.path.realpath(str(dest)) in calls               # existing dest backed up

    def test_copy_to_fresh_makes_no_backup(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(_mod, "create_backup", lambda p, t: calls.append(p))
        src = tmp_path / "s.md"; src.write_text("# S\n\n## A\n\nx.\n")
        fresh = tmp_path / "new.md"                                # does not exist
        _mod.copy_section(str(src), "A", str(fresh))
        assert calls == []                                        # fresh output -> no backup

    def test_trailing_newline_exactly_one(self, tmp_path):
        # I12: commit normalizes to exactly one trailing newline (a fresh copy used to
        # get none; an existing target kept its own count).
        src = tmp_path / "s.md"; src.write_text("# S\n\n## A\n\nx.")  # source has none
        out = tmp_path / "o.md"
        subprocess.run([*MD_TOOLS, "copy", str(src), "A", str(out)], check=True)
        t = out.read_text()
        assert t.endswith("\n") and not t.endswith("\n\n")

    def test_copy_locks_source(self, tmp_path, monkeypatch):
        # I13: copy locks BOTH source and target (it reads the source, writes the target).
        import contextlib
        seen = []
        real = _mod.multi_file_lock
        @contextlib.contextmanager
        def spy(*paths, **kw):
            seen.extend(paths)
            with real(*paths, **kw):
                yield
        monkeypatch.setattr(_mod, "multi_file_lock", spy)
        src = tmp_path / "s.md"; src.write_text("# S\n\n## A\n\nx.\n")
        out = tmp_path / "o.md"
        _mod.copy_section(str(src), "A", str(out))
        assert str(src) in seen                                   # source is in the lock set


class TestMovePlacementParity:

    def test_move_no_spurious_stderr_on_success(self, tmp_path):
        # I5: a successful cross-file move must not emit the speculative "No exact match"
        # error (the destination-exists probe used to route a miss through the user-facing
        # error printer).
        src = tmp_path / "s.md"; src.write_text("# S\n\n## Alpha\n\nx.\n")
        tgt = tmp_path / "t.md"; tgt.write_text("# T\n\n## Container\n\ny.\n")
        r = subprocess.run(
            [*MD_TOOLS, "move", str(src), "Alpha", "--target", str(tgt), "--parent", "Container"],
            capture_output=True, text=True)
        assert r.returncode == 0
        assert "No exact match" not in r.stderr

    def test_move_routes_through_place_view(self, tmp_path, monkeypatch):
        called = []
        real = _mod.place_view
        def spy(*a, **k):
            called.append(True)
            return real(*a, **k)
        monkeypatch.setattr(_mod, "place_view", spy)
        f = tmp_path / "f.md"
        f.write_text("# D\n\n## Active\n\n### A\n\nx.\n\n## Dest\n\nd.\n")
        _mod.move_sections(str(f), None, "Active:/:A", parent_path="Dest")
        assert called                                             # placement goes through EMIT


# ============================================================================
# B3 remainder — convert unification + backlog (list/map positional, insert
# --before-sibling/--state, body-line-append rename, whole-file blank-run normalize)
# ============================================================================

class TestB3ListMapPositional:
    """Item A: list/map accept an optional positional section (alias for --path)."""

    DOC = "# Root\n\n## Alpha\n\n### A1\n\nx.\n\n## Beta\n\ny.\n"

    def test_list_positional_equals_path_flag(self, tmp_path):
        f = tmp_path / "d.md"; f.write_text(self.DOC)
        a = subprocess.run([*MD_TOOLS, "list", str(f), "Root:/:Alpha"], capture_output=True, text=True, check=True)
        b = subprocess.run([*MD_TOOLS, "list", str(f), "--path", "Root:/:Alpha"], capture_output=True, text=True, check=True)
        assert a.stdout == b.stdout and "Alpha" in a.stdout

    def test_map_positional_equals_path_flag(self, tmp_path):
        f = tmp_path / "d.md"; f.write_text(self.DOC)
        a = subprocess.run([*MD_TOOLS, "map", str(f), "Root:/:Alpha"], capture_output=True, text=True, check=True)
        b = subprocess.run([*MD_TOOLS, "map", str(f), "--path", "Root:/:Alpha"], capture_output=True, text=True, check=True)
        assert a.stdout == b.stdout and "Alpha" in a.stdout


class TestRenameMarkerSlots:
    """Editing ONE marker on a heading without retyping the rest. Rebuilding a
    full title by hand to change a state tag is how a depth-tier, a provisional
    '*' or a priority paren gets silently dropped, so --state / --tier address a
    bracket by POSITION and leave every other byte alone. Placement only — no
    value is checked against any controlled vocabulary."""

    @staticmethod
    def _titles(path):
        tree = MarkdownTree()
        tree.parse(path.read_text())
        out = []
        def walk(n):
            for c in n.children:
                out.append(c.title)
                walk(c)
        walk(tree.root)
        return out

    @pytest.fixture
    def marked(self, tmp_path):
        f = tmp_path / "marked.md"
        f.write_text(
            "# T\n\n## Plain\n\n## Tagged  [implement]\n\n"
            "## Full  *[implement] [v1] (#)\n\n## Pinned  [queued] (#2)\n"
        )
        return f

    def test_state_flip_preserves_tier_star_and_pin(self, marked):
        """The load-bearing case: only the state bracket changes."""
        subprocess.run([*MD_TOOLS, "rename", str(marked), "Full", "--state", "x"], check=True)
        assert "Full  *[x] [v1] (#)" in self._titles(marked)

    def test_state_preserves_trailing_paren(self, marked):
        subprocess.run([*MD_TOOLS, "rename", str(marked), "Pinned", "--state", "x"], check=True)
        assert "Pinned  [x] (#2)" in self._titles(marked)

    def test_state_keeps_name_internal_paren_in_place(self, tmp_path):
        """A paren that precedes the state bracket is the name's; the flip must
        not pull it into the marker zone or re-space it."""
        f = tmp_path / "paren.md"
        f.write_text("# T\n\n## Verbs (add-todo, add-thread)  [ ]\n\n"
                     "## Mechanism (/refactor skill)  [queued] (#)\n")
        subprocess.run([*MD_TOOLS, "rename", str(f), "Verbs", "--state", "superseded"], check=True)
        subprocess.run([*MD_TOOLS, "rename", str(f), "Mechanism", "--state", "x"], check=True)
        titles = self._titles(f)
        assert "Verbs (add-todo, add-thread)  [superseded]" in titles
        assert "Mechanism (/refactor skill)  [x] (#)" in titles

    def test_state_on_unmarked_heading_adds_bracket(self, marked):
        subprocess.run([*MD_TOOLS, "rename", str(marked), "Plain", "--state", " "], check=True)
        assert "Plain  [ ]" in self._titles(marked)

    def test_tier_appends_after_state(self, marked):
        subprocess.run([*MD_TOOLS, "rename", str(marked), "Tagged", "--tier", "v2"], check=True)
        assert "Tagged  [implement] [v2]" in self._titles(marked)

    def test_tier_without_state_refuses_and_changes_nothing(self, marked):
        original = marked.read_text()
        result = subprocess.run(
            [*MD_TOOLS, "rename", str(marked), "Plain", "--tier", "v3"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "no state bracket" in result.stderr
        assert marked.read_text() == original

    def test_no_flags_errors(self, marked):
        original = marked.read_text()
        result = subprocess.run(
            [*MD_TOOLS, "rename", str(marked), "Plain"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert marked.read_text() == original

    def test_full_retitle_still_works(self, marked):
        subprocess.run(
            [*MD_TOOLS, "rename", str(marked), "Plain", "--to", "Renamed Outright"],
            check=True,
        )
        assert "Renamed Outright" in self._titles(marked)

    def test_state_and_tier_together(self, marked):
        subprocess.run(
            [*MD_TOOLS, "rename", str(marked), "Tagged", "--state", "x", "--tier", "v3"],
            check=True,
        )
        assert "Tagged  [x] [v3]" in self._titles(marked)
class TestB3BodyLineAppend:
    """Item C: body-line-append verb + item-append alias."""

    def test_body_line_append(self, tmp_path):
        f = tmp_path / "d.md"; f.write_text("# D\n\n## L\n\n- one\n")
        subprocess.run([*MD_TOOLS, "body-line-append", str(f), "L", "- two"], check=True)
        assert "- two" in f.read_text()

    def test_item_append_alias(self, tmp_path):
        f = tmp_path / "d.md"; f.write_text("# D\n\n## L\n\n- one\n")
        subprocess.run([*MD_TOOLS, "item-append", str(f), "L", "- two"], check=True)
        assert "- two" in f.read_text()


class TestB3NormalizeBlankRuns:
    """Item D: whole-file gsub/subst collapse 2+ blank lines to one (outside code fences)."""

    def test_gsub_collapses_blank_runs(self, tmp_path):
        f = tmp_path / "d.md"
        f.write_text("# D\n\n## A\n\nkeep\n\nX\n\nkeep2\n")   # delete X -> a 3-blank run
        subprocess.run([*MD_TOOLS, "gsub", str(f), "^X$", ""], check=True)
        t = f.read_text()
        assert "X" not in t.split("## A")[1]
        assert "\n\n\n" not in t                              # no 2+ blank-line run remains

    def test_blank_runs_preserved_in_fence(self, tmp_path):
        f = tmp_path / "d.md"
        f.write_text("# D\n\n## A\n\n```\nline1\n\n\nline2\n```\n\nx CHANGE\n")
        subprocess.run([*MD_TOOLS, "gsub", str(f), "CHANGE", "done"], check=True)
        t = f.read_text()
        assert "line1\n\n\nline2" in t                        # in-fence blank run preserved
        assert "done" in t

    def test_subst_collapses_blank_runs(self, tmp_path):
        f = tmp_path / "d.md"
        f.write_text("# D\n\n## A\n\nkeep\n\nGONE\n\nkeep2\n")
        subprocess.run([*MD_TOOLS, "subst", str(f), "GONE", ""], check=True)
        assert "\n\n\n" not in f.read_text()


class TestDotRootLocator:
    """"." addresses the document's own root node. It used to resolve only on the
    SELECT/TRANSFORM code path, so `copy` documented it while `read` and
    `body-line-append` rejected it with an error that showed a path looking like a
    typo — meaning a caller had to look up each file's title just to prepend a line."""

    @pytest.fixture
    def doc(self, tmp_path):
        f = tmp_path / "dot.md"
        f.write_text("# My Title\n\nPreamble line.\n\n## Section A\n\nBody A.\n")
        return f

    def test_read_dot(self, doc):
        r = subprocess.run([*MD_TOOLS, "read", str(doc), "."],
                           capture_output=True, text=True, check=True)
        assert "My Title" in r.stdout and "Section A" in r.stdout

    def test_list_dot(self, doc):
        r = subprocess.run([*MD_TOOLS, "list", str(doc), "."],
                           capture_output=True, text=True, check=True)
        assert "Section A" in r.stdout

    def test_body_line_append_dot_top_prepends_to_preamble(self, doc):
        """The banner case: a line at the top of the file's own body, above the
        first section but below the title."""
        subprocess.run([*MD_TOOLS, "body-line-append", str(doc), ".", "--top",
                        "BANNER"], check=True)
        text = doc.read_text()
        assert "BANNER" in text
        assert text.index("BANNER") < text.index("Preamble line.")
        assert text.index("# My Title") < text.index("BANNER")

    def test_body_line_append_dot_bottom(self, doc):
        subprocess.run([*MD_TOOLS, "body-line-append", str(doc), ".", "TRAILER"],
                       check=True)
        text = doc.read_text()
        assert "TRAILER" in text
        assert text.index("TRAILER") < text.index("## Section A")


class TestDeleteDotEmptiesFile:
    """delete "." removes the document root, which empties the file. That is
    allowed, but the ordinary success line reads identically to a one-section
    delete, so it is announced with a restore command that actually works."""

    @pytest.fixture
    def doc(self, tmp_path):
        f = tmp_path / "todelete.md"
        f.write_text("# Title\n\nPreamble.\n\n## A\n\nBody A.\n\n## B\n\nBody B.\n")
        return f

    def test_delete_dot_warns_and_restore_line_round_trips(self, doc):
        original = doc.read_text()
        r = subprocess.run([*MD_TOOLS, "delete", str(doc), "."],
                           capture_output=True, text=True, check=True)
        assert "EMPTIED" in r.stderr
        assert "## A" not in doc.read_text()

        # The printed recovery command must name a real backup holding the
        # pre-delete content — a path that does not restore is worse than none.
        line = [ln for ln in r.stderr.splitlines() if "Restore with:" in ln]
        assert line, r.stderr
        backup = line[0].split("cp '", 1)[1].split("'", 1)[0]
        assert os.path.exists(backup)
        assert Path(backup).read_text() == original

    def test_ordinary_delete_does_not_warn(self, doc):
        r = subprocess.run([*MD_TOOLS, "delete", str(doc), "A"],
                           capture_output=True, text=True, check=True)
        assert "EMPTIED" not in r.stderr
        assert "## B" in doc.read_text()



class TestInsertCollisionMerges:
    """insert routes placement through the shared EMIT back-end, so a
    marker-transparent title collision MERGES exactly as it does for
    copy / move / extract / replace.

    Before this, insert was the only placing verb that appended a duplicate — and
    the result was unrecoverable: no locator distinguishes two identical sibling
    titles, so neither node could afterwards be read, renamed, moved or deleted.
    """

    @staticmethod
    def _collide_file(tmp_path):
        f = tmp_path / "collide.md"
        f.write_text(
            "# Root\n\n## Parent\n\n### Alpha\n\nexisting body.\n\n#### Kid A\n\na.\n"
        )
        return f

    def test_colliding_title_merges_instead_of_duplicating(self, tmp_path):
        f = self._collide_file(tmp_path)
        subprocess.run(
            [*MD_TOOLS, "insert", str(f), "Parent", "# Alpha\n\n#### Kid B\n\nb.\n"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(f.read_text())
        parent = tree.root.children[0].children[0]
        alphas = [c for c in parent.children if c.title == "Alpha"]
        assert len(alphas) == 1, "collision must merge, not duplicate"
        # children union: the pre-existing child survives and the incoming one joins
        assert [c.title for c in alphas[0].children] == ["Kid A", "Kid B"]

    def test_merged_node_stays_addressable(self, tmp_path):
        """The failure this prevents: two identical siblings are unaddressable."""
        f = self._collide_file(tmp_path)
        subprocess.run(
            [*MD_TOOLS, "insert", str(f), "Parent", "# Alpha\n\n#### Kid B\n\nb.\n"],
            check=True,
        )
        r = subprocess.run([*MD_TOOLS, "read", str(f), "Alpha"],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"merged node must resolve, got: {r.stderr}"

    def test_merge_is_reported_not_silent(self, tmp_path):
        """A merge changes an existing section, so it must say so."""
        f = self._collide_file(tmp_path)
        r = subprocess.run(
            [*MD_TOOLS, "insert", str(f), "Parent", "# Alpha\n\n#### Kid B\n\nb.\n"],
            capture_output=True, text=True, check=True,
        )
        assert "MERGED" in r.stdout

    def test_append_policy_restores_duplicate_behaviour(self, tmp_path):
        """--append is the opt-in escape hatch for the pre-merge behaviour."""
        f = self._collide_file(tmp_path)
        subprocess.run(
            [*MD_TOOLS, "insert", str(f), "Parent", "# Alpha\n\nsecond.\n", "--append"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(f.read_text())
        parent = tree.root.children[0].children[0]
        assert len([c for c in parent.children if c.title == "Alpha"]) == 2

    def test_non_colliding_title_still_places_fresh(self, tmp_path):
        """The common case is unchanged — a new title is placed, not merged."""
        f = self._collide_file(tmp_path)
        r = subprocess.run(
            [*MD_TOOLS, "insert", str(f), "Parent", "# Beta\n\nnew.\n"],
            capture_output=True, text=True, check=True,
        )
        assert "Inserted section 'Beta'" in r.stdout
        assert "MERGED" not in r.stdout
        tree = MarkdownTree()
        tree.parse(f.read_text())
        parent = tree.root.children[0].children[0]
        assert [c.title for c in parent.children] == ["Alpha", "Beta"]

    def test_collision_match_is_marker_transparent(self, tmp_path):
        """Matching ignores the trailing marker zone, as elsewhere in the tool."""
        f = tmp_path / "marked.md"
        f.write_text("# Root\n\n## Parent\n\n### Alpha  [queued] [v1]\n\nx.\n")
        subprocess.run(
            [*MD_TOOLS, "insert", str(f), "Parent", "# Alpha\n\n#### Kid\n\nk.\n"],
            check=True,
        )
        tree = MarkdownTree()
        tree.parse(f.read_text())
        parent = tree.root.children[0].children[0]
        assert len(parent.children) == 1
        # the existing heading's markers are preserved by the merge
        assert parent.children[0].title == "Alpha  [queued] [v1]"
