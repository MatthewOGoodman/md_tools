#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Markdown Manager - Section manipulation tool for CLAUDE.md files

Uses FIXED version of markdown-parser-py (respects code fences) for hierarchical section operations:
- Read: Print section content to stdout (read-only — use this to inspect sections)
- List: Display document outline structure (ALWAYS START HERE)
- Map: Display document outline with line counts (quantitative analysis)
- Reorder: Reorder sibling sections at same level (partial list OK, rest follow)
- Move: Move one or more sections (:,:-separated) between existing files (target must exist; use copy for new files)
- Extract: Cut section to new file (destructive — removes from source; wraps copy + delete/reshape)
- Extract-abridge: Copy a section to a file (full), then strip the source to a heading skeleton (wraps copy + reshape)
- Reshape: Apply SELECT/TRANSFORM flags to a section IN PLACE (strip bodies/markers, flatten, prune via keep/omit)
- Abridge: Strip a section to a heading skeleton in place (convenience alias for reshape --strip-all-body-text)
- Delete: Remove section from file
- Insert: Add a new section under a parent (preferred for TODOs/threads; appends last by default, --after-sibling/--before-sibling for position, --state to compose a [tag], --stdin for body)
- Convert: Turn in-body structure into child headings — `- ` bullets (default) or **Bold:** lines (--from bold); --body-marker, --level, --checkbox-to-trailing, --dry-run
- Subst: LITERAL fixed-string find/replace — `subst FILE OLD NEW` (regex metachars in OLD/NEW are literal; the safe default for prose edits); --regex for Python regex; --all, --ignore-case, --section, --dry-run
- Gsub: Python-REGEX find/replace — `gsub FILE PATTERN REPL` (= subst --regex; REPL supports \1 backrefs); --all, --ignore-case, --section, --dry-run
- Body-line-append: Append a body line/bullet to a section's body (bottom, or --top); for a child heading use Insert (alias: item-append)
- Line-append: Append a raw line to a flat append-only file (e.g. ACTIVITY_LOG.md) via O_APPEND
- Rename: Retitle a section in place (body + child subsections preserved)
- Cleanup-backups: Delete all but most recent backup per file (datestamped backups)

CONCURRENT-WRITE SAFETY:
    Every write verb holds an exclusive advisory flock (fcntl) on the data file's
    PARENT DIRECTORY for the WHOLE read-modify-write and commits via temp-file +
    os.replace(). Two md_tools processes editing the same shared file (STATUS.md,
    CLAUDE.md, the user-global ACTIVITY_LOG.md) are serialized — no silent lost
    updates — and a crash mid-write cannot leave a truncated file. The directory
    is the coordination token, so NO lock files are ever created. POSIX-only
    (fcntl): on a platform without it, or with MD_TOOLS_LOCK=0, the lock degrades
    to a no-op while atomic writes still apply.

SETUP (one-time):
    conda create -n claude_tools python=3.13
    conda activate claude_tools
    pip install markdown-parser-py
    conda deactivate
    chmod +x ~/.claude/md_tools

    Optional: Add to ~/.zshenv for convenience:
        export PATH="$HOME/.claude:$PATH"

Usage:
    md_tools read SOURCE SECTION
    md_tools list FILE [SECTION|--path=SECTION] [--max-depth=N]
    md_tools list-paths FILE [--max-depth=N]
    md_tools map FILE [SECTION|--path=SECTION] [--max-depth=N]
    md_tools reorder FILE "Section1:,:Section2:,:..." [--parent=PATH]
    md_tools move SOURCE SECTION[:,:SECTION2:,:...] [--target=FILE] [--parent=PATH] [--after-sibling=NAME|^|$] [--flatten]
    md_tools convert FILE [SECTION] [--from bullets|bold] [--body-marker=STR] [--level=N] [--checkbox-to-trailing] [--dry-run]
    md_tools copy SOURCE SECTION OUTPUT [--parent=PATH] [--after-sibling=NAME|^] [--on-conflict=merge|clobber-body|full-subtree|append] [--append]
    md_tools extract SOURCE SECTION OUTPUT [--parent=PATH] [--after-sibling=NAME|^] [--on-conflict=...|--append]
    md_tools extract-abridge SOURCE SECTION OUTPUT
    md_tools reshape FILE SECTION [--strip-all-body-text|--keep-sections=...|--omit-sections=...|--flatten|--strip-markers]
    md_tools abridge FILE SECTION
    md_tools delete FILE SECTION
    md_tools insert FILE TITLE CONTENT [--parent=PATH] [--after-sibling=NAME|^ | --before-sibling=NAME] [--state=TAG] [--stdin]
    md_tools subst FILE OLD NEW [--regex] [--all] [--ignore-case] [--section=PATH] [--dry-run]   # LITERAL by default (the safe choice for prose); --regex for Python regex
    md_tools gsub FILE PATTERN REPL [--all] [--ignore-case] [--section=PATH] [--dry-run]   # Python-REGEX find/replace (= subst --regex; REPL supports \1)
    md_tools body-line-append FILE SECTION CONTENT [--top] [--stdin]   # appends a body line/bullet (alias: item-append)
    md_tools line-append FILE LINE [--stdin]
    md_tools rename FILE SECTION --to "New Title"
    md_tools cleanup-backups [DIRECTORY]
    md_tools test

    Paths use :/: as hierarchy separator (e.g., "Parent:/:Child:/:Grandchild").
    Multiple paths use :,: as list separator (e.g., "Section A:,:Section B").

SELECT → TRANSFORM (read / copy / extract / move / reshape):
    The emit verbs share a flag set that builds a re-leveled VIEW of a node-set in
    one pass. With any of these flags the SECTION positional is the HEAD ("." = the
    file's H1 root); without them each verb keeps its native single-section behavior.
      SELECT     --keep-sections "A:,:B:/:C"  (allowlist, relative paths kept from the
                   head down; naming a node keeps its whole subtree)
                 --omit-sections "A:,:B"      (denylist; the inverse of keep)
                 --children [--depth N]       (lift the head's depth-N children)
      TRANSFORM  --flatten · --strip-markers · --strip-{target,child,all}-body-text
    On read/copy the view is emitted; on extract/move the selected content is removed
    from source (head + complement retained). reshape applies the same flags IN PLACE.

MAX-DEPTH GUIDANCE:
    The default (unlimited) is correct for 1st pass familiarization — trust it.
    After familiarization, use --path or read to target specific subtrees and save context.
    The # root heading consumes depth level 1, so --max-depth 2 only shows ## headings,
    hiding ### subsections which are usually the most useful working level.
    If you must limit depth, use --max-depth 3 or higher unless you specifically
    need only top-level (##) headings (e.g., scanning document skeleton).

BACKUP SAFETY:
    All destructive operations (extract, delete, reshape, move, convert, subst, gsub,
    body-line-append, rename) automatically create timestamped backups in ~/.claude/backups/md_tools/
    before modifying files. (line-append is pure O_APPEND — no read, no backup.) Use cleanup-backups to
    remove old backups (keeps most recent per file). Default cleanup directory: ~/.claude/backups/md_tools

IMPLEMENTATION NOTES:
    Self-contained script with inline fixed MarkdownTree parser.

    Based on markdown-parser-py with CRITICAL FIX:
    - Original package treats '# comments' inside ``` code blocks as headings
    - This version filters heading matches inside triple-backtick fenced code blocks
    - Uses _find_code_fence_ranges() to detect code block boundaries
    - Skips heading regex matches that fall within code fence ranges

    Uses MarkdownNode from markdown-parser-py package (installed in claude_tools env).
    Shebang points to claude_tools Python - no 'conda activate' needed.
    Works in non-interactive shells (Claude Code Bash tool) automatically.

HIERARCHICAL PATHS:
    Sections are referenced by :/:-separated paths from root:
    - "Parent" - top-level section
    - "Parent:/:Child" - subsection under Parent
    - "Parent:/:Child:/:Grandchild" - nested subsection

    The :/:separator was chosen because it never appears in natural language,
    programming languages, or markdown headers. Unlike . (collides with version
    numbers, file extensions), :: (R namespace syntax), or : (common in headers).

PATH RESOLUTION (any SECTION argument):
    A path is a partial locator: a contiguous, right-anchored slice of a
    section's ancestor chain ending at the target. You may omit leading levels
    (the H1 root is always droppable, so "ROOT:/:X" == "X") and each component
    may be a case-insensitive prefix (or, failing that, substring) of the real
    heading. Trailing state tags ("  [ ]", "  [implement]", "  [v1]", "*[ ]")
    are ignored for prefix/substring matching, so a stale or omitted tag still
    matches; give the exact full title to address a section by its tag.
    Exactly one match resolves (the canonical path is echoed to stderr); two or
    more print "Ambiguous match" with candidates and exit 1 — add an ancestor
    (e.g. "Parent:/:leaf") or paste the exact full path to disambiguate.
    Skipping a NON-root middle level is a no-match by design.
"""

import sys
import argparse
import os
import time
import tempfile
import regex as re
from contextlib import contextmanager, ExitStack
from pathlib import Path
from markdown_parser.node import MarkdownNode
from md_tools_backup import create_backup, cleanup_backups

# fcntl is POSIX-only. On a platform without it (e.g. Windows) md_tools still
# RUNS — atomic_write is cross-platform — and the advisory locking simply
# degrades to a no-op. _LOCKING_ENABLED is the single opt-out gate: it is on by
# default where fcntl exists, off where it doesn't, and `MD_TOOLS_LOCK=0`
# disables it on a POSIX host. (A v2 can grow this one seam into a richer
# opt-in/out without touching any lock call site.)
try:
    import fcntl
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - only reached on non-POSIX platforms
    fcntl = None
    _HAVE_FCNTL = False

_LOCKING_ENABLED = _HAVE_FCNTL and os.environ.get("MD_TOOLS_LOCK", "1") != "0"


# ============================================================================
# Concurrent-write hardening
# ----------------------------------------------------------------------------
# Two md_tools processes editing the same shared file (STATUS.md, CLAUDE.md, the
# user-global ACTIVITY_LOG.md) used to be able to interleave a read-modify-write
# and silently drop one update — the Bash read-modify-write path has no harness
# CAS. Every public write verb now (1) holds an exclusive advisory flock for the
# WHOLE read-modify-write, so the second writer waits instead of clobbering, and
# (2) commits via a temp-file + os.replace() so a crash mid-write can never leave
# a truncated file. Zero change to agent-visible behavior.
# ============================================================================

_LOCK_TIMEOUT = 30.0  # seconds; bounded so a wedged holder raises instead of hanging forever


def _lock_dir_for(path):
    """Return the directory whose flock guards writes to `path`.

    We lock the data file's PARENT DIRECTORY — a stable object that already
    exists and is never renamed — NOT the data file (atomic_write swaps its inode,
    so a lock held on it would not coordinate with a writer that re-opens the
    path) and NOT a per-file lock file (which would accumulate on disk). So no
    lock file is ever created; the directory IS the coordination token.

    The path is realpath-resolved first so that a writer reaching the file via a
    symlink and a writer reaching it via the real path lock the SAME directory
    (abspath would lock the symlink's own parent, defeating serialization).
    """
    return os.path.dirname(os.path.realpath(path)) or "."


@contextmanager
def _dir_lock(directory, timeout=_LOCK_TIMEOUT, poll=0.05):
    """Hold an exclusive advisory flock on a directory fd for the duration.

    Bounded wait via LOCK_NB polling so a stuck holder raises TimeoutError
    instead of hanging. Kernel-held; auto-released if the holding process dies.
    If the directory can't be opened to lock it, degrade to a no-op rather than
    fail the operation — the real write surfaces any genuine error itself.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        yield
        return
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"md_tools: could not acquire write lock for {directory} "
                        f"within {timeout:g}s (held by another process?)")
                time.sleep(poll)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


@contextmanager
def multi_file_lock(*paths, timeout=_LOCK_TIMEOUT):
    """Serialize writes to the given paths by flocking their parent directories.

    Locks each DISTINCT directory once (a same-directory multi-file op locks it
    once) in sorted realpath order, so two processes locking the same set can
    never deadlock. A no-op when locking is disabled (no fcntl, or
    MD_TOOLS_LOCK=0) — atomic_write still protects file integrity on its own.
    """
    if not _LOCKING_ENABLED:
        yield
        return
    dirs = {}
    for p in paths:
        if p is None:
            continue
        d = _lock_dir_for(p)
        dirs.setdefault(os.path.realpath(d), d)
    with ExitStack() as stack:
        for rp in sorted(dirs):
            stack.enter_context(_dir_lock(dirs[rp], timeout=timeout))
        yield


@contextmanager
def file_lock(path, timeout=_LOCK_TIMEOUT):
    """Exclusive advisory lock guarding writes to one file (via its parent dir)."""
    with multi_file_lock(path, timeout=timeout):
        yield


def atomic_write(path, text):
    """Write text to path atomically: temp file in the same dir + os.replace().

    os.replace is atomic on POSIX, so a concurrent reader sees either the old or
    the new file, never a torn/truncated one. fsync before the swap for durability.
    The temp file is created in the target's directory so the rename stays on one
    filesystem; it is cleaned up on any failure before re-raising.

    The path is realpath-resolved FIRST so a symlinked target is written THROUGH:
    os.replace(tmp, real) overwrites the real file and leaves the symlink intact.
    Without this, replacing the symlink path itself swaps the link for a regular
    file, detaching it from its target (e.g. a dotfiles-tracked config symlink).
    """
    real = os.path.realpath(path)
    d = os.path.dirname(real) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(real) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, real)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def commit(path, text):
    """Shared write back-end for every section verb: backup-if-exists, normalize the
    trailing newline, then atomic_write.

    - Backs up an EXISTING target before overwriting it (so copy/extract gain a backup
      when they overwrite a populated output, matching every in-place verb). A fresh
      target (the common copy-to-new-file case) is NOT backed up. create_backup dedups
      per-process, so a verb that already backed up earlier in the call is a no-op here.
    - Normalizes to exactly ONE trailing newline (the canonical shape; a fresh
      copy/extract output previously got none, an existing target kept its own).
    - atomic_write is realpath-resolved, so a symlinked target is written THROUGH.

    No lock here: the *_bare caller runs under the public wrapper's (or composer's) flock.
    """
    if os.path.exists(path):
        create_backup(path, 'md_tools')
    text = (text.rstrip('\n') + '\n') if text.strip() else '\n'
    atomic_write(path, text)


def normalize_blank_runs(text):
    """Collapse runs of 2+ consecutive blank lines to a SINGLE blank line, OUTSIDE
    code fences (blank runs inside ``` fences are preserved verbatim). Idempotent.

    The tree.dump() write paths already emit exactly one blank line between blocks, so
    a section-scoped op is canonical by construction. This helper enforces the SAME
    invariant on the RAW whole-file write paths (gsub/subst), which substitute body text
    directly without re-serializing — e.g. a gsub that deletes lines can otherwise leave a
    stray multi-blank run. Fence state is tracked by toggling on lines that start with ```.
    """
    out = []
    in_fence = False
    blank_run = 0
    for ln in text.split("\n"):
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            blank_run = 0
            out.append(ln)
        elif not in_fence and ln.strip() == "":
            blank_run += 1
            if blank_run == 1:        # keep the first blank, drop the rest of the run
                out.append(ln)
        else:
            blank_run = 0
            out.append(ln)
    return "\n".join(out)


def _locked(write_targets, worker, *args, **kwargs):
    """Run a *_bare worker while holding exclusive locks on its write target(s)."""
    with multi_file_lock(*write_targets):
        return worker(*args, **kwargs)


# ============================================================================
# Fixed MarkdownTree class (respects code fences)
# Based on markdown-parser-py with fix for ignoring headings inside ``` blocks
# ============================================================================

FRONTMATTER_FENCE = "---"
_BOM = "﻿"


def _frontmatter_split(text):
    """Split a leading YAML frontmatter block off as an opaque, byte-verbatim prefix.

    Frontmatter is present iff the first line (after an optional BOM) is exactly
    `---` AND a later line is exactly `---`. The returned raw_prefix is reconstructed
    by character-offset slice (byte-exact — never re-joined), and absorbs any blank
    lines immediately after the closing fence so the conventional gap before the first
    heading is not dropped by the body parser. Frontmatter is held off the markdown
    tree entirely so a `# comment` inside YAML is never misparsed as a heading.

    Returns (raw_prefix, remainder). No frontmatter -> ("", text). An unclosed leading
    fence is NOT frontmatter -> ("", text) (the content is preserved as body).
    """
    bom = _BOM if text[:1] == _BOM else ""
    probe = text[len(bom):]
    lines = probe.split("\n")
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return ("", text)
    for i in range(1, len(lines)):
        if lines[i].strip() == FRONTMATTER_FENCE:
            off = sum(len(l) + 1 for l in lines[:i + 1])  # through closing fence + its \n
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":  # absorb trailing blank run
                off += len(lines[j]) + 1
                j += 1
            off = min(off, len(probe))  # clamp: closing fence may lack a final newline
            return (bom + probe[:off], probe[off:])
    return ("", text)


class MarkdownTree:
    HEADER_REGEX = re.compile(r"^(#{1,6})[ \t]+(.+)$", re.MULTILINE)
    CODE_FENCE_REGEX = re.compile(r"^```", re.MULTILINE)

    def __init__(self):
        self.root = MarkdownNode(0, "ROOT")
        # Opaque leading frontmatter + trailing-newline run, held off-tree and
        # reattached verbatim by dump(). Defaults are load-bearing: fresh output
        # trees (copy/extract) dump WITHOUT ever parsing and rely on these.
        self.frontmatter_raw = ""
        self.trailing = ""

    def _find_code_fence_ranges(self, text: str) -> list[tuple[int, int]]:
        """Find all (start, end) positions of ``` code blocks."""
        ranges = []
        fences = [m.start() for m in self.CODE_FENCE_REGEX.finditer(text)]

        # Pair up opening and closing fences
        for i in range(0, len(fences) - 1, 2):
            ranges.append((fences[i], fences[i + 1]))

        return ranges

    def _is_inside_code_fence(self, pos: int, fence_ranges: list[tuple[int, int]]) -> bool:
        """Check if position is inside any code fence range."""
        for start, end in fence_ranges:
            if start < pos < end:
                return True
        return False

    def parse(self, markdown_text: str):
        """Parse markdown text into tree structure, ignoring headings in code blocks."""
        # Reset per-parse (belt-and-suspenders; no verb re-parses one instance) then
        # peel the opaque frontmatter prefix off so the heading parser never sees it,
        # and capture the trailing-newline run so dump() can reattach it byte-exact.
        self.frontmatter_raw = ""
        self.trailing = ""
        self.frontmatter_raw, markdown_text = _frontmatter_split(markdown_text)
        self.trailing = markdown_text[len(markdown_text.rstrip("\n")):]

        fence_ranges = self._find_code_fence_ranges(markdown_text)

        positions = []
        for match in self.HEADER_REGEX.finditer(markdown_text):
            # Skip if this heading is inside a code fence
            if not self._is_inside_code_fence(match.start(), fence_ranges):
                positions.append(
                    (
                        match.start(),
                        match.end(),
                        len(match.group(1)),
                        match.group(2).strip(),
                    )
                )

        if not positions:
            self.root.add_content(markdown_text)
            return

        # Capture any preamble before the first heading (previously dropped — data loss).
        preamble = markdown_text[:positions[0][0]]
        if preamble.strip():
            self.root.add_content(preamble)

        nodes = []
        for idx, (start, end, level, title) in enumerate(positions):
            start_of_next = None
            if idx < len(positions) - 1:
                start_of_next = positions[idx+1][0]
            content = markdown_text[end:start_of_next].strip("\n")
            nodes.append((level, title, content))

        stack = [self.root]
        for level, title, content in nodes:
            if title is not None:
                node = MarkdownNode(level, title)
                while stack[-1].level >= level:
                    stack.pop()
                stack[-1].add_child(node)
                stack.append(node)
                if content:
                    node.add_content(content)
            else:
                if content:
                    stack[-1].add_content(content)

    def find_node_by_path(self, path: str) -> MarkdownNode | None:
        """Find a node by :/:-separated path like 'Introduction:/:Installation'."""
        parts = path.split(":/:")

        current_nodes = [self.root]
        for part in parts:
            next_level_nodes = []
            for node in current_nodes:
                found = None
                for child in node.children:
                    if child.title == part:
                        found = child
                        break
                if found:
                    next_level_nodes = [found]
                    break
            if not next_level_nodes:
                return None
            current_nodes = next_level_nodes
        return current_nodes[0] if current_nodes else None

    def remove_section(self, path: str) -> bool:
        """Remove a section by path. Returns True if successful."""
        node = self.find_node_by_path(path)
        if node and node.parent:
            node.parent.remove_child(node)
            return True
        return False

    def add_section(self, parent_path: str, title: str, content="") -> MarkdownNode | None:
        """Add a new section. If parent_path is empty/ROOT, adds at root level."""
        if parent_path in ("", "ROOT"):
            parent_node = self.root
        else:
            parent_node = self.find_node_by_path(parent_path)

        if parent_node is None:
            return None

        new_level = parent_node.level + 1
        new_node = MarkdownNode(new_level, title)
        if content:
            new_node.add_content(content)
        parent_node.add_child(new_node)
        return new_node

    def dump(self) -> str:
        """Generate full markdown text from the tree."""
        # Reattach the opaque frontmatter prefix + trailing-newline run verbatim.
        return self.frontmatter_raw + self.root.dump() + self.trailing

    def visualize(self, path=None, max_depth=None):
        """Print heading hierarchy as a tree.

        Args:
            path: Optional section path to display (e.g., "Parent:/:Child")
            max_depth: Optional maximum depth to display

        Returns:
            bool: True if successful, False if path not found
        """
        if path:
            node, error_printed = find_node_with_suggestions(self, path)
            if node is None:
                if not error_printed:
                    print(f"Error: Path '{path}' not found", file=sys.stderr)
                return False
            start_node = node
        else:
            start_node = self.root

        print_tree_recursive(start_node, current_depth=0, max_depth=max_depth)
        return True

    def attach_subtree(self, target_path: str, source_tree: "MarkdownTree",
                       source_path: str | None = None, max_level: int = 6):
        """Attach subtree from source_tree under target_path with level adjustment."""
        if target_path in ("", "ROOT"):
            parent = self.root
        else:
            parent = self.find_node_by_path(target_path)
        if parent is None:
            return []

        if source_path in (None, "", "ROOT"):
            source_nodes = source_tree.root.children
            per_node = True
        else:
            node = source_tree.find_node_by_path(source_path)
            if node is None or node.level == 0:
                return []
            source_nodes = [node]
            per_node = False
            base_delta = (parent.level + 1) - node.level

        attached = []
        for sn in source_nodes:
            delta = (parent.level + 1) - sn.level if per_node else base_delta
            clone = sn.copy_with_level_delta(delta, max_level=max_level)
            parent.add_child(clone)
            attached.append(clone)
        return attached


# ============================================================================
# Tree Display Helper Function
# ============================================================================


def print_tree_recursive(node, indent="", last=True, current_depth=0, max_depth=None):
    """Print tree with optional depth limit.

    Args:
        node: MarkdownNode to print
        indent: Current indentation string
        last: Whether this is the last child at current level
        current_depth: Current depth in tree (0 = root)
        max_depth: Maximum depth to display (None = unlimited)
    """
    prefix = indent + ("└── " if last else "├── ")
    if node.level > 0:
        print(prefix + f"{'#' * node.level} {node.title}")

    # Check depth limit
    if max_depth is not None and current_depth >= max_depth:
        return

    for i, child in enumerate(node.children):
        next_indent = indent + ("    " if last else "│   ")
        print_tree_recursive(child, next_indent,
                             i == len(node.children) - 1,
                             current_depth + 1, max_depth)


# ============================================================================
# Helper Functions
# ============================================================================


def detect_single_root(tree):
    """Detect if tree has a single root heading and return its title.

    Args:
        tree: MarkdownTree object

    Returns:
        str or None: Root heading title if single root exists, None otherwise
    """
    if len(tree.root.children) == 1:
        return tree.root.children[0].title
    return None



def prepend_root_prefix(path, root_prefix):
    """Prepend root prefix to path if needed.

    Args:
        path: Section path (user input)
        root_prefix: Root heading title or None

    Returns:
        str: Path with root prefix prepended if needed
    """
    if not root_prefix:
        return path
    if path.startswith(root_prefix + ":/:") or path == root_prefix:
        return path
    return f"{root_prefix}:/:{path}"


def collect_all_paths(node, prefix="", max_depth=None, current_depth=0):
    """Recursively collect all valid :/:-separated paths in the tree.

    Args:
        node: MarkdownNode to start from (usually tree.root)
        prefix: Path prefix built so far
        max_depth: Optional maximum depth to recurse
        current_depth: Current recursion depth

    Returns:
        list[str]: All valid :/:-separated paths
    """
    paths = []
    for child in node.children:
        path = f"{prefix}:/:{child.title}" if prefix else child.title
        paths.append(path)
        if max_depth is None or current_depth < max_depth:
            paths.extend(collect_all_paths(child, path, max_depth, current_depth + 1))
    return paths


def suggest_matches(query, all_paths, max_suggestions=5):
    """Given a failed path query, return ranked suggestions from all valid paths.

    Priority:
    1. Full query substring match (case-insensitive)
    2. Leaf component substring match (query's last :/: component appears in any path)
    3. Leaf-name exact match (last :/: component matches any node's leaf title)

    Args:
        query: The failed path string
        all_paths: List of all valid :/:-separated paths
        max_suggestions: Maximum number of suggestions to return

    Returns:
        list[str]: Ranked suggestion paths (up to max_suggestions)
    """
    query_lower = query.lower()
    query_leaf = query.split(":/:")[-1].lower()
    seen = set()

    def add_unique(results, candidates):
        for c in candidates:
            if c not in seen:
                seen.add(c)
                results.append(c)

    combined = []

    # Full query substring matches
    add_unique(combined, [p for p in all_paths if query_lower in p.lower()])

    # Leaf component substring matches (query's last component appears anywhere in path)
    add_unique(combined, [p for p in all_paths if query_leaf in p.lower()])

    # Leaf-name exact match (any path whose leaf title matches query's leaf)
    add_unique(combined, [p for p in all_paths if p.split(":/:")[-1].lower() == query_leaf])

    return combined[:max_suggestions]


def format_path_error(query, all_paths, file_path=None):
    """Print structured error message with suggestions to stderr.

    Args:
        query: The failed path string
        all_paths: List of all valid paths
        file_path: Optional file path for the hint message
    """
    print(f'Error: No exact match for path: "{query}"', file=sys.stderr)

    suggestions = suggest_matches(query, all_paths)
    if suggestions:
        print("\nDid you mean:", file=sys.stderr)
        for s in suggestions:
            print(f"  - {s}", file=sys.stderr)

    # Show top-level sections
    top_level = [p for p in all_paths if ":/:" not in p]
    if top_level:
        print("\nTop-level sections:", file=sys.stderr)
        for s in top_level:
            print(f"  - {s}", file=sys.stderr)

    hint_file = file_path or "FILE"
    print(f"\nRun 'md_tools list-paths {hint_file}' to see all valid paths.", file=sys.stderr)


def _collect_node_paths(node, prefix=()):
    """Yield (node, (title, ...)) for every node below the level-0 root.

    The component tuple includes the H1 (it is a child of the invisible
    level-0 root). Mirrors collect_all_paths()'s walk but pairs each path
    with its node, so a resolved match maps straight back to the node.
    """
    for child in node.children:
        parts = prefix + (child.title,)
        yield (child, parts)
        yield from _collect_node_paths(child, parts)


_LEADING_DECORATION = re.compile(r'^\s*\*?\[[^\]]*\]\s+')
_TRAILING_DECORATION = re.compile(r'(?:\s+\*?(?:\[[^\]]*\]|\([^)]*\)))+\s*$')

# Shared --stdin help. It is a SHELL-QUOTING escape hatch, not a second content
# mode: in a normal double-quoted argument the shell executes backticks and
# $(...) before md_tools ever sees the text, and silently substitutes the
# command's output — so a payload mentioning `md_tools list` loses that span and
# still reports success. Content is handled identically whichever way it arrives.
_STDIN_HELP = ("Read content from stdin. Use a QUOTED heredoc (<<'EOF') for any content "
               "containing backticks, $(...), $VAR or ! — in a normal shell argument those "
               "execute and the text is silently replaced by the command's output. Not a "
               "different insertion mode; content is handled identically either way.")


_MARKER_GROUP_RE = re.compile(r'\*?(?:\[[^\]]*\]|\([^)]*\))')


def _marker_groups(title):
    """Split a heading into its stem and its ORDERED trailing marker groups.

    'name  *[implement] [v1] (#)'    -> ('name', ['*[implement]', '[v1]', '(#)'])
    'name (what it is)  [queued]'    -> ('name (what it is)', ['[queued]'])
    'name  (after: x)'               -> ('name', ['(after: x)'])
    No marker zone -> (title, []).

    The canonical marker order is `[state] [tier] (#)`, so a paren group can be
    a marker only AFTER a bracket has opened the zone — a paren that precedes
    the first bracket is part of the name. With no bracket in the zone at all,
    every trailing paren is a marker (a bare `(#)` pin or `(after: x)` hint).
    This is the counterpart to _strip_state_tags, which only ever discards the
    whole zone; addressing one marker needs the zone as parts.
    """
    m = _TRAILING_DECORATION.search(title)
    if not m:
        return title.rstrip(), []
    groups = list(_MARKER_GROUP_RE.finditer(title, m.start()))
    first_bracket = next((g for g in groups if g.group(0).lstrip('*').startswith('[')), None)
    if first_bracket is not None:
        groups = [g for g in groups if g.start() >= first_bracket.start()]
    zone_start = groups[0].start() if groups else m.start()
    return title[:zone_start].rstrip(), [g.group(0) for g in groups]


def _join_markers(stem, groups):
    """Rebuild a heading in canonical marker spacing: two spaces before the
    first marker, one space between the rest."""
    return f"{stem}  {' '.join(groups)}" if groups else stem


def _set_bracket_marker(title, index, value):
    """Replace the index-th BRACKET group of a heading's marker zone, appending
    one when the heading has exactly that many brackets already.

    Addresses by POSITION, not vocabulary. Bracket order is fixed by convention
    (state first, depth-tier second), so a caller names a slot and md_tools
    places the text verbatim — nothing is checked against a controlled
    vocabulary, which belongs to whichever consumer owns that vocabulary rather
    than to a general markdown tool.

    A provisional '*' already on the target group is preserved. Parens are never
    touched: they are positionally unambiguous inside one heading but carry
    different meanings in different sections, so they get no slot flag.

    Returns the new title, or None when the requested slot would leave a gap
    (e.g. setting the second bracket on a heading that has none).
    """
    tag = value.strip()
    if not (tag.startswith('[') and tag.endswith(']')):
        tag = f"[{tag if tag else ' '}]"

    stem, groups = _marker_groups(title)
    brackets = [i for i, g in enumerate(groups) if g.lstrip('*').startswith('[')]

    if index < len(brackets):
        at = brackets[index]
        star = '*' if groups[at].startswith('*') else ''
        groups[at] = f"{star}{tag}"
    elif index > len(brackets):
        return None
    elif brackets:
        # Exactly one slot past the end: place it after the last bracket, which
        # keeps every bracket ahead of any trailing paren.
        groups.insert(brackets[-1] + 1, tag)
    else:
        groups.insert(0, tag)
    return _join_markers(stem, groups)


def _strip_state_tags(title):
    """Strip the canonical marker decoration zone from a heading title.

    Trailing (canonical): one or more ' *?[...]' bracket and/or ' (...)'
    marker-paren groups at the end —
        'name  [implement] [v1]' / 'name  *[ ]' / 'name  (#)' /
        'name  (after: x)'  ->  'name'.
    Leading (insurance against a naive '- [ ]'->'#### [ ]' convert):
        '[ ] name' / '*[ ] name'  ->  'name'.
    Strips by decoration SYNTAX (optional-'*' + bracket or marker paren),
    not the marker VOCABULARY, so it survives vocab changes and tolerates
    either provisional-star placement (the canonical '*[ ]' prefix OR an
    incidental '[v1*]' inside).
    Markers are always row suffixes, so a trailing '(#...)' priority or
    '(after:...)' hint paren strips the same as a bracket — but a paren that
    PRECEDES the first bracket is part of the name and stays
    ('name (what it is)  [queued]' -> 'name (what it is)'; see _marker_groups).
    Used by the soft tiers (prefix/substring) of _locator_matches().
    """
    title = _marker_groups(title)[0]
    title = _LEADING_DECORATION.sub('', title)
    return title.strip()


def _locator_matches(locator_parts, full_parts, mode):
    """Contiguous, right-anchored match of a partial locator against a node's
    full component list (offset = len(full) - len(locator); the locator's LAST
    component always aligns with the target's OWN title).

    Per component:
        mode 'exact'     -> case-insensitive equality (NO strip — so a literal
                            'name [x]' still addresses a node by its tag)
        mode 'prefix'    -> full.startswith(loc), both _strip_state_tags-normalized
        mode 'substring' -> loc in full,          both _strip_state_tags-normalized
    """
    k = len(locator_parts)
    m = len(full_parts)
    if k == 0 or k > m:
        return False
    offset = m - k
    for i in range(k):
        loc = locator_parts[i]
        full = full_parts[offset + i]
        if mode != "exact":
            loc = _strip_state_tags(loc)
            full = _strip_state_tags(full)
        loc = loc.lower()
        full = full.lower()
        if mode == "exact":
            if full != loc:
                return False
        elif mode == "prefix":
            if not full.startswith(loc):
                return False
        else:  # substring
            if loc not in full:
                return False
    return True


def build_node_path(node):
    """Build :/:-separated path from node to root by walking parent chain.

    Converts a resolved node back to the exact path string that
    find_node_by_path() will match. Used to bridge fuzzy resolution
    (which returns a node) with exact-match APIs (which need path strings).

    Args:
        node: MarkdownNode to build path for

    Returns:
        str: :/:-separated path from root to node
    """
    parts = []
    current = node
    while current and current.level > 0:
        parts.append(current.title)
        current = current.parent
    return ":/:".join(reversed(parts))


def find_node_with_suggestions(tree, path, file_path=None):
    """Resolve a (possibly partial) locator to a unique node, or print a
    structured ambiguous / no-match error.

    A locator is a CONTIGUOUS, RIGHT-ANCHORED subset of a node's ancestor
    chain ending at the target: leading ancestor levels may be omitted and
    each component may be a prefix/substring of the real title. Cascade:

        0. exact rooted path (case-sensitive) via find_node_by_path()  [fast path]
        1-3. registry match, loosening exact (case-insensitive) -> prefix ->
             substring, all contiguous + right-anchored. prefix/substring make
             the canonical state-tag decoration transparent on both sides
             (see _strip_state_tags), so a stale/omitted '[state]' still matches.

    Exactly one match -> resolve; >1 at the tightest reached tier -> refuse with
    candidates (a looser tier is a superset and can't disambiguate); 0 at every
    tier -> structured suggestions. To force-disambiguate, re-run with the exact
    full path (it hits Step 0).

    Args:
        tree: MarkdownTree to search
        path: :/:-separated locator (full, partial, leaf name, or prefix)
        file_path: Optional file path for error messages

    Returns:
        tuple: (node, error_printed)
            - (node, False) on success (an info line is printed for a non-exact
              resolution; nothing printed for the Step 0 exact fast path)
            - (None, True) on failure (error + suggestions printed to stderr)
    """
    # Step 0: exact rooted path — fast path; preserves prior exact behavior and
    # is the re-run target for the exact-path disambiguation escape hatch.
    node = tree.find_node_by_path(path)
    if node is not None:
        return (node, False)

    registry = list(_collect_node_paths(tree.root))
    locator = [p for p in path.split(":/:") if p.strip()]
    if not locator:
        format_path_error(path, collect_all_paths(tree.root), file_path)
        return (None, True)

    # A leading component naming the single H1 root is redundant: the registry
    # already carries the root and matching is right-anchored, so keeping it would
    # force a FALSE gap between the document container and a deeper leaf (callers
    # prepend the root for the Step-0 exact path; a bare deep leaf then becomes
    # 'ROOT:/:leaf'). Drop it — 'ROOT:/:X' means 'X anywhere'. Non-root middle
    # levels stay strict (a real gap is still a no-match).
    if len(locator) > 1:
        root_title = detect_single_root(tree)
        if root_title and locator[0].lower() == root_title.lower():
            locator = locator[1:]

    # Loosening cascade: a tighter tier with a unique hit wins; ambiguity at a
    # reached tier refuses (a looser tier is a superset, so it can't
    # disambiguate); zero matches falls through to the next looser tier.
    for mode in ("exact", "prefix", "substring"):
        matches = [(n, parts) for (n, parts) in registry
                   if _locator_matches(locator, parts, mode)]
        if len(matches) == 1:
            n, parts = matches[0]
            resolved = ":/:".join(parts)
            if resolved != path:
                print(f'  (resolved "{path}" → "{resolved}" via {mode} match)',
                      file=sys.stderr)
            return (n, False)
        if len(matches) > 1:
            print(f'Error: Ambiguous match for "{path}" ({len(matches)} matches)',
                  file=sys.stderr)
            print("\nDid you mean:", file=sys.stderr)
            for n, parts in matches[:8]:
                print(f"  - {':/:'.join(parts)}", file=sys.stderr)
            hint_file = file_path or "FILE"
            print(f"\nRun 'md_tools list-paths {hint_file}' to see all valid paths.",
                  file=sys.stderr)
            return (None, True)

    format_path_error(path, collect_all_paths(tree.root), file_path)
    return (None, True)


def parse_and_resolve(file_path, section_path):
    """Parse file and resolve section path with fuzzy matching.

    Combines: parse → detect root → prepend root → fuzzy resolve → build path.
    Shared helper used by all file-level CLI functions that need path resolution.

    Args:
        file_path: Path to markdown file
        section_path: User-provided section path (may be partial, case-insensitive, leaf name)

    Returns:
        tuple: (tree, node, resolved_path) on success
               (None, None, None) on failure (error printed to stderr)
    """
    tree = MarkdownTree()
    with open(file_path, 'r', encoding='utf-8') as f:
        tree.parse(f.read())

    # "." addresses the document's own root: the single H1 when there is one,
    # else the synthetic level-0 container holding the top-level sections.
    # Same rule as _resolve_head, so the shorthand means one thing everywhere
    # rather than only under a SELECT/TRANSFORM flag.
    if section_path is not None and section_path.strip() == ".":
        node = tree.root.children[0] if detect_single_root(tree) else tree.root
        return (tree, node, build_node_path(node) or ".")

    root = detect_single_root(tree)
    full_path = prepend_root_prefix(section_path, root)

    node, error_printed = find_node_with_suggestions(tree, full_path, file_path)
    if not node:
        if not error_printed:
            print(f"Error: Section '{section_path}' not found", file=sys.stderr)
        return (None, None, None)

    resolved_path = build_node_path(node)
    return (tree, node, resolved_path)


def resolve_output_path(source_file, output_file):
    """Resolve output file path, defaulting to source file's directory.

    Handles: bare filename → resolve relative to source dir, create dirs if needed.
    Shared helper used by copy_section and extract_section.

    Args:
        source_file: Source file (used for default directory)
        output_file: User-provided output path (may be relative/bare filename)

    Returns:
        str: Resolved output path (directories created if needed)
    """
    import os

    output_dir = os.path.dirname(output_file)
    if not output_dir:
        source_dir = os.path.dirname(os.path.abspath(source_file))
        output_file = os.path.join(source_dir, output_file)
        output_dir = source_dir

    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    return output_file


def calculate_position(parent, sibling, before=False):
    """Calculate insertion index for non-default positions.

    Args:
        parent: Parent node to insert into
        sibling: Sibling marker ("^" for first; a name to position relative to)
        before: insert BEFORE the named sibling (default: AFTER it)

    Returns:
        int: Index position for insertion, or None if named sibling not found
              or the fuzzy match is ambiguous

    Sibling matching is fuzzy: exact title first, then a UNIQUE
    case-insensitive prefix match, then a UNIQUE substring match. This
    lets callers pass "item-1" for a node actually titled "item-1  [ ]" without
    needing the exact state-tag spelling. With before=True the result is the
    sibling's own index (insert before it); otherwise sibling index + 1 (after).
    """
    if sibling == "^":
        return 0  # First position
    off = 0 if before else 1

    # Exact title match (fast path)
    for idx, child in enumerate(parent.children):
        if child.title == sibling:
            return idx + off

    # Fuzzy fallback: unique case-insensitive prefix, then unique substring
    q = sibling.lower()
    prefix = [idx for idx, c in enumerate(parent.children) if c.title.lower().startswith(q)]
    if len(prefix) == 1:
        return prefix[0] + off
    substring = [idx for idx, c in enumerate(parent.children) if q in c.title.lower()]
    if len(substring) == 1:
        return substring[0] + off

    return None


def flatten_subtree(node):
    """Flatten node and all descendants into temp tree at root level."""
    temp_tree = MarkdownTree()

    def add_flat(n):
        """Recursive helper to add node to temp tree root."""
        content_str = "\n".join(n.content) if n.content else ""
        temp_tree.add_section("", n.title, content_str)
        for child in n.children:
            add_flat(child)

    add_flat(node)
    return temp_tree


# ============================================================================
# SELECT → TRANSFORM → EMIT core
# ----------------------------------------------------------------------------
# Every emit verb is SELECT (which node-set from the source) → TRANSFORM
# (reshape it) → EMIT (where it lands). SELECT and TRANSFORM are a uniform flag
# vocabulary; the intermediate representation is `list[MarkdownNode]` end to end
# (no MarkdownTree in the pipeline). build_view() drives the non-destructive emit
# verbs (read / copy): it operates on the in-memory parse and, for keep/omit,
# prunes that parse in place — safe because read/copy never write the source.
# ============================================================================


def collect_children(node, depth=1):
    """Descendants at relative TREE depth N below `node`, each WITH its subtree.

    Depth counts parent->child links in the parsed tree, NOT heading levels — so a
    ##->#### level-SKIP makes the #### a depth-1 child (it is a direct child in the
    tree). depth<=0 -> [node]; depth deeper than the subtree -> []. Returns node
    REFERENCES; callers that emit clone (read/copy never mutate the source).
    Generalizes attach_subtree's root-children lift to an arbitrary node.
    """
    if depth <= 0:
        return [node]
    current = [node]
    for _ in range(depth):
        nxt = []
        for n in current:
            nxt.extend(n.children)
        current = nxt
    return current


def _resolve_rel_path(head, parts):
    """Per-component descent under `head`; each component matched
    _strip_state_tags-normalized + case-insensitive (so a markered title
    'Thread Alpha  [implement]' resolves from the component 'Thread Alpha').

    `parts` is the already-split component list. Returns the resolved node, or
    None on any miss (caller warns to stderr and SKIPS — graceful for the
    non-canonical files keep/omit must tolerate).
    """
    cur = head
    for part in parts:
        want = _strip_state_tags(part).strip().lower()
        found = None
        for child in cur.children:
            if _strip_state_tags(child.title).strip().lower() == want:
                found = child
                break
        if found is None:
            return None
        cur = found
    return cur


def _resolve_keep_omit_paths(head, rel_paths, kind):
    """Resolve a list of head-relative :/:-paths to nodes under `head`.

    Returns the list of resolved nodes; a path that misses is reported to stderr
    and skipped (never an error — required so an allowlist can run on an arbitrary
    file). `kind` ('keep'/'omit') is only used in the warning text.
    """
    resolved = []
    for rel in rel_paths:
        parts = [p for p in rel.split(":/:") if p.strip()]
        if not parts:
            continue
        node = _resolve_rel_path(head, parts)
        if node is None:
            print(f"Warning: {kind} path '{rel}' not found under "
                  f"'{head.title}'; skipped.", file=sys.stderr)
            continue
        resolved.append(node)
    return resolved


def _prune_to_keep_closure(head, keep_nodes):
    """Prune `head`'s subtree IN PLACE to the keep-closure: each kept node's WHOLE
    subtree + the ancestor chain from head down to it (containers); head retained,
    every non-kept sibling dropped. Mutates head. (Naming a parent ⊇ naming any of
    its children — a kept node pulls in all its descendants.)"""
    keep_ids = {id(head)}
    for kn in keep_nodes:
        # the kept node and its whole subtree
        stack = [kn]
        while stack:
            n = stack.pop()
            keep_ids.add(id(n))
            stack.extend(n.children)
        # its ancestors up to (and including) head
        a = kn.parent
        while a is not None and id(a) not in keep_ids:
            keep_ids.add(id(a))
            if a is head:
                break
            a = a.parent

    def prune(n):
        n.children = [c for c in n.children if id(c) in keep_ids]
        for c in n.children:
            prune(c)

    prune(head)


def select_keep(head, keep_rel_paths):
    """ALLOWLIST select: prune `head`'s subtree IN PLACE to the keep-closure, then
    return head's surviving top-level children as a list.

    A deep keep ('Prioritization:/:Goal') keeps the relative path from the head down
    (Prioritization as the container, intro body kept by default) with ONLY Goal
    under it; the head itself is the level reference (EMIT re-levels its survivors to
    the output root). Mutates the (throwaway) working tree — read/copy never write
    the source, so this is non-destructive to the file.
    """
    keep_nodes = _resolve_keep_omit_paths(head, keep_rel_paths, "keep")
    _prune_to_keep_closure(head, keep_nodes)
    return list(head.children)


def select_omit(head, omit_rel_paths):
    """DENYLIST select (the complement): delete each resolved omit path from
    `head`'s subtree IN PLACE, then return head's surviving top-level children.

    A missing omit path is reported + skipped (graceful). Mutates the throwaway
    working tree only.
    """
    omit_nodes = _resolve_keep_omit_paths(head, omit_rel_paths, "omit")
    for n in omit_nodes:
        if n.parent is not None:
            n.parent.remove_child(n)
    return list(head.children)


def strip_markers(node):
    """Recursively replace every title in the subtree with its _strip_state_tags
    form (drops the canonical trailing marker zone: [state]/[v1]/*[ ]/(#)/(after:)).
    Idempotent; preserves mid-title backticks and inline links."""
    node.title = _strip_state_tags(node.title)
    for c in node.children:
        strip_markers(c)


def strip_bodies(node, scope):
    """Strip body content within a subtree. scope in {target, child, all}:
      target -> node's own body only;
      child  -> descendants' bodies only (node body kept);
      all    -> node + all descendants (heading skeleton only).
    Heading structure is always preserved.
    """
    if scope in ("target", "all"):
        node.content = []
    if scope in ("child", "all"):
        def strip_desc(n):
            for c in n.children:
                c.content = []
                strip_desc(c)
        strip_desc(node)


def _title_key(title):
    """Marker-transparent identity key for upserting a heading against existing children:
    the _strip_state_tags form, lowercased + trimmed. So 'todo a1  [x]', 'todo a1  *[ ]'
    and 'todo a1' all collide — a merge matches by title and ignores marker drift (the
    normal STATUS.md state). This is the I4 fix (replace's old raw c.title==clone.title
    duplicated a heading the moment a marker differed)."""
    return _strip_state_tags(title).strip().lower()


def _merge_node_into(target, incoming, *, clobber_body):
    """Merge `incoming` into the existing `target` node (same _title_key) — the ONE
    shared, marker-transparent, clobber-aware merger used by both `replace` and
    `place_view`.

    - clobber_body True  -> refresh target's body AND heading text from `incoming`
                            (a body/header refresh — e.g. leading prose, or a
                            clobber-body/full-subtree policy).
      clobber_body False -> leave target.content and target.title UNTOUCHED (pure
                            children-merge — a user `(#)` pin / `[v1]` / hand-set
                            state on the target survives; G1-sub).
    - incoming.children are upserted into target.children by _title_key (recursive):
        same key  -> merge into the existing child in place, keeping its slot, with
                     the per-child rule clobber_body = bool(child.content) (a child
                     carrying prose refreshes; a structural child leaves the match);
        new key   -> clone in, re-leveled to target.level + 1 (cascading), appended.
    """
    if clobber_body:
        target.content = list(incoming.content)
        target.title = incoming.title
    for inc_child in incoming.children:
        key = _title_key(inc_child.title)
        match = next((c for c in target.children if _title_key(c.title) == key), None)
        if match is not None:
            _merge_node_into(match, inc_child, clobber_body=bool(inc_child.content))
        else:
            delta = (target.level + 1) - inc_child.level
            clone = inc_child.copy_with_level_delta(delta, max_level=6)
            clone.parent = target
            target.children.append(clone)


def _resolve_head(tree, head_path):
    """Resolve the SELECT head node. head_path '.'/''/None -> the DETECTED single
    root (the H1), NOT the synthetic level-0 ROOT; a multi-root/empty doc -> the
    synthetic root (so its children are the top-level sections). Otherwise resolve
    head_path via the standard fuzzy resolver. Returns the node or None.
    """
    if head_path in (".", "", None):
        if detect_single_root(tree):
            return tree.root.children[0]
        return tree.root
    root_prefix = detect_single_root(tree)
    full = prepend_root_prefix(head_path, root_prefix)
    node, _err = find_node_with_suggestions(tree, full)
    return node


def build_view(tree, head_path=".", *, keep=None, omit=None, children=False,
               depth=1, flatten=False, strip_body=None, strip_markers_flag=False):
    """SELECT -> TRANSFORM pipeline over `tree`, returning a list[MarkdownNode].

    Fixed canonical order (NOT CLI flag order, so the result is deterministic):
      1. resolve head  (head_path '.' = the detected H1 root)
      2. SUBSET        keep -> select_keep; elif omit -> select_omit; else head's
                       children. (Both -> keep then omit-within-kept.)
      3. LIFT          if children: replace the list with the children of EACH
                       selected node at relative depth N (drops the wrappers).
      4. TRANSFORM     flatten -> strip_body -> strip_markers, in place on the list.

    Returns the node list, or None if the head could not be resolved. The nodes are
    references into the (mutated) working tree; EMIT clones them.
    """
    head = _resolve_head(tree, head_path)
    if head is None:
        return None

    # 2. SUBSET. keep/omit return head's surviving children (a SET); with no
    # selection the working unit is the head ITSELF — so `--children` lifts the
    # head's children (matching the flag's contract) and a bare transform
    # (--strip-*/--flatten/--strip-markers) reshapes the head as a unit.
    if keep:
        working = select_keep(head, keep)
        if omit:
            working = select_omit(head, omit)
    elif omit:
        working = select_omit(head, omit)
    else:
        working = [head]

    # 3. LIFT
    if children:
        lifted = []
        for n in working:
            lifted.extend(collect_children(n, depth))
        working = lifted

    # 4. TRANSFORM (in place on the list)
    if flatten:
        flat = []
        for n in working:
            ft = flatten_subtree(n)
            flat.extend(ft.root.children)
        working = flat
    if strip_body:
        for n in working:
            strip_bodies(n, strip_body)
    if strip_markers_flag:
        for n in working:
            strip_markers(n)
    return working


def _clones_clamped(node, delta, max_level=6):
    """True if re-leveling `node`'s subtree by `delta` pins any node at max_level.

    copy_with_level_delta clamps >max_level to max_level AND recurses with the same
    delta, collapsing deeper nodes onto that level (lossy). View re-leveling is
    downward (delta<=0) and never clamps; deep --parent/--under can.
    """
    if node.level + delta > max_level:
        return True
    return any(_clones_clamped(c, delta, max_level) for c in node.children)


def _emit_view_nodes(nodes, parent_level=0, max_level=6):
    """Clone each node re-leveled so its heading sits at parent_level+1 (the EMIT
    placement delta-math). Returns (clones, clamped_any). parent_level 0 -> each top
    node becomes level 1 (the normalized view document / new-file root level)."""
    clones = []
    clamped_any = False
    for n in nodes:
        delta = (parent_level + 1) - n.level
        if _clones_clamped(n, delta, max_level):
            clamped_any = True
        clones.append(n.copy_with_level_delta(delta, max_level=max_level))
    return clones, clamped_any


def _warn_if_clamped(clamped, where):
    if clamped:
        print(f"Warning: re-leveling {where} pinned one or more headings at the "
              f"max markdown depth (6), collapsing deeper levels onto it.",
              file=sys.stderr)


def place_view(output_tree, nodes, *, parent=None, after_sibling=None,
               policy="merge", where=""):
    """EMIT back-end — the destination counterpart to build_view. Place `nodes` under
    `parent` in `output_tree`, merging on marker-transparent title-match instead of
    blindly appending. Returns (placed, clamped_any): `placed` is the list of FRESHLY
    added clones (a node merged into an existing match is NOT in `placed`).

    A. Default parent = _resolve_head(output_tree, ".") — the single H1, else the
       synthetic root (I8: one canonical default-parent resolution, never a stray 2nd H1).
       Callers with a --parent string resolve it to a node first and pass it in.
    B. Each node is cloned + re-leveled to parent.level+1 via _emit_view_nodes (the EMIT
       delta-math — NEVER re-leveled to root, the level-correctness fix); an upward
       re-level past depth 6 clamps and WARNs.
    C. Per-clone, marker-transparent (_title_key) placement against parent.children:
         policy 'append' OR no match -> parent.add_child(clone)  (fresh-place; the
                                        unchanged common copy-to-fresh-file/new-title case)
         match + 'merge'        -> _merge_node_into(match, clone, clobber_body=bool(clone.content))
                                   (G1-sub: leading prose ⇒ body+header refresh;
                                    children-only ⇒ match's header/markers untouched)
         match + 'clobber-body'  -> _merge_node_into(match, clone, clobber_body=True)
         match + 'full-subtree'  -> match.children=[]; _merge_node_into(match, clone, clobber_body=True)
    D. Warn once if any clone clamped.
    E. Reposition ONLY freshly-placed nodes when after_sibling is set (a merged node
       keeps the match's slot), via calculate_position — same as move.
    """
    if parent is None:
        parent = _resolve_head(output_tree, ".")
    clones, clamped_any = _emit_view_nodes(nodes, parent_level=parent.level)
    _warn_if_clamped(clamped_any, where)
    placed = []
    for clone in clones:
        match = None
        if policy != "append":
            key = _title_key(clone.title)
            match = next((c for c in parent.children if _title_key(c.title) == key), None)
        if match is None:
            parent.add_child(clone)
            placed.append(clone)
        elif policy == "full-subtree":
            match.children = []
            _merge_node_into(match, clone, clobber_body=True)
        elif policy == "clobber-body":
            _merge_node_into(match, clone, clobber_body=True)
        else:  # merge (default)
            _merge_node_into(match, clone, clobber_body=bool(clone.content))
    # Reposition only the freshly-placed nodes. Insert in reverse so they end up in
    # input order right after the named sibling (calculate_position re-resolves the
    # sibling's index each pass; the sibling does not move since we insert after it).
    if after_sibling not in (None, "$", "LAST") and placed:
        for clone in reversed(placed):
            pos = calculate_position(parent, after_sibling)
            if pos is None:
                break  # named sibling not found — leave appended; caller may report
            parent.children.remove(clone)
            parent.children.insert(pos, clone)
    return placed, clamped_any


# ============================================================================
# CLI Functions
# ============================================================================


def _select_active(keep, omit, children, flatten, strip_body, strip_markers_flag):
    """True if any SELECT/TRANSFORM flag is set (so the verb routes through
    build_view); else the verb takes its native single-section path."""
    return bool(keep or omit or children or flatten or strip_body or strip_markers_flag)


def _view_to_tree(nodes, output_tree=None, where=""):
    """Re-level a view node-list to the (output) root and graft it on.

    Each top node is re-leveled so its heading sits at the root's child level
    (level 1 for a new doc), via the EMIT delta-math; a clamp at max depth WARNs.
    Returns the tree (a fresh one if output_tree is None).
    """
    if output_tree is None:
        output_tree = MarkdownTree()
    clones, clamped = _emit_view_nodes(nodes, parent_level=output_tree.root.level)
    _warn_if_clamped(clamped, where)
    for c in clones:
        output_tree.root.add_child(c)
    return output_tree


def read_section(input_file, section_path, *, keep=None, omit=None, children=False,
                 depth=1, flatten=False, strip_body=None, strip_markers_flag=False):
    """Print a section to stdout (read-only).

    Bare `read FILE SECTION` (no SELECT/TRANSFORM flag) dumps the resolved node at
    its NATIVE level — unchanged. With any SELECT/TRANSFORM flag, SECTION is the
    HEAD; the selected node-set is re-leveled to a normalized view and printed.
    """
    if not _select_active(keep, omit, children, flatten, strip_body, strip_markers_flag):
        tree, node, resolved_path = parse_and_resolve(input_file, section_path)
        if not tree:
            return False
        print(node.dump())
        return True

    tree = MarkdownTree()
    with open(input_file, 'r', encoding='utf-8') as f:
        tree.parse(f.read())
    nodes = build_view(tree, section_path, keep=keep, omit=omit, children=children,
                       depth=depth, flatten=flatten, strip_body=strip_body,
                       strip_markers_flag=strip_markers_flag)
    if nodes is None:
        print(f"Error: head '{section_path}' not found in {input_file}", file=sys.stderr)
        return False
    out = _view_to_tree(nodes, where=f"read view of {input_file}")
    print(out.dump())
    return True


def _read_output_tree(output_file):
    """Parse an existing output file into a tree, or return a fresh empty tree."""
    import os
    output_tree = MarkdownTree()
    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8') as f:
            content = f.read()
            if content.strip():
                output_tree.parse(content)
    return output_tree


def copy_section_bare(source_file, section_path, output_file, *, keep=None, omit=None,
                      children=False, depth=1, flatten=False, strip_body=None,
                      strip_markers_flag=False, parent=None, after_sibling=None,
                      policy="merge"):
    """Copy section(s) to an output file. Source is NOT modified.

    Non-destructive copy — the fundamental primitive (extract_section composes it).
    SELECT/TRANSFORM via build_view (a bare copy = build_view with no flags -> the one
    resolved node), EMIT via place_view (re-level + place under `parent`, merging on
    title-match). A fresh file / new title -> placed as-is; a same-(stripped)-title
    section in the destination -> merged per `policy` (the I1/I2 fix). The output never
    inherits the source's frontmatter (file-bound).
    """
    output_file = resolve_output_path(source_file, output_file)

    tree = MarkdownTree()
    with open(source_file, 'r', encoding='utf-8') as f:
        tree.parse(f.read())
    nodes = build_view(tree, section_path, keep=keep, omit=omit, children=children,
                       depth=depth, flatten=flatten, strip_body=strip_body,
                       strip_markers_flag=strip_markers_flag)
    if nodes is None:
        print(f"Error: head '{section_path}' not found in {source_file}", file=sys.stderr)
        return False

    output_tree = _read_output_tree(output_file)
    parent_node = None
    if parent not in (None, "", ".", "ROOT"):
        # A real destination path -> resolve it; "."/""/ROOT/None fall through to
        # place_view's default (the output's single H1, else the synthetic root).
        root_prefix = detect_single_root(output_tree)
        full = prepend_root_prefix(parent, root_prefix)
        parent_node, failed = find_node_with_suggestions(output_tree, full, output_file)
        if failed or parent_node is None:
            return False
    place_view(output_tree, nodes, parent=parent_node, after_sibling=after_sibling,
               policy=policy, where=f"copy to {output_file}")
    commit(output_file, output_tree.dump())
    print(f"✓ Copied {len(nodes)} node(s) from '{section_path}' to {output_file}")
    return True


def extract_section(input_file, section_path, output_file, *, keep=None, omit=None,
                    children=False, depth=1, flatten=False, strip_body=None,
                    strip_markers_flag=False, parent=None, after_sibling=None,
                    policy="merge"):
    """Extract (cut) section(s) from source to a file — a thin wrapper over `copy` +
    `delete`/`reshape`. Bare `extract SOURCE SECTION OUTPUT` = copy + delete. With a
    SELECT flag, SECTION is the HEAD: the SAME view `copy` emits is written to OUTPUT
    (inheriting copy's place-and-merge EMIT — `--parent`/`--after-sibling`/`policy`),
    then the emitted content is removed from source via the INVERSE in-place op (the
    head + everything NOT selected stay):
        --keep K   = copy(--keep K)   + reshape(--omit K)    (remove the kept from source)
        --omit O   = copy(--omit O)   + reshape(--keep O)    (keep only the omitted)
        --children = copy(--children) + delete each lifted child
    --flatten / --strip-body / --strip-markers reshape the emitted copy.
    """
    output_file = resolve_output_path(input_file, output_file)
    transform = dict(flatten=flatten, strip_body=strip_body,
                     strip_markers_flag=strip_markers_flag)
    emit = dict(parent=parent, after_sibling=after_sibling, policy=policy)
    # Hold both files' locks for the whole copy+remove and call the *_bare forms
    # (a wrapped sub-verb would re-acquire LOCK_EX on input_file and self-deadlock).
    with multi_file_lock(input_file, output_file):
        if not (keep or omit or children):
            ok = copy_section_bare(input_file, section_path, output_file, **transform, **emit)
            return ok and delete_section_bare(input_file, section_path)
        # Copy the view to OUTPUT first (so a source edit can't invalidate it).
        ok = copy_section_bare(input_file, section_path, output_file,
                               keep=keep, omit=omit, children=children, depth=depth,
                               **transform, **emit)
        if not ok:
            return False
        # Remove the emitted content from source via the inverse in-place op.
        if keep:
            return reshape_section_bare(input_file, section_path, omit=keep)
        if omit:
            return reshape_section_bare(input_file, section_path, keep=omit)
        # children: delete each lifted child by path (head retained, emptied of them).
        tree = MarkdownTree()
        with open(input_file, 'r', encoding='utf-8') as f:
            tree.parse(f.read())
        head = _resolve_head(tree, section_path)
        if head is None:
            print(f"Error: head '{section_path}' not found in {input_file}", file=sys.stderr)
            return False
        ok = True
        for p in [build_node_path(c) for c in collect_children(head, depth)]:
            ok = delete_section_bare(input_file, p) and ok
        return ok


def delete_section_bare(input_file, section_path):
    """Delete section from file.

    Deleting the document root ('.' or the H1's own title) removes every
    section — the file is emptied. That is allowed, but it is announced on
    stderr with a restore command, because the ordinary success line reads
    identically to a one-section delete.
    """
    backup_path = create_backup(input_file, 'md_tools')

    tree, node, resolved_path = parse_and_resolve(input_file, section_path)
    if not tree:
        return False

    # Decide BEFORE removing: is this the document's own root? Tested by node
    # identity rather than by the locator string, so the explicit-H1-title form
    # warns exactly like the '.' shorthand does.
    root_child = tree.root.children[0] if detect_single_root(tree) else None
    emptying = (node is tree.root) or (root_child is not None and node is root_child)

    if node.parent:
        node.parent.remove_child(node)
    else:
        return False

    commit(input_file, tree.dump())

    if emptying:
        print(f"⚠️  EMPTIED {input_file} — removed the document root and ALL sections under it.",
              file=sys.stderr)
        if backup_path:
            print(f"    Restore with:  cp '{backup_path}' '{input_file}'", file=sys.stderr)
        else:
            # create_backup returns None when it de-duplicates (same file already
            # backed up this hour or this invocation), so there is no path to
            # quote. Point at the directory instead of naming a file that may
            # predate this delete.
            print("    A backup from earlier this hour is in ~/.claude/backups/md_tools/ —"
                  " check its timestamp before restoring.", file=sys.stderr)
        return True

    print(f"✓ Deleted section '{section_path}' from {input_file}")
    return True


def insert_section_bare(input_file, parent_path, content, after_sibling=None,
                        before_sibling=None, policy="merge"):
    """Insert one or more new sections, authored as a markdown fragment.

    Mirrors replace_section_bare: `content` is parsed as markdown rather than
    written as literal body text. Its first heading becomes the new section's
    title; the text under that heading becomes its body, and deeper headings
    become its subsections. Heading levels are re-leveled to nest under
    `parent_path`, so the payload can be written at any depth. Headings inside
    code fences are never touched.

    A payload carrying several top-level headings inserts them as siblings.

    Args:
        input_file: Markdown file to insert into
        parent_path: DESTINATION section — the payload nests under this node.
                     "." = the file's root. Required: the old form took the new
                     section's TITLE here, so a stale call would silently treat
                     that title as a destination. The heading guard below turns
                     every such call into a loud error instead.
        content: Markdown fragment BEGINNING with the new section's heading
        after_sibling: Position marker: "^" = first child, name = after that sibling,
                       None/"$"/"LAST" = append to end
        before_sibling: name = insert BEFORE that sibling (mutually exclusive with
                       after_sibling; "^" = first child)
    """
    # The payload must start with a heading — that heading IS the new section's
    # title. Checking it first is also the migration guard: a caller still using
    # the old `insert FILE "Title" "body"` form passes body text with no heading,
    # which lands here and fails loudly rather than creating a section named after
    # whatever it meant as a destination.
    lead, payload = _split_at_first_unfenced_header(content or "")
    if not payload.strip():
        print(f"Error: insert needs a markdown fragment whose FIRST line is the new "
              f"section's heading; none found in the content given.\n"
              f"       Form:  md_tools insert FILE <destination-section> "
              f"'# New Title\\n<body>\\n## Subsection'\n"
              f"       The destination is where the payload NESTS; the title comes "
              f"from the payload's own heading.", file=sys.stderr)
        return False
    if lead.strip():
        print(f"Error: content before the first heading would be discarded "
              f"(the payload's heading must come first). Move this text under the "
              f"heading:\n       {lead.strip().splitlines()[0][:80]}", file=sys.stderr)
        return False

    # Parse FIRST, resolve the parent, and only then back up + write. Doing the
    # backup last means a refuse/failed-resolution path (below) leaves no stray
    # backup for an operation that changed nothing.
    tree, parent_node, parent_display = parse_and_resolve(input_file, parent_path)
    if not tree:
        return False

    # A file with several top-level titles has no single H1 for "." to mean, so
    # "." lands on the synthetic container and the payload becomes ANOTHER
    # top-level title. That is now an explicit request rather than the accident
    # a parent-less insert used to be, so it proceeds — but it still grows the
    # H1 count on an already non-canonical file, which is worth saying out loud.
    if parent_node is tree.root and len(tree.root.children) > 1:
        print(f"Warning: '{input_file}' has {len(tree.root.children)} top-level titles; "
              f"inserting at '.' adds another one. Name a section as the destination "
              f"instead if you meant to nest.", file=sys.stderr)

    create_backup(input_file, 'md_tools')

    # Parse the payload as its own document, then re-level it onto the
    # destination. _dedent_headers normalizes the fragment's shallowest heading
    # to level 1 (equal-level headings otherwise nest under each other rather
    # than parsing as siblings); _emit_view_nodes then applies the destination
    # delta. Both skip fenced lines, so an embedded code block that contains
    # '#' lines survives byte-exact.
    frag = MarkdownTree()
    frag.parse(_dedent_headers(payload))
    if not frag.root.children:
        print("Error: the payload parsed to no sections.", file=sys.stderr)
        return False

    # Placement goes through the SHARED EMIT back-end, so a marker-transparent title
    # collision MERGES exactly as it does for copy / move / extract / replace. insert
    # was previously the only placing verb that appended a duplicate instead — and the
    # result was unrecoverable, because no locator distinguishes two identical titles,
    # so neither node could afterwards be read, renamed, moved or deleted.
    # Repositioning stays HERE rather than in place_view: insert also supports
    # --before-sibling, and it reports a missing sibling as an error instead of
    # silently leaving the node appended.
    incoming_titles = [c.title for c in frag.root.children]
    new_nodes, _clamped = place_view(tree, frag.root.children, parent=parent_node,
                                     after_sibling=None, policy=policy,
                                     where=f"insert into '{parent_display}'")
    _placed_keys = {_title_key(_n.title) for _n in new_nodes}
    merged_titles = [t for t in incoming_titles if _title_key(t) not in _placed_keys]

    # Reposition if a non-default position was requested. before_sibling and
    # after_sibling are mutually exclusive (enforced by the CLI group); before wins
    # if both are somehow set programmatically.
    is_before = before_sibling is not None
    sib = before_sibling if is_before else after_sibling
    if sib not in (None, "$", "LAST"):
        # Detach the freshly-appended nodes BEFORE locating the sibling, so the
        # index is computed against the pre-existing children only.
        for _n in new_nodes:
            parent_node.children.remove(_n)
        position = calculate_position(parent_node, sib, before=is_before)
        if position is None:
            siblings = [c.title for c in parent_node.children]
            rel = "before" if is_before else "after"
            print(f"Error: Sibling '{sib}' (to insert {rel}) not found under '{parent_node.title}'.", file=sys.stderr)
            if siblings:
                print(f"Available siblings: {', '.join(siblings)}", file=sys.stderr)
            return False
        parent_node.children[position:position] = new_nodes

    commit(input_file, tree.dump())

    parts = []
    if new_nodes:
        parts.append("Inserted section "
                     + ", ".join(f"'{_n.title}'" for _n in new_nodes))
    if merged_titles:
        parts.append("MERGED into existing "
                     + ", ".join(f"'{t}'" for t in merged_titles))
    print(f"✓ {'; '.join(parts)} in {input_file}")
    return True


def move_sections_bare(source_file, target_file, section_paths, parent_path=None,
                       after_sibling=None, flatten=False, keep=None, omit=None,
                       children=False, depth=1, strip_body=None, strip_markers_flag=False):
    """Move one or more sections (:,:-separated) between existing files.

    Target file must already exist — move reorganizes between existing documents.
    Use copy_section to write a section to a new file.

    Args:
        source_file: Source markdown file
        target_file: Target markdown file (must exist; None = same as source)
        section_paths: Section path(s) to move (:,:-separated for multiple). With a
                  SELECT flag (keep/omit/children) this is the HEAD; the relocate set
                  is derived from it (keep -> the named subtrees; omit -> head's
                  children minus the omitted; children -> the depth-N children).
        parent_path: New parent section path (None = root level)
        after_sibling: Sibling marker (None/"$"/"LAST" = append, "^" = first, name = after sibling)
        flatten: If True, flatten section hierarchy before moving
        keep/omit: head-relative path-set selecting which subtrees to relocate.
        children: If True, expand each named path into its depth-N children (the
                  named node's wrapper is dropped; its children become the units).
        depth: Relative depth for `children` (default 1 = immediate children).
        strip_markers_flag: If True, strip the canonical marker zone from each
                  moved heading's title.
    """
    # Default target to source for same-file moves
    if target_file is None:
        target_file = source_file

    # Target must exist (move reorganizes between existing documents)
    if not Path(target_file).exists():
        print(f"Error: Target file '{target_file}' does not exist. "
              f"Use 'copy' to create a new file, or 'move' to reorganize between existing files.",
              file=sys.stderr)
        return False

    # Create backups
    create_backup(source_file, 'md_tools')
    if target_file != source_file:
        create_backup(target_file, 'md_tools')

    # Parse source and target (always separate objects)
    source_tree = MarkdownTree()
    with open(source_file, 'r', encoding='utf-8') as f:
        source_tree.parse(f.read())

    target_tree = MarkdownTree()
    with open(target_file, 'r', encoding='utf-8') as f:
        target_tree.parse(f.read())

    # Auto-detect root prefixes (can differ between files)
    source_root = detect_single_root(source_tree)
    target_root = detect_single_root(target_tree)

    # Prepend target root to parent_path if needed. "." names the file root, the
    # same as insert's destination and the SELECT head: the single H1, else ROOT.
    parent_path = prepend_root_prefix(parent_path, target_root) if parent_path not in (None, "", ".", "ROOT") else (target_root or "")

    # Get parent node in target tree
    if parent_path in ("", "ROOT"):
        parent = target_tree.root
        parent_display = "root"
    else:
        parent, error_printed = find_node_with_suggestions(target_tree, parent_path, target_file)
        if not parent:
            if not error_printed:
                print(f"Error: Parent '{parent_path}' not found", file=sys.stderr)
            return False
        parent_display = parent_path

    # Derive the relocate set. keep/omit: section_paths is the HEAD; the named
    # subtrees (keep) / head's children minus the omitted (omit) relocate. children:
    # each named head's depth-N children. Resolve against the source before removal.
    if keep or omit:
        head = _resolve_head(source_tree, section_paths.strip())
        if head is None:
            print(f"Error: head '{section_paths}' not found in source; file left unchanged.",
                  file=sys.stderr)
            return False
        if keep:
            sel = _resolve_keep_omit_paths(head, keep, "keep")
        else:
            omit_nodes = _resolve_keep_omit_paths(head, omit, "omit")
            if any(n.parent is not head for n in omit_nodes):
                print("Warning: move --omit operates on the head's direct children; a "
                      "deeper omit path does not stay behind — use --keep for deep "
                      "exclusion.", file=sys.stderr)
            omit_ids = {id(n) for n in omit_nodes}
            sel = [c for c in head.children if id(c) not in omit_ids]
        if not sel:
            print("Error: SELECT resolved no sections to move; file left unchanged.",
                  file=sys.stderr)
            return False
        user_paths = [build_node_path(n) for n in sel]
    else:
        # Parse :,:-separated paths
        user_paths = [p.strip() for p in section_paths.split(':,:')]
        # --children: replace each named path with its depth-N children (drop the
        # wrapper).
        if children:
            expanded = []
            for up in user_paths:
                head = _resolve_head(source_tree, up)
                if head is None:
                    print(f"Warning: section '{up}' not found in source; skipped.", file=sys.stderr)
                    continue
                expanded.extend(build_node_path(c) for c in collect_children(head, depth))
            if not expanded:
                print("Error: --children resolved no sections to move; file left unchanged.",
                      file=sys.stderr)
                return False
            user_paths = expanded

    # For non-default positions, reverse order to preserve final order
    # (each insert at same position pushes previous down, so last-first yields first-last)
    if after_sibling not in (None, "$", "LAST"):
        user_paths = list(reversed(user_paths))

    moved_count = 0

    # Process each section
    for user_path in user_paths:
        # Build the source path with its root prefix (the destination side is handled by
        # place_view, which resolves the parent + merges by title).
        source_path = prepend_root_prefix(user_path, source_root)

        # Resolve source_path with fuzzy matching (both branches need this)
        source_node, error_printed = find_node_with_suggestions(source_tree, source_path, source_file)
        if not source_node:
            if not error_printed:
                print(f"Warning: Section '{user_path}' not found in source", file=sys.stderr)
            continue
        resolved_source_path = build_node_path(source_node)

        # Same-file relocate: remove the source's OLD occurrence from the target tree
        # (a separate parse of the SAME file) so the section never appears twice. Remove
        # by the EXACT resolved source path — silent, by design (the old code did a FUZZY
        # find_node_with_suggestions probe on target_path here, which printed a spurious
        # "No exact match" error to stderr on the cross-file no-collision case; I5). The
        # cross-file source removal happens after placement, below. A cross-file move into
        # a destination that already holds a same-titled section is left for place_view to
        # MERGE (no pre-removal), consistent with copy/extract/replace.
        if source_file == target_file:
            target_tree.remove_section(resolved_source_path)

        # EMIT through the shared place_view: clone + re-level under `parent`, merge on
        # marker-transparent title-match, reposition the freshly-placed nodes, and WARN if
        # a deep-parent re-level clamps at the max markdown depth (6). flatten lifts the
        # source subtree to a flat node sequence first.
        if flatten:
            nodes_to_place = flatten_subtree(source_node).root.children
        else:
            nodes_to_place = [source_node]
        placed, _clamped = place_view(
            target_tree, nodes_to_place, parent=parent, after_sibling=after_sibling,
            policy="merge", where=f"move of '{user_path}' under '{parent_display}'")

        # TRANSFORM the freshly-placed clones: strip body text, then strip markers.
        if strip_body:
            for clone in placed:
                strip_bodies(clone, strip_body)
        if strip_markers_flag:
            for clone in placed:
                strip_markers(clone)

        # Clean up source if cross-file
        if source_file != target_file:
            source_tree.remove_section(resolved_source_path)

        moved_count += 1

    # Safety net: if nothing was successfully moved, do NOT write — otherwise a
    # failed attach after a remove would persist a destructive partial state (the
    # data-loss bug). Leaving the file untouched keeps the source intact.
    if moved_count == 0:
        print("Error: No sections moved (no match or placement failed); file left unchanged.", file=sys.stderr)
        return False

    # Write target file
    commit(target_file, target_tree.dump())

    # Write source file only if different
    if source_file != target_file:
        commit(source_file, source_tree.dump())

    # Print summary
    mode_str = " (flattened)" if flatten else ""
    position_str = ""
    if after_sibling == "^":
        position_str = " at first position"
    elif after_sibling and after_sibling not in ("$", "LAST"):
        position_str = f" after '{after_sibling}'"

    print(f"✓ Moved {moved_count} section(s) to '{parent_display}'{position_str}{mode_str}")
    return True


def list_paths(input_file, max_depth=None):
    """Output all valid :/:-separated paths, one per line.

    Enables path discovery before extract/move/delete operations.

    Args:
        input_file: Path to markdown file
        max_depth: Optional maximum depth to output

    Returns:
        bool: True if successful
    """
    tree = MarkdownTree()
    with open(input_file, 'r', encoding='utf-8') as f:
        tree.parse(f.read())

    paths = collect_all_paths(tree.root, max_depth=max_depth)
    for p in paths:
        print(p)

    return True


def list_sections(input_file, path=None, max_depth=None):
    """Display document outline.

    Args:
        input_file: Path to markdown file
        path: Optional section path to display (e.g., "Parent:/:Child")
        max_depth: Optional maximum depth to display

    Returns:
        bool: True if successful, False if path not found
    """
    if path:
        tree, node, resolved_path = parse_and_resolve(input_file, path)
        if not tree:
            return False
        return tree.visualize(path=resolved_path, max_depth=max_depth)
    else:
        tree = MarkdownTree()
        with open(input_file, 'r', encoding='utf-8') as f:
            tree.parse(f.read())
        return tree.visualize(max_depth=max_depth)


def map_sections(input_file, path=None, max_depth=None):
    """Display document outline with line counts for each section.

    Args:
        input_file: Path to markdown file
        path: Optional section path to display (e.g., "Parent:/:Child")
        max_depth: Optional maximum depth to display

    Returns:
        bool: True if successful, False if path not found
    """
    import os

    if path:
        tree, start_node, resolved_path = parse_and_resolve(input_file, path)
        if not tree:
            return False
    else:
        tree = MarkdownTree()
        with open(input_file, 'r', encoding='utf-8') as f:
            tree.parse(f.read())
        start_node = tree.root

    total_lines = len(tree.dump().split('\n'))

    # Print header
    filename = os.path.basename(input_file)
    if path:
        print(f"# {filename} - Document Map (Section: {path})\n")
    else:
        print(f"# {filename} - Document Map\n")
    print(f"**Total Lines: {total_lines}**\n")

    # Calculate line counts by converting tree dump back to text and measuring
    def count_node_lines(node):
        """Recursively count lines for a node and its children."""
        node_tree = MarkdownTree()
        node_tree.root.children = [node]
        return len(node_tree.dump().split('\n'))

    def print_node_with_counts(node, indent_level=0, current_depth=0):
        """Recursively print nodes with line counts."""
        if node.level == 0:  # Root node
            for child in node.children:
                print_node_with_counts(child, indent_level, current_depth)
        else:
            lines = count_node_lines(node)
            indent = "  " * (node.level - 1)
            print(f"{indent}- {node.title} ({lines} lines)")

            # Only recurse if within depth limit
            if max_depth is None or current_depth < max_depth:
                for child in node.children:
                    print_node_with_counts(child, indent_level, current_depth + 1)

    print_node_with_counts(start_node)

    return True


def _fence_line_flags(lines):
    """Return list[bool]: True for lines INSIDE a ``` code fence (the fence delimiter
    lines themselves are False). Used so a `- ` / `**` inside a code block is not
    mistaken for a bullet / bold header during conversion."""
    flags = []
    in_fence = False
    for ln in lines:
        if ln.lstrip().startswith("```"):
            flags.append(False)
            in_fence = not in_fence
        else:
            flags.append(in_fence)
    return flags


def _convert_bullets_in_node(node, body_marker="\n", level=None, checkbox_to_trailing=False):
    """Convert node's top-level `- ` bullets (outside code fences) into child headings,
    inserted BEFORE any existing children; leading non-bullet prose stays as the body.

    Each entry (the `- ` line + its following non-bullet continuation lines) is split into
    heading | body at the FIRST occurrence of `body_marker` (default '\\n' = the bullet
    line is the heading, continuation lines the body). With `checkbox_to_trailing`, a
    task-list checkbox is relocated to the canonical trailing tag ('[ ] X' -> 'X  [ ]').

    Returns the number of bullets converted, or None if the child level would exceed 6.
    """
    child_level = level if level else node.level + 1
    if child_level > 6:
        return None
    lines = ("\n".join(node.content)).split("\n") if node.content else []
    fence = _fence_line_flags(lines)

    def is_bullet(k):
        return lines[k].startswith("- ") and not fence[k]

    # Leading non-bullet prose remains the section body.
    intro, i = [], 0
    while i < len(lines) and not is_bullet(i):
        intro.append(lines[i])
        i += 1

    # Group the rest into entries: each top-level `- ` line starts an entry; following
    # non-bullet lines are that entry's continuation body.
    entries = []
    for k in range(i, len(lines)):
        if is_bullet(k):
            entries.append([lines[k], []])
        elif entries:
            entries[-1][1].append(lines[k])
        else:
            intro.append(lines[k])  # defensive: stray pre-bullet line

    if not entries:
        return 0

    new_children = []
    for head_line, cont in entries:
        bullet_text = head_line[2:]  # strip leading "- "
        entry_text = bullet_text if not cont else bullet_text + "\n" + "\n".join(cont)
        if body_marker and body_marker in entry_text:
            hd, bd = entry_text.split(body_marker, 1)
        else:
            hd, bd = entry_text, ""
        title = hd.strip()
        body = bd.strip("\n").rstrip()
        if checkbox_to_trailing:
            m = re.match(r'^\[([ xX])\]\s+(.*)$', title)
            if m:
                box = m.group(1).strip() or " "
                title = f"{m.group(2).strip()}  [{box}]"
        child = MarkdownNode(child_level, title)
        if body.strip():
            child.add_content(body)
        new_children.append(child)

    intro_text = "\n".join(intro).strip("\n")
    node.content = [intro_text] if intro_text.strip() else []
    node.children = new_children + node.children
    return len(new_children)


def convert_to_headings_bare(file_path, section_path=None, mode="bullets",
                             body_marker="\n", level=None, dry_run=False,
                             checkbox_to_trailing=False):
    """Convert in-body structure into child HEADINGS. One verb, two modes:

      - 'bullets' (default): a SECTION's top-level `- ` bullets -> child headings, split
        heading|body at --body-marker (default '\\n'). SECTION is REQUIRED — whole-file
        bullet conversion would promote every legitimate bullet list in the document, so
        it is omitted by design (convert one section at a time). --level overrides the
        child level; --checkbox-to-trailing relocates a task-list checkbox to the
        canonical trailing tag.
      - 'bold': **Title:** lines in body content -> child headings (recursive). SECTION
        optional (default: whole file, matching the historical convert-bold behavior);
        given, only that subtree is processed. --body-marker/--level/--checkbox-to-trailing
        do not apply (bold's heading|body boundary is intrinsically `**`).

    Both modes are code-fence aware and honor --dry-run (print, no write).
    """
    if mode == "bold":
        return _convert_bold_to_headings_bare(file_path, section_path=section_path,
                                              dry_run=dry_run)
    # bullets mode
    if not section_path:
        print("convert: 'bullets' mode requires a SECTION (whole-file bullet conversion is "
              "omitted by design — it would promote every bullet list in the file). "
              "Use --from bold for whole-file bold-header conversion.", file=sys.stderr)
        return False
    tree, node, resolved_path = parse_and_resolve(file_path, section_path)
    if not tree:
        return False
    child_level = level if level else node.level + 1
    n = _convert_bullets_in_node(node, body_marker=body_marker, level=level,
                                 checkbox_to_trailing=checkbox_to_trailing)
    if n is None:
        print(f"✗ ERROR: child level {child_level} exceeds markdown max depth (6)")
        return False
    if n == 0:
        print(f"No top-level '- ' bullets found in section '{resolved_path}'")
        return False
    result = tree.dump()
    if dry_run:
        print(result)
        print(f"\n--- DRY RUN: {n} bullet(s) in '{resolved_path}' would become level-"
              f"{child_level} headings (no write) ---", file=sys.stderr)
        return True
    create_backup(file_path, 'md_tools')
    commit(file_path, result)
    print(f"✓ Converted {n} bullet(s) in '{resolved_path}' to level-{child_level} "
          f"headings in {file_path}")
    return True


def _convert_bold_to_headings_bare(file_path, section_path=None, dry_run=False):
    """Convert bold headers (**Title:**) in body content to child headings.

    Recursively processes the subtree rooted at `section_path` (or the whole document
    when section_path is None), converting **Title:** lines to child sections at
    parent_level + 1. Code-fence aware (a `**Bold:**` inside a ``` block is left alone).
    Internal helper for the `convert --from bold` verb.

    Returns:
        bool: True if successful
    """
    if section_path:
        tree, start_node, resolved = parse_and_resolve(file_path, section_path)
        if not tree:
            return False
    else:
        tree = MarkdownTree()
        with open(file_path, 'r', encoding='utf-8') as f:
            tree.parse(f.read())
        # Whole-file: require a root-level header for proper sibling parsing.
        has_root = any(child.level == 1 for child in tree.root.children)
        if not has_root:
            print(f"✗ ERROR: {file_path} requires a root-level header (# Title) for proper parsing")
            print("  Without a root header, siblings will be incorrectly nested as parent-child.")
            return False
        start_node = tree.root
        resolved = "(whole file)"

    def is_bold_header(line):
        """Check if line starts with bold text (**...**)."""
        stripped = line.strip()
        # Must start with ** and have a closing **
        return stripped.startswith('**') and '**' in stripped[2:]

    def extract_bold_title_and_inline_content(line):
        """Extract title and any inline content from bold header.

        Examples:
            **Title:** -> ('Title', '')
            **Title:** Some content -> ('Title', 'Some content')
            **Title** -> ('Title', '')
            **Title** Some text -> ('Title', 'Some text')

        Returns:
            tuple: (title, inline_content) where inline_content can be empty
        """
        stripped = line.strip()
        # Find the closing **
        start = 2  # After opening **
        end = stripped.find('**', start)

        if end == -1:
            # Malformed, treat whole thing as title
            return stripped[2:], ''

        title = stripped[start:end]
        # Strip trailing colon and whitespace
        title = title.rstrip(':').strip()
        inline_content = stripped[end+2:].strip()  # Strip leading/trailing whitespace

        return title, inline_content

    def promote_bold_headers_in_node(node):
        """Recursively convert bold headers in content to child sections."""
        # CRITICAL: Save original children BEFORE adding new ones
        # New bold header nodes are LEAVES - don't recurse on them
        original_children = list(node.children)

        # Process this node's content if it has any
        if node.content:
            # Join all content and split by lines for processing
            full_content = '\n'.join(node.content)
            lines = full_content.split('\n')
            # Fence-aware: a **Bold:** line inside a ``` block is body, not a header.
            _fence = _fence_line_flags(lines)

            def bold_at(k):
                return is_bold_header(lines[k]) and not _fence[k]

            new_children = []
            initial_content = []
            final_content = []

            i = 0

            # Phase 1: Initial content (before first bold header)
            while i < len(lines) and not bold_at(i):
                initial_content.append(lines[i])
                i += 1

            # Phase 2: Process bold headers
            while i < len(lines):
                if not bold_at(i):
                    # Hit non-bold content after bold headers - this is final content
                    break

                # Extract title and any inline content
                title, inline_content = extract_bold_title_and_inline_content(lines[i])

                # Create child at parent_level + 1
                child_level = node.level + 1 if node.level > 0 else 1

                # Safety check: Skip if would exceed markdown max depth (6 levels)
                if child_level > 6:
                    print(f"⚠ WARNING: Skipping '{title}' - would exceed markdown max depth (level {child_level} > 6)")
                    i += 1
                    # Skip content until next bold header
                    while i < len(lines) and not bold_at(i):
                        i += 1
                    continue

                child_node = MarkdownNode(child_level, title)

                # Collect content starting with inline content, then subsequent lines
                i += 1
                child_content_lines = []

                # Add inline content if present
                if inline_content:
                    child_content_lines.append(inline_content)

                # Collect content until: next bold header OR \n\n + content (final content marker)
                while i < len(lines) and not bold_at(i):
                    # Check for \n\n separator (empty line followed by content)
                    if (not lines[i].strip() and
                        i+1 < len(lines) and
                        lines[i+1].strip() and
                        not bold_at(i+1)):
                        # Found final content separator
                        i += 1  # Skip the empty line
                        break
                    child_content_lines.append(lines[i])
                    i += 1

                # Join and ensure at least ' ' for proper sibling parsing
                if child_content_lines:
                    final_child_content = '\n'.join(child_content_lines)
                    # If content is empty or only whitespace, use single space
                    if not final_child_content.strip():
                        final_child_content = ' '
                    child_node.content = [final_child_content]
                else:
                    child_node.content = [' ']  # Space maintains sibling relationship
                new_children.append(child_node)

            # Phase 3: Final content (everything remaining after bold headers)
            while i < len(lines):
                final_content.append(lines[i])
                i += 1

            # Set parent content: initial + \n + final
            parent_parts = []
            if initial_content:
                parent_parts.append('\n'.join(initial_content))
            if final_content:
                parent_parts.append('\n'.join(final_content))

            if parent_parts:
                node.content = ['\n'.join(parent_parts)]
            else:
                node.content = []

            # Add new children to existing children
            for child in new_children:
                node.add_child(child)

        # CRITICAL: Only recurse on ORIGINAL children (not newly promoted bold headers)
        for child in original_children:
            promote_bold_headers_in_node(child)

    # Process from the resolved start node (root for whole-file, else the section subtree)
    promote_bold_headers_in_node(start_node)

    result = tree.dump()
    if dry_run:
        print(result)
        print(f"\n--- DRY RUN: bold headers in '{resolved}' would become child headings "
              f"(no write) ---", file=sys.stderr)
        return True
    create_backup(file_path, 'md_tools')
    commit(file_path, result)
    print(f"✓ Converted bold headers to child headings in '{resolved}' of {file_path}")
    return True


def _replace_node_body(node, content, remove_subsections=False):
    """In-memory primitive: set a node's body content and optionally drop subsections.

    Shared by replace_section.
    """
    node.content = [content] if content else []
    if remove_subsections:
        node.children = []


def _flatten_in_place(node):
    """Collapse `node`'s subtree IN PLACE: every descendant becomes a flat direct
    child of node (re-leveled to node.level+1, nesting dropped); node's body kept."""
    flat = []

    def gather(n):
        for c in n.children:
            flat.append(c)
            gather(c)

    gather(node)
    for d in flat:
        d.children = []
        d.level = node.level + 1
        d.parent = node
    node.children = flat


def reshape_section_bare(file_path, section_path, *, keep=None, omit=None, flatten=False,
                         strip_body=None, strip_markers_flag=False):
    """Apply SELECT/TRANSFORM to a section's subtree IN PLACE (the file is rewritten).

    The "emit to the same location" verb — SECTION is the HEAD; its subtree is pruned
    (keep/omit) and/or reshaped (flatten / strip-body / strip-markers), and the file
    is written back. The head node + its heading always stay; keep/omit PRUNE in place
    (prune-preserve, not lift). At least one flag is required.
        reshape FILE X --strip-all-body-text   -> heading skeleton (X + descendants)
        reshape FILE X --strip-child-body-text -> X's body kept, descendants stripped
        reshape FILE X --omit Y                -> drop Y from X
        reshape FILE X --keep A:,:B            -> keep only A, B (and their paths) under X
    """
    if not (keep or omit or flatten or strip_body or strip_markers_flag):
        print("reshape: nothing to do — pass a SELECT/TRANSFORM flag "
              "(--keep-sections/--omit-sections/--flatten/--strip-*-body-text/--strip-markers).",
              file=sys.stderr)
        return False
    tree = MarkdownTree()
    with open(file_path, 'r', encoding='utf-8') as f:
        tree.parse(f.read())
    # _resolve_head (not parse_and_resolve) so "." = the file's H1 head resolves, and
    # the verb can be driven by `extract` with a "." head.
    node = _resolve_head(tree, section_path)
    if node is None:
        print(f"reshape: section '{section_path}' not found in {file_path}", file=sys.stderr)
        return False
    resolved_path = build_node_path(node) or section_path
    changed = False
    # SELECT — prune the head's subtree in place (keep then omit-within-kept).
    if keep:
        keep_nodes = _resolve_keep_omit_paths(node, keep, "keep")
        if not keep_nodes:
            # Guard: a --keep that resolves NOTHING would prune the section empty.
            # Refuse — leave the subtree intact (so a typo can't wipe it).
            print(f"reshape: no --keep path resolved under '{resolved_path}'; "
                  f"section left unchanged.", file=sys.stderr)
        else:
            _prune_to_keep_closure(node, keep_nodes)
            changed = True
    if omit:
        for n in _resolve_keep_omit_paths(node, omit, "omit"):
            if n.parent is not None:
                n.parent.remove_child(n)
                changed = True
    # TRANSFORM — flatten -> strip body -> strip markers, on the head's subtree.
    if flatten:
        _flatten_in_place(node); changed = True
    if strip_body:
        strip_bodies(node, strip_body); changed = True
    if strip_markers_flag:
        strip_markers(node); changed = True
    # Only write (and back up) when something actually changed — so a no-op reshape
    # (e.g. a --keep that resolved nothing) leaves the file byte-identical.
    if not changed:
        print(f"reshape: no change to '{resolved_path}' in {file_path}.", file=sys.stderr)
        return True
    create_backup(file_path, "md_tools")
    commit(file_path, tree.dump())
    print(f"✓ Reshaped section '{resolved_path}' in {file_path}")
    return True


def _split_at_first_unfenced_header(text):
    """Split text at the first markdown header line NOT inside a code fence.

    The parser drops any preamble *before* the first header (it only captures
    content that follows a header), so a structured replace must peel the leading
    body off the raw string itself rather than reading it back from a parsed tree.

    Returns:
        (head, rest): head = body text before the first unfenced header (trailing
        newlines stripped); rest = text from that header onward. If there is no
        unfenced header, head == text and rest == "".
    """
    probe = MarkdownTree()
    fence_ranges = probe._find_code_fence_ranges(text)
    for m in MarkdownTree.HEADER_REGEX.finditer(text):
        if not probe._is_inside_code_fence(m.start(), fence_ranges):
            return (text[:m.start()].rstrip("\n"), text[m.start():])
    return (text, "")


def _dedent_headers(text):
    """Shift all unfenced header levels so the shallowest becomes level 1.

    The parser nests via a stack whose depth assumes headers start at level 1; a
    fragment whose top headers are deeper (e.g. '### Child' with no '#'/'##' above)
    makes equal-level siblings nest under each other. Dedenting to level 1 restores
    correct sibling parsing; the caller re-levels afterward via copy_with_level_delta.
    """
    probe = MarkdownTree()
    fence_ranges = probe._find_code_fence_ranges(text)
    matches = [m for m in MarkdownTree.HEADER_REGEX.finditer(text)
               if not probe._is_inside_code_fence(m.start(), fence_ranges)]
    if not matches:
        return text
    shift = min(len(m.group(1)) for m in matches) - 1
    if shift <= 0:
        return text
    out, last = [], 0
    for m in matches:
        out.append(text[last:m.start()])
        out.append('#' * (len(m.group(1)) - shift) + ' ' + m.group(2))
        last = m.end()
    out.append(text[last:])
    return ''.join(out)


def replace_section_bare(file_path, section_path, content, remove_subsections=False, full_subtree=False):
    """Replace a section's body in place (heading preserved).

    Default = MERGE: parse `content`; its leading body replaces the body, its headers
    upsert children by title (same -> replaced, new -> added, unnamed -> kept). A body-only
    payload just replaces the body; fenced headers stay literal.

    full_subtree: clobber — the fragment's children become the only children (rest dropped).
    remove_subsections: replace the body and drop all children.
    """
    create_backup(file_path, 'md_tools')

    tree, node, resolved_path = parse_and_resolve(file_path, section_path)
    if not tree:
        return False

    head, rest = _split_at_first_unfenced_header(content)

    if remove_subsections and not full_subtree:
        # Replace body, drop all children (no new children supplied).
        _replace_node_body(node, content, remove_subsections=True)
    else:
        # Merge (default), or clobber (--full-subtree clears children first, so the
        # merge into an empty set becomes a wholesale replace).
        node.content = [head] if head.strip() else []
        if full_subtree:
            node.children = []
        if rest:
            frag = MarkdownTree()
            frag.parse(_dedent_headers(rest))
            # Marker-transparent upsert of the fragment's headers into node's children
            # (I4). clobber_body=False: replace already set node.content above; the
            # per-child rule inside (clobber by bool(child.content)) refreshes a
            # re-typed child's body while keeping un-named children.
            _merge_node_into(node, frag.root, clobber_body=False)

    commit(file_path, tree.dump())

    if full_subtree:
        suffix = " (full-subtree: body + children replaced)"
    elif remove_subsections:
        suffix = " (subsections removed)"
    elif rest:
        suffix = " (merged children)"
    else:
        suffix = ""
    print(f"✓ Replaced body of section '{resolved_path}' in {file_path}{suffix}")
    return True


def reorder_sections_bare(file_path, section_names, parent_path=""):
    """Reorder sections within a parent, moving specified ones to top.

    Sections not mentioned retain their original relative order and appear after
    the specified sections. All sections stay at the same hierarchy level.

    Args:
        file_path: Markdown file to modify
        section_names: :,:-separated list of section titles to reorder
        parent_path: Parent section path (empty = the file's single H1 root, so a
                     parent-less reorder reorders its ## sections; falls back to the
                     synthetic ROOT only when there is no single H1)
    """
    create_backup(file_path, 'md_tools')

    # Get parent node
    if parent_path in ("", "ROOT"):
        tree = MarkdownTree()
        with open(file_path, 'r', encoding='utf-8') as f:
            tree.parse(f.read())
        # Default = the single H1 root, so a parent-less reorder reorders the
        # file's `##` sections (the H1's children), not the lone H1 under the
        # synthetic ROOT. Mirror _resolve_head; fall back to ROOT for multi-root.
        if detect_single_root(tree):
            parent = tree.root.children[0]
            parent_display = parent.title
        else:
            parent = tree.root
            parent_display = "root"
    else:
        tree, parent, resolved_path = parse_and_resolve(file_path, parent_path)
        if not tree:
            return False
        parent_display = parent_path

    # Get current children
    current_children = parent.children[:]
    if not current_children:
        print(f"No sections found under '{parent_display}'")
        return False

    # Parse desired section names
    desired_names = [name.strip() for name in section_names.split(':,:')]

    # Build reordered list
    reordered = []
    missing = []

    # Resolve each name against the siblings, mirroring the path resolver's tiering:
    # an EXACT title wins outright (so a caller can always disambiguate by typing the
    # full heading), else a UNIQUE marker-transparent match via _title_key — the same
    # normalization the resolver and the EMIT merger apply, so a caller need not retype
    # a ' [state] [v1] (#)' zone that drifts independently of the title. An
    # already-claimed child is skipped, so a repeated name cannot consume one node twice.
    #
    # AMBIGUITY REFUSES, matching the resolver contract ("unique wins; ambiguity
    # refuses"). Two siblings differing only by marker — '### Foo  [ ]' and
    # '### Foo  [x]' — normalize to the same key, and silently taking the first would
    # reorder a section the caller did not name.
    for name in desired_names:
        avail = [c for c in current_children if c not in reordered]
        exact = [c for c in avail if c.title == name]
        found = exact[0] if exact else None
        if found is None:
            cand = [c for c in avail if _title_key(c.title) == _title_key(name)]
            if len(cand) > 1:
                print(f"Error: Ambiguous section '{name}' under '{parent_display}' — "
                      f"{len(cand)} siblings match once markers are ignored.",
                      file=sys.stderr)
                for c in cand:
                    print(f"  - {c.title}", file=sys.stderr)
                print("  Pass the exact full heading (including its marker zone) "
                      "to disambiguate.", file=sys.stderr)
                return False
            if cand:
                found = cand[0]
        if found:
            reordered.append(found)
        else:
            missing.append(name)
            print(f"Warning: Section '{name}' not found, skipping", file=sys.stderr)

    # Nothing matched => nothing to do. Report it as a FAILURE rather than printing a
    # ✓ over a no-op: a non-interactive caller cannot otherwise distinguish "already in
    # the requested order" from "matched none of the names I gave you".
    if not reordered:
        print(f"Error: no sections matched under '{parent_display}' — nothing reordered.",
              file=sys.stderr)
        print(f"  Requested: {desired_names}", file=sys.stderr)
        print(f"  Available: {[c.title for c in current_children]}", file=sys.stderr)
        return False

    # Then, add remaining sections in original order
    remaining = [child for child in current_children if child not in reordered]

    # Replace parent's children with reordered list
    parent.children = reordered + remaining

    # Write back
    commit(file_path, tree.dump())

    skipped = f", {len(missing)} not found" if missing else ""
    print(f"✓ Reordered {len(reordered)} section(s) under '{parent_display}' "
          f"(+ {len(remaining)} unchanged{skipped})")
    return True


def extract_abridge_section(file_path, section_path, output_file):
    """Copy a section to OUTPUT (full content), then strip the SOURCE section to a
    heading skeleton in place (leave breadcrumbs). A thin wrapper composing two tools:
    `copy` (full → output) + `reshape --strip-all-body-text` (source → skeleton). Holds
    both files' locks for the whole copy+reshape and calls the *_bare forms (a wrapped
    sub-verb would re-acquire LOCK_EX on file_path and self-deadlock)."""
    output_file = resolve_output_path(file_path, output_file)
    with multi_file_lock(file_path, output_file):
        ok = copy_section_bare(file_path, section_path, output_file)
        if ok:
            ok = reshape_section_bare(file_path, section_path, strip_body="all")
    return ok


def run_tests():
    """Run built-in unit tests for all functions."""
    import tempfile
    import shutil
    import os
    import glob

    print("Running unit tests...")

    # Output directory for inspection
    output_dir = "/tmp/claude_md_tests"
    os.makedirs(output_dir, exist_ok=True)
    print(f"Test outputs will be saved to: {output_dir}\n")

    # Test file template
    TEST_CONTENT = """# Test Document

## Section A
Content in section A.

### A1
Content in A1.

### A2
Content in A2.

## Section B
Content in section B.

### B1
Content in B1.

#### B1a
Content in B1a.

## Section C
Content in section C.

### C1
Content in C1.

## Target
Target section with existing children.

### T1
Existing child T1.

### T2
Existing child T2.

## Other
This section should remain unchanged.
"""

    test_dir = tempfile.mkdtemp()
    passed = 0
    failed = 0

    try:
        # Test 1: Move sections (bulk with order preservation)
        print("\n[Test 1] move_sections with multiple sections...")
        test_file = f"{test_dir}/test_move_sections.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        # Move multiple sections after Target.T1
        move_sections(test_file, None, "Test Document:/:Section A:,:Test Document:/:Section C",
                     parent_path="Test Document:/:Target", after_sibling="T1", flatten=False)

        tree = MarkdownTree()
        with open(test_file, 'r') as f:
            tree.parse(f.read())

        target = tree.find_node_by_path("Test Document:/:Target")
        if target and len(target.children) >= 4:  # T1, A, C, T2
            # Check order: children should be T1, A, C, T2
            children_titles = [child.title for child in target.children]
            if children_titles[:3] == ["T1", "Section A", "Section C"]:
                # Check A's children preserved
                a_node = tree.find_node_by_path("Test Document:/:Target:/:Section A")
                if a_node and len(a_node.children) == 2:  # A1, A2
                    print("✓ PASS: Multiple sections moved in order, hierarchy preserved")
                    passed += 1
                else:
                    print("✗ FAIL: Section A children not preserved")
                    failed += 1
            else:
                print(f"✗ FAIL: Order not preserved. Got: {children_titles[:3]}")
                failed += 1
        else:
            print("✗ FAIL: Sections not moved correctly")
            failed += 1

        # Test 2: Reshape — in-place strip-all-body-text (heading skeleton)
        print("\n[Test 2] reshape --strip-all-body-text command...")
        test_file = f"{test_dir}/test_reshape.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        reshape_section(test_file, "Test Document:/:Section A", strip_body="all")

        # Save output for inspection
        tree = MarkdownTree()
        with open(test_file, 'r') as f:
            tree.parse(f.read())
        with open(f"{output_dir}/test2_reshape_output.md", 'w') as f:
            f.write(tree.dump())

        with open(test_file, 'r') as f:
            result = f.read()

        if "Content in section A" not in result and "## Section A" in result and "### A1" in result:
            print("✓ PASS: Content removed, headers preserved")
            passed += 1
        else:
            print("✗ FAIL: reshape strip-all did not work correctly")
            failed += 1

        # Test 3: extract-to-file-keep-breadcrumbs = copy (full) + reshape --strip-all-body-text
        print("\n[Test 3] copy + reshape (extract full, strip source)...")
        test_file = f"{test_dir}/test_copy_reshape.md"
        output_file = f"{test_dir}/extracted.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        copy_section(test_file, "Test Document:/:Section B", output_file)
        reshape_section(test_file, "Test Document:/:Section B", strip_body="all")

        with open(output_file, 'r') as f:
            extracted = f.read()
        with open(test_file, 'r') as f:
            original = f.read()

        # Output keeps full content; source has headers only.
        if ("Content in section B" in extracted and
            "Content in section B" not in original and
            "## Section B" in original and
            "### B1" in original):
            print("✓ PASS: copy kept full content, reshape stripped source to headers")
            passed += 1
        else:
            print("✗ FAIL: copy + reshape did not work correctly")
            failed += 1

        # Test 3.5: Replace section body
        print("\n[Test 3.5] replace command...")
        test_file = f"{test_dir}/test_replace.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        # Default mode: replace body, preserve subsections
        replace_section(test_file, "Test Document:/:Section A", "REPLACED BODY")
        with open(test_file, 'r') as f:
            result = f.read()
        default_ok = ("REPLACED BODY" in result and
                      "Content in section A." not in result and
                      "### A1" in result and
                      "Content in A1." in result)

        # remove_subsections=True: replace body AND drop children
        replace_section(test_file, "Test Document:/:Section B",
                        "REPLACED B", remove_subsections=True)
        with open(test_file, 'r') as f:
            result = f.read()
        strip_ok = ("REPLACED B" in result and
                    "### B1" not in result and
                    "Content in section B." not in result)

        # Empty content clears the body
        replace_section(test_file, "Test Document:/:Section C", "")
        with open(test_file, 'r') as f:
            result = f.read()
        empty_ok = ("Content in section C." not in result and
                    "## Section C" in result and
                    "### C1" in result)

        if default_ok and strip_ok and empty_ok:
            print("✓ PASS: replace preserves subsections by default, removes them with flag, clears with empty content")
            passed += 1
        else:
            print(f"✗ FAIL: replace (default={default_ok}, remove_subsections={strip_ok}, empty={empty_ok})")
            failed += 1

        # Test 4: Cleanup-backups
        print("\n[Test 4] cleanup-backups command...")
        # Create multiple backups for same file
        backup_base = f"{test_dir}/test_cleanup"
        with open(f"{backup_base}.backup_20251001_100000.md", 'w') as f:
            f.write("# Old backup 1")
        with open(f"{backup_base}.backup_20251001_120000.md", 'w') as f:
            f.write("# Old backup 2")
        with open(f"{backup_base}.backup_20251001_150000.md", 'w') as f:
            f.write("# Most recent backup")

        # Also create backups for another file
        backup_base2 = f"{test_dir}/another_file"
        with open(f"{backup_base2}.backup_20251002_100000.md", 'w') as f:
            f.write("# Old backup")
        with open(f"{backup_base2}.backup_20251002_140000.md", 'w') as f:
            f.write("# Recent backup")

        cleanup_backups(test_dir)

        # Check that only most recent backups remain for our test files
        test_cleanup_backups = glob.glob(f"{backup_base}.backup_*.md")
        another_backups = glob.glob(f"{backup_base2}.backup_*.md")

        if (len(test_cleanup_backups) == 1 and
            f"{backup_base}.backup_20251001_150000.md" in test_cleanup_backups and
            len(another_backups) == 1 and
            f"{backup_base2}.backup_20251002_140000.md" in another_backups):
            print("✓ PASS: Cleanup kept only most recent backups")
            passed += 1
        else:
            print(f"✗ FAIL: Expected 1 backup each, got {len(test_cleanup_backups)} and {len(another_backups)}")
            failed += 1

        # Test 5: list-paths
        print("\n[Test 5] list-paths output...")
        test_file = f"{test_dir}/test_list_paths.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        import io
        from contextlib import redirect_stdout
        captured = io.StringIO()
        with redirect_stdout(captured):
            list_paths(test_file)
        paths_output = captured.getvalue().strip().split('\n')

        # Should contain :/:-separated paths
        expected_paths = [
            "Test Document",
            "Test Document:/:Section A",
            "Test Document:/:Section A:/:A1",
            "Test Document:/:Section A:/:A2",
            "Test Document:/:Section B",
            "Test Document:/:Section B:/:B1",
            "Test Document:/:Section B:/:B1:/:B1a",
        ]
        all_found = all(p in paths_output for p in expected_paths)
        no_dots = all("." not in p for p in paths_output)  # No dot separators
        if all_found and no_dots:
            print(f"✓ PASS: list-paths output correct ({len(paths_output)} paths, all use :/: separator)")
            passed += 1
        else:
            missing = [p for p in expected_paths if p not in paths_output]
            print(f"✗ FAIL: list-paths missing paths: {missing}")
            failed += 1

        # Test 6: Case-insensitive resolution
        print("\n[Test 6] case-insensitive path resolution...")
        test_file = f"{test_dir}/test_case.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        tree = MarkdownTree()
        with open(test_file, 'r') as f:
            tree.parse(f.read())

        # Lowercase path should resolve to correct node
        node, error_printed = find_node_with_suggestions(tree, "test document:/:section a:/:a1")
        if node and node.title == "A1" and not error_printed:
            print("✓ PASS: Case-insensitive resolution found correct node")
            passed += 1
        else:
            print(f"✗ FAIL: Case-insensitive resolution failed (node={node}, error_printed={error_printed})")
            failed += 1

        # Test 7: Fuzzy suggestions on bad path
        print("\n[Test 7] fuzzy suggestions on failed path...")
        all_paths = collect_all_paths(tree.root)
        suggestions = suggest_matches("Section B", all_paths)
        if any("Section B" in s for s in suggestions):
            print(f"✓ PASS: Fuzzy suggestions found relevant matches ({len(suggestions)} suggestions)")
            passed += 1
        else:
            print(f"✗ FAIL: Fuzzy suggestions returned no relevant matches: {suggestions}")
            failed += 1

        # Test 8: Separator collision regression (dots, colons, R syntax in headers)
        print("\n[Test 8] separator collision regression...")
        collision_content = """# Root

## Section 2.1 Setup
Content about version 2.1.

## CRITICAL: Git Scope
Important git rules.

## Using dplyr::filter
R code examples.

## Methods, Results
Combined section.

## pkg:::internal_fn
Internal R function docs.
"""
        test_file = f"{test_dir}/test_collision.md"
        with open(test_file, 'w') as f:
            f.write(collision_content)

        tree = MarkdownTree()
        with open(test_file, 'r') as f:
            tree.parse(f.read())

        # All these should resolve correctly — dots, colons, commas, :: and ::: in titles
        collision_tests = [
            ("Root:/:Section 2.1 Setup", "Section 2.1 Setup"),
            ("Root:/:CRITICAL: Git Scope", "CRITICAL: Git Scope"),
            ("Root:/:Using dplyr::filter", "Using dplyr::filter"),
            ("Root:/:Methods, Results", "Methods, Results"),
            ("Root:/:pkg:::internal_fn", "pkg:::internal_fn"),
        ]
        collision_passed = True
        for path, expected_title in collision_tests:
            node = tree.find_node_by_path(path)
            if not node or node.title != expected_title:
                print(f"  ✗ Failed: '{path}' → got {node.title if node else None}, expected '{expected_title}'")
                collision_passed = False

        if collision_passed:
            print(f"✓ PASS: All separator collision cases resolved ({len(collision_tests)} headers with dots, colons, commas, ::, :::)")
            passed += 1
        else:
            print("✗ FAIL: Some separator collision cases failed")
            failed += 1

        # Test 9: Error message format
        print("\n[Test 9] error message format on bad path...")
        captured_err = io.StringIO()
        import contextlib
        with contextlib.redirect_stderr(captured_err):
            node, error_printed = find_node_with_suggestions(tree, "Root:/:Nonexistent Section", test_file)
        err_output = captured_err.getvalue()

        has_error_line = 'No exact match for path' in err_output
        has_top_level = 'Top-level sections:' in err_output
        has_hint = 'list-paths' in err_output
        if node is None and error_printed and has_error_line and has_top_level and has_hint:
            print("✓ PASS: Error message has structured format (error, top-level sections, list-paths hint)")
            passed += 1
        else:
            print(f"✗ FAIL: Error message format incorrect. has_error={has_error_line}, has_top_level={has_top_level}, has_hint={has_hint}")
            failed += 1

        # Test 10: Leaf resolution — unique prefix match
        print("\n[Test 10] leaf resolution: unique prefix match...")
        leaf_content = """# Doc

## Git Commit Best Practices
Git commit content.

## CRITICAL: Git Safety Protocol
Safety content.

## Variable Renaming Standards
Renaming content.

## Template-Based Refactoring
Refactoring content.

## Code Audit Methodology
Audit content.
"""
        test_file = f"{test_dir}/test_leaf.md"
        with open(test_file, 'w') as f:
            f.write(leaf_content)

        tree = MarkdownTree()
        with open(test_file, 'r') as f:
            tree.parse(f.read())

        # "Variable" is a unique prefix — only "Variable Renaming Standards" starts with it
        captured_err = io.StringIO()
        with contextlib.redirect_stderr(captured_err):
            node, error_printed = find_node_with_suggestions(tree, "Variable")
        if node and node.title == "Variable Renaming Standards" and not error_printed:
            print("✓ PASS: Unique prefix 'Variable' resolved to 'Variable Renaming Standards'")
            passed += 1
        else:
            print(f"✗ FAIL: Unique prefix resolution failed (node={node.title if node else None})")
            failed += 1

        # Test 11: Leaf resolution — unique substring (not prefix)
        print("\n[Test 11] leaf resolution: unique substring match (not prefix)...")
        # "Git Safety" is a substring of "CRITICAL: Git Safety Protocol" but not a prefix
        # It's also NOT a substring of "Git Commit Best Practices"
        captured_err = io.StringIO()
        with contextlib.redirect_stderr(captured_err):
            node, error_printed = find_node_with_suggestions(tree, "Git Safety")
        if node and node.title == "CRITICAL: Git Safety Protocol" and not error_printed:
            print("✓ PASS: Unique substring 'Git Safety' resolved to 'CRITICAL: Git Safety Protocol'")
            passed += 1
        else:
            print(f"✗ FAIL: Unique substring resolution failed (node={node.title if node else None})")
            failed += 1

        # Test 12: Leaf resolution — prefix wins despite additional substring matches
        print("\n[Test 12] leaf resolution: 1 prefix match + 1 substring match...")
        # "Git Commit" is a prefix of "Git Commit Best Practices" (1 prefix hit)
        # "Git Commit" is NOT a substring of "CRITICAL: Git Safety Protocol"
        # So: 1 prefix match → auto-resolve, never checks substring
        captured_err = io.StringIO()
        with contextlib.redirect_stderr(captured_err):
            node, error_printed = find_node_with_suggestions(tree, "Git Commit")
        if node and node.title == "Git Commit Best Practices" and not error_printed:
            print("✓ PASS: Prefix match 'Git Commit' resolved (didn't fall to substring)")
            passed += 1
        else:
            print(f"✗ FAIL: Prefix-wins resolution failed (node={node.title if node else None})")
            failed += 1

        # Test 13: Leaf resolution — ambiguous prefix (multiple prefix hits)
        print("\n[Test 13] leaf resolution: ambiguous prefix (multiple hits)...")
        # "Git" is a prefix of BOTH "Git Commit Best Practices" AND "Git Safety..." — wait,
        # "CRITICAL: Git Safety..." doesn't start with "Git". So this is actually 1 prefix hit.
        # Let's use a doc with true ambiguity instead:
        ambig_content = """# Doc

## Git Commit Standards
Commit content.

## Git Safety Protocol
Safety content.

## Unrelated Section
Other content.
"""
        test_file2 = f"{test_dir}/test_ambig.md"
        with open(test_file2, 'w') as f:
            f.write(ambig_content)

        tree2 = MarkdownTree()
        with open(test_file2, 'r') as f:
            tree2.parse(f.read())

        # "Git" is prefix of both "Git Commit Standards" AND "Git Safety Protocol"
        captured_err = io.StringIO()
        with contextlib.redirect_stderr(captured_err):
            node, error_printed = find_node_with_suggestions(tree2, "Git")
        err_output = captured_err.getvalue()
        if node is None and error_printed and 'Ambiguous' in err_output:
            print("✓ PASS: Ambiguous prefix 'Git' correctly errored with multiple matches")
            passed += 1
        else:
            print(f"✗ FAIL: Ambiguous prefix should error (node={node}, err={err_output[:80]})")
            failed += 1

        # Test 14: Leaf resolution — no matches at all
        print("\n[Test 14] leaf resolution: no matches...")
        captured_err = io.StringIO()
        with contextlib.redirect_stderr(captured_err):
            node, error_printed = find_node_with_suggestions(tree, "Zzzznonexistent")
        if node is None and error_printed:
            print("✓ PASS: No-match query correctly fell through to error")
            passed += 1
        else:
            print(f"✗ FAIL: No-match should error (node={node})")
            failed += 1

        # Test 15: Leaf resolution — prefix beats coincidental substring
        print("\n[Test 15] leaf resolution: 1 prefix hit, 1 extra substring hit elsewhere...")
        # Using tree from test_leaf.md:
        # "Code" is prefix of "Code Audit Methodology" (1 prefix hit)
        # Not checking substring because prefix already found 1
        captured_err = io.StringIO()
        with contextlib.redirect_stderr(captured_err):
            node, error_printed = find_node_with_suggestions(tree, "Code")
        if node and node.title == "Code Audit Methodology" and not error_printed:
            print("✓ PASS: 'Code' resolved via prefix, ignoring any substring matches")
            passed += 1
        else:
            print(f"✗ FAIL: Prefix-beats-substring failed (node={node.title if node else None})")
            failed += 1

        # Test 16: Standalone extract preserves source
        print("\n[Test 16] extract is destructive (copy + delete)...")
        test_file = f"{test_dir}/test_extract_standalone.md"
        output_file = f"{test_dir}/extracted_standalone.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        # Read source before extract
        with open(test_file, 'r') as f:
            source_before = f.read()

        extract_section(test_file, "Test Document:/:Section A", output_file)

        # Source should have section removed, output should have it
        with open(test_file, 'r') as f:
            source_after = f.read()
        with open(output_file, 'r') as f:
            extracted = f.read()

        source_changed = source_before != source_after
        section_removed = "Content in section A" not in source_after
        extracted_has_content = "Content in section A" in extracted
        if source_changed and section_removed and extracted_has_content:
            print("✓ PASS: Extract removed section from source, copied to output")
            passed += 1
        else:
            print(f"✗ FAIL: source_changed={source_changed}, section_removed={section_removed}, extracted_has_content={extracted_has_content}")
            failed += 1

        # Test 17: Root auto-detect + leaf resolution interaction
        print("\n[Test 17] root auto-detect + leaf resolution via CLI path...")
        test_file = f"{test_dir}/test_root_leaf.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        # Simulate what list_sections does: prepend root, then visualize
        tree = MarkdownTree()
        with open(test_file, 'r') as f:
            tree.parse(f.read())
        root = detect_single_root(tree)
        # User types just "B1a" — root prepend makes it "Test Document:/:B1a"
        resolved_path = prepend_root_prefix("B1a", root)
        captured_err = io.StringIO()
        with contextlib.redirect_stderr(captured_err):
            node, error_printed = find_node_with_suggestions(tree, resolved_path)
        if node and node.title == "B1a" and not error_printed:
            print("✓ PASS: Leaf 'B1a' resolved through root auto-detect + leaf resolution")
            passed += 1
        else:
            print(f"✗ FAIL: Root+leaf interaction failed (node={node.title if node else None}, path={resolved_path})")
            failed += 1

        # Test 18: Reorder with :,: separator
        print("\n[Test 18] reorder with :,: separator...")
        test_file = f"{test_dir}/test_reorder.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        reorder_sections(test_file, "Section C:,:Section A", "Test Document")

        tree = MarkdownTree()
        with open(test_file, 'r') as f:
            tree.parse(f.read())
        root_node = tree.find_node_by_path("Test Document")
        children = [c.title for c in root_node.children]
        # Section C and A should be first two, then the rest in original order
        if children[0] == "Section C" and children[1] == "Section A":
            print("✓ PASS: Reorder with :,: separator placed sections in correct order")
            passed += 1
        else:
            print(f"✗ FAIL: Reorder order wrong: {children[:4]}")
            failed += 1

        # Test 19: Single path (no :,: delimiter) in move
        print("\n[Test 19] single path without :,: delimiter in move...")
        test_file = f"{test_dir}/test_single_move.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        # Move a single section (no :,: in the string)
        move_sections(test_file, None, "Test Document:/:Section C",
                     parent_path="Test Document:/:Target", flatten=False)

        tree = MarkdownTree()
        with open(test_file, 'r') as f:
            tree.parse(f.read())
        target = tree.find_node_by_path("Test Document:/:Target")
        target_children = [c.title for c in target.children]
        if "Section C" in target_children:
            print("✓ PASS: Single path (no :,: delimiter) moved correctly")
            passed += 1
        else:
            print(f"✗ FAIL: Single-path move failed, target children: {target_children}")
            failed += 1

        # Test 20: list-paths on empty file
        print("\n[Test 20] list-paths on file with no headers...")
        test_file = f"{test_dir}/test_empty.md"
        with open(test_file, 'w') as f:
            f.write("Just some text, no headers at all.\n\nMore text.\n")

        captured = io.StringIO()
        with redirect_stdout(captured):
            result = list_paths(test_file)
        paths_output = captured.getvalue().strip()
        if result and paths_output == "":
            print("✓ PASS: list-paths on headerless file returns empty output")
            passed += 1
        else:
            print(f"✗ FAIL: Expected empty output, got: '{paths_output[:50]}'")
            failed += 1

        # Test 21: build_node_path round-trip
        print("\n[Test 21] build_node_path round-trip...")
        test_file = f"{test_dir}/test_build_node_path.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        tree = MarkdownTree()
        with open(test_file, 'r') as f:
            tree.parse(f.read())
        # Find a nested node via fuzzy matching
        node, _ = find_node_with_suggestions(tree, "Test Document:/:Section A:/:A1")
        if node:
            built_path = build_node_path(node)
            # Round-trip: find_node_by_path should find the same node
            found = tree.find_node_by_path(built_path)
            if found is node:
                print("✓ PASS: build_node_path round-trip finds same node")
                passed += 1
            else:
                print(f"✗ FAIL: Round-trip failed, built_path='{built_path}', found={found}")
                failed += 1
        else:
            print("✗ FAIL: Could not find test node for round-trip")
            failed += 1

        # Test 22: fuzzy resolution through move_sections non-flatten
        print("\n[Test 22] fuzzy leaf resolution through move_sections...")
        test_file = f"{test_dir}/test_fuzzy_move.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        # Use leaf query "A1" (no full path) to move via non-flatten branch
        move_sections(test_file, None, "A1",
                     parent_path="Test Document:/:Target", flatten=False)

        tree = MarkdownTree()
        with open(test_file, 'r') as f:
            tree.parse(f.read())
        target = tree.find_node_by_path("Test Document:/:Target")
        target_children = [c.title for c in target.children]
        # A1 should no longer be under Section A
        section_a = tree.find_node_by_path("Test Document:/:Section A")
        a_children = [c.title for c in section_a.children]
        if "A1" in target_children and "A1" not in a_children:
            print("✓ PASS: Leaf query 'A1' resolved and moved via move_sections")
            passed += 1
        else:
            print(f"✗ FAIL: target_children={target_children}, a_children={a_children}")
            failed += 1

        # Test 23: copy_section standalone (non-destructive)
        print("\n[Test 23] copy_section standalone (source unchanged)...")
        test_file = f"{test_dir}/test_copy_standalone.md"
        output_file = f"{test_dir}/copied_standalone.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        with open(test_file, 'r') as f:
            source_before = f.read()

        copy_section(test_file, "Section A", output_file)

        with open(test_file, 'r') as f:
            source_after = f.read()
        with open(output_file, 'r') as f:
            copied = f.read()

        source_unchanged = source_before == source_after
        has_content = "Content in section A" in copied
        has_children = "A1" in copied and "A2" in copied
        if source_unchanged and has_content and has_children:
            print("✓ PASS: copy_section preserved source, output has full section")
            passed += 1
        else:
            print(f"✗ FAIL: source_unchanged={source_unchanged}, has_content={has_content}, has_children={has_children}")
            failed += 1

        # Test 24: parse_and_resolve with root prepend on bare section name
        print("\n[Test 24] parse_and_resolve with root prepend...")
        test_file = f"{test_dir}/test_parse_resolve.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        # Bare section name "Section B" should auto-prepend root "Test Document"
        tree, node, resolved_path = parse_and_resolve(test_file, "Section B")
        if tree and node and node.title == "Section B":
            expected_path = "Test Document:/:Section B"
            if resolved_path == expected_path:
                print("✓ PASS: parse_and_resolve auto-prepended root to bare section name")
                passed += 1
            else:
                print(f"✗ FAIL: resolved_path='{resolved_path}', expected='{expected_path}'")
                failed += 1
        else:
            print(f"✗ FAIL: parse_and_resolve returned tree={tree is not None}, node={node is not None}")
            failed += 1

        # Test 25: read_section prints to stdout (read-only)
        print("\n[Test 25] read_section prints to stdout...")
        test_file = f"{test_dir}/test_read_section.md"
        with open(test_file, 'w') as f:
            f.write(TEST_CONTENT)

        with open(test_file, 'r') as f:
            source_before = f.read()

        # Capture stdout
        import io
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        result = read_section(test_file, "Section A")
        sys.stdout = old_stdout
        output = captured.getvalue()

        with open(test_file, 'r') as f:
            source_after = f.read()

        source_unchanged = source_before == source_after
        has_header = "## Section A" in output
        has_content = "Content in section A" in output
        has_children = "### A1" in output and "### A2" in output
        if result and source_unchanged and has_header and has_content and has_children:
            print("✓ PASS: read_section printed section to stdout, source unchanged")
            passed += 1
        else:
            print(f"✗ FAIL: result={result}, source_unchanged={source_unchanged}, has_header={has_header}, has_content={has_content}, has_children={has_children}")
            failed += 1

        # Summary
        print(f"\n{'='*50}")
        print(f"Test Results: {passed} passed, {failed} failed")
        print(f"{'='*50}")

        return failed == 0

    finally:
        # Cleanup
        shutil.rmtree(test_dir)


def _regex_sub_text(text, rx, replacement, count):
    """Apply a regex substitution line by line — the engine behind `subst --regex` and
    the `gsub` alias. REPLACEMENT supports `\\1` backreferences. Returns (new_text, n)."""
    total = 0
    out = []
    for line in text.split("\n"):
        new_line, n = rx.subn(replacement, line, count=count)
        total += n
        out.append(new_line)
    return "\n".join(out), total


def _subst_text(text, rx, new, count):
    """Apply a LITERAL substitution line by line — `new` is inserted verbatim (a
    function repl, so `\\1`/`\\`/metachars in it stay literal). (new_text, n)."""
    total = 0
    out = []
    for line in text.split("\n"):
        new_line, n = rx.subn(lambda m: new, line, count=count)
        total += n
        out.append(new_line)
    return "\n".join(out), total


def subst_file_bare(file_path, old, new, section_path=None, dry_run=False,
                    ignore_case=False, all_matches=False, regex=False):
    """Find/replace OLD->NEW; whole-file body or one --section subtree, under a write lock.

    Default is LITERAL fixed-string: OLD/NEW are positional literals — regex metacharacters
    match themselves and NEW is inserted verbatim (no delimiter, nothing to escape). With
    regex=True (the `--regex` flag, and the `gsub` verb), OLD is a Python regex and NEW
    supports `\\1` backreferences. Default replaces the FIRST match per line; all_matches
    (--all) replaces every match. Whole-file leaves leading YAML frontmatter opaque;
    --section never touches heading titles (paths stay stable).
    """
    flags = re.IGNORECASE if ignore_case else 0
    count = 0 if all_matches else 1
    if regex:
        rx = re.compile(old, flags)                              # OLD is a Python regex
        sub_text = lambda t: _regex_sub_text(t, rx, new, count)  # NEW supports \1 backrefs
        label = "gsub"
    else:
        rx = re.compile(re.escape(old), flags)                   # OLD literal
        sub_text = lambda t: _subst_text(t, rx, new, count)      # NEW inserted verbatim
        label = "subst"

    if section_path is None:
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()
        prefix, body = _frontmatter_split(raw)
        new_body, n = sub_text(body)
        # Canonicalize blank runs on this raw whole-file write (the section-scoped branch
        # goes through tree.dump(), which already does this); frontmatter held opaque.
        new_body = normalize_blank_runs(new_body)
        new_text = prefix + new_body
        scope = file_path
    else:
        tree, node, resolved_path = parse_and_resolve(file_path, section_path)
        if not tree:
            return False
        counter = [0]

        def apply(nd):
            new_content = []
            for block in nd.content:
                nb, n = sub_text(block)
                counter[0] += n
                new_content.append(nb)
            nd.content = new_content
            for ch in nd.children:
                apply(ch)

        apply(node)
        new_text = tree.dump()
        n = counter[0]
        scope = f"section '{resolved_path}' of {file_path}"

    if dry_run:
        sys.stdout.write(new_text)
        if not new_text.endswith("\n"):
            sys.stdout.write("\n")
        print(f"--- {label} (dry-run): {n} substitution(s) in {scope}; not written ---", file=sys.stderr)
        return True
    if n == 0:
        print(f"{label}: no matches in {scope}; file left unchanged.", file=sys.stderr)
        return True
    create_backup(file_path, "md_tools")
    commit(file_path, new_text)
    print(f"✓ {label}: {n} substitution(s) in {scope}")
    return True


def body_line_append_bare(file_path, section_path, text, top=False):
    """Append a body LINE/ITEM (a bullet or prose line) to a section's body
    (bottom by default; top=True prepends). For a child HEADING/section, use `insert`.

    Why a dedicated verb: a bullet is body TEXT, not a tree node, so md_tools' section
    ops (move/reorder/replace/delete) cannot address an individual bullet — append is
    the only operation available for one. If a bullet list later becomes a
    reorganization target, `convert` its bullets to leaf headings (then the entries are
    nodes and the full section ops apply).
    """
    # Mechanic (invisible transient — not user-facing): a heading line passed as `text`
    # lands in the body and is re-promoted to a child on the NEXT parse; the body block
    # is joined with a single newline, so it is non-canonical (missing the standard blank
    # line) only until that reparse+dump normalizes it. Use `insert` for a child heading.
    block = text.rstrip("\n")
    if not block.strip():
        print("item-append: empty content; nothing to append.", file=sys.stderr)
        return False
    create_backup(file_path, "md_tools")
    tree, node, resolved_path = parse_and_resolve(file_path, section_path)
    if not tree:
        return False
    if top:
        node.content.insert(0, block)
    else:
        node.content.append(block)
    commit(file_path, tree.dump())
    where = "top" if top else "bottom"
    print(f"✓ Appended item to {where} of '{resolved_path}' in {file_path}")
    return True


def line_append_bare(file_path, text):
    """Append a raw line to a flat append-only file via O_APPEND (no tree, no read).

    For the user-global ACTIVITY_LOG.md and similar flat logs. The lock still
    matters: O_APPEND only serializes append-vs-append, not append-vs-rewrite, so
    a concurrent item_append / replace could otherwise read-modify-write this line
    away. The file is created if absent.
    """
    line = text if text.endswith("\n") else text + "\n"
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"✓ Appended line to {file_path}")
    return True


def rename_section_bare(file_path, section_path, new_title=None, state=None, tier=None):
    """Retitle a section node in place; body and child subsections are preserved.

    Two ways to call it. `new_title` replaces the whole heading. `state` / `tier`
    instead edit ONE marker in place and leave every other byte of the heading
    alone — which is the point: rebuilding a full title by hand to change one tag
    is how a v-tier, a provisional '*' or a priority paren gets silently dropped.

    The path/list separators (:/:, :,:) are forbidden in a title — they would break
    later path resolution. Descendant paths shift to use the new title, so use the
    new title for any subsequent ops in the same script.
    """
    if new_title is not None:
        if ":/:" in new_title or ":,:" in new_title:
            print("rename: new title may not contain the path separator ':/:' or list separator ':,:'.",
                  file=sys.stderr)
            return False
        if not new_title.strip():
            print("rename: new title is empty.", file=sys.stderr)
            return False
    elif state is None and tier is None:
        print("rename: pass --to for a full retitle, or --state / --tier to edit one marker.",
              file=sys.stderr)
        return False

    create_backup(file_path, "md_tools")
    tree, node, resolved_path = parse_and_resolve(file_path, section_path)
    if not tree:
        return False
    if node.parent is None or node.level == 0:
        print("rename: cannot rename the document root.", file=sys.stderr)
        return False
    old_title = node.title

    if new_title is None:
        # Marker-slot edits, applied to the CURRENT heading so untouched markers
        # survive byte-identical. State is bracket 0, depth-tier bracket 1.
        candidate = node.title
        for slot, value, flag in ((0, state, "--state"), (1, tier, "--tier")):
            if value is None:
                continue
            updated = _set_bracket_marker(candidate, slot, value)
            if updated is None:
                print(f"rename: cannot set {flag} on '{node.title}' — it has no state "
                      f"bracket to sit after. Set --state first, or pass --to with the "
                      f"full heading.", file=sys.stderr)
                return False
            candidate = updated
        new_title = candidate

    node.title = new_title.strip()
    commit(file_path, tree.dump())
    print(f"✓ Renamed '{old_title}' -> '{node.title}' in {file_path}")
    return True


# ============================================================================
# Public locking wrappers
# ----------------------------------------------------------------------------
# Every write verb acquires the directory flock for its write target(s) and
# commits atomically; the *_bare workers above do the real read-modify-write. The
# lock spans the ENTIRE read-modify-write (not just the final write), so a second
# concurrent md_tools process cannot interleave and drop an update. The composer
# `extract` holds its own lock and calls the *_bare forms directly to avoid a
# self-deadlocking second LOCK_EX on the same directory.
# ============================================================================

def copy_section(source_file, section_path, output_file, *, keep=None, omit=None,
                 children=False, depth=1, flatten=False, strip_body=None,
                 strip_markers_flag=False, parent=None, after_sibling=None,
                 policy="merge"):
    target = resolve_output_path(source_file, output_file)
    # Lock BOTH source and target (I13): copy reads the source and writes the target,
    # so a concurrent writer to either must serialize. multi_file_lock dedups same-dir
    # realpaths, so a same-directory source/target locks once (no deadlock).
    return _locked([source_file, target], copy_section_bare, source_file, section_path,
                   output_file, keep=keep, omit=omit, children=children, depth=depth,
                   flatten=flatten, strip_body=strip_body, strip_markers_flag=strip_markers_flag,
                   parent=parent, after_sibling=after_sibling, policy=policy)


def delete_section(input_file, section_path):
    return _locked([input_file], delete_section_bare, input_file, section_path)


def insert_section(input_file, parent_path, content, after_sibling=None,
                   before_sibling=None, policy="merge"):
    return _locked([input_file], insert_section_bare, input_file, parent_path, content,
                   after_sibling=after_sibling, before_sibling=before_sibling,
                   policy=policy)


def move_sections(source_file, target_file, section_paths, parent_path=None,
                  after_sibling=None, flatten=False, keep=None, omit=None,
                  children=False, depth=1, strip_body=None, strip_markers_flag=False):
    target = target_file if target_file is not None else source_file
    return _locked([source_file, target], move_sections_bare, source_file, target_file,
                   section_paths, parent_path=parent_path, after_sibling=after_sibling,
                   flatten=flatten, keep=keep, omit=omit, children=children, depth=depth,
                   strip_body=strip_body, strip_markers_flag=strip_markers_flag)


def reshape_section(file_path, section_path, *, keep=None, omit=None, flatten=False,
                    strip_body=None, strip_markers_flag=False):
    return _locked([file_path], reshape_section_bare, file_path, section_path,
                   keep=keep, omit=omit, flatten=flatten, strip_body=strip_body,
                   strip_markers_flag=strip_markers_flag)


def abridge_section(file_path, section_path):
    """Strip a section's subtree to a heading skeleton in place — a thin wrapper for
    the common `reshape --strip-all-body-text`. Single-file in-place, so it delegates
    to the (locking) public `reshape_section`; no own lock needed."""
    return reshape_section(file_path, section_path, strip_body="all")


def replace_section(file_path, section_path, content, remove_subsections=False, full_subtree=False):
    return _locked([file_path], replace_section_bare, file_path, section_path, content,
                   remove_subsections=remove_subsections, full_subtree=full_subtree)


def reorder_sections(file_path, section_names, parent_path=""):
    return _locked([file_path], reorder_sections_bare, file_path, section_names, parent_path)


def convert_to_headings(file_path, section_path=None, mode="bullets", body_marker="\n",
                        level=None, dry_run=False, checkbox_to_trailing=False):
    return _locked([file_path], convert_to_headings_bare, file_path,
                   section_path=section_path, mode=mode, body_marker=body_marker,
                   level=level, dry_run=dry_run, checkbox_to_trailing=checkbox_to_trailing)


def subst_file(file_path, old, new, section_path=None, dry_run=False,
               ignore_case=False, all_matches=False, regex=False):
    # An empty search string matches at every line boundary, so the "substitution"
    # injects NEW throughout the file and reports success. There is no legitimate
    # use, and the usual cause is a caller whose anchor came back empty from a
    # failed command substitution — which is silent. Refuse before taking the lock
    # or writing a backup, so a bad call touches nothing.
    if old == '':
        label = "gsub" if regex else "subst"
        print(f"Error: {label} refuses an empty search string — it would match every "
              f"line and inject the replacement throughout {file_path}.", file=sys.stderr)
        if not regex:
            print("  If you meant to delete text, pass the text to delete as OLD and "
                  "an empty NEW.", file=sys.stderr)
        return False
    if dry_run:  # read-only preview — no lock, no sidecar created
        return subst_file_bare(file_path, old, new, section_path=section_path,
                               dry_run=True, ignore_case=ignore_case,
                               all_matches=all_matches, regex=regex)
    return _locked([file_path], subst_file_bare, file_path, old, new,
                   section_path=section_path, dry_run=False,
                   ignore_case=ignore_case, all_matches=all_matches, regex=regex)


def body_line_append(file_path, section_path, text, top=False):
    return _locked([file_path], body_line_append_bare, file_path, section_path, text, top=top)


def line_append(file_path, text):
    return _locked([file_path], line_append_bare, file_path, text)


def rename_section(file_path, section_path, new_title=None, state=None, tier=None):
    return _locked([file_path], rename_section_bare, file_path, section_path, new_title,
                   state=state, tier=tier)


def main():
    parser = argparse.ArgumentParser(
        description='Claude Markdown Manager - Section manipulation tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    def _add_select_transform_args(p, *, keep_omit=True, flatten=True):
        """Add the shared SELECT/TRANSFORM flags to an emit verb's parser.

        With any of these set, the verb's section positional is the HEAD (use "."
        for the file root) and the selected node-set is emitted (re-leveled).
        """
        if keep_omit:
            p.add_argument('--keep-sections', default=None,
                help='ALLOWLIST (read/copy): keep only these head-relative paths '
                     '(:,:-separated; each may be a deep :/: path). Ancestors are kept '
                     'as scaffold; everything else under the head is dropped.')
            p.add_argument('--omit-sections', default=None,
                help='DENYLIST (read/copy): drop these head-relative paths '
                     '(:,:-separated); keep everything else under the head.')
        p.add_argument('--children', action='store_true',
            help='Lift the children of the named node (drop its wrapper); pair with --depth.')
        p.add_argument('--depth', type=int, default=1,
            help='Relative TREE depth for --children (1 = immediate children, 2 = grandchildren).')
        if flatten:
            p.add_argument('--flatten', action='store_true',
                help='Flatten each selected subtree to a flat heading sequence.')
        p.add_argument('--strip-markers', action='store_true',
            help='Strip the canonical marker zone ([state]/[v1]/*[ ]/(#)) from every emitted heading.')
        g = p.add_mutually_exclusive_group()
        g.add_argument('--strip-target-body-text', dest='strip_body',
            action='store_const', const='target',
            help="Strip each emitted node's OWN body text (headings + descendants kept).")
        g.add_argument('--strip-child-body-text', dest='strip_body',
            action='store_const', const='child',
            help="Strip DESCENDANTS' body text only (node's own body kept) — header breadcrumbs.")
        g.add_argument('--strip-all-body-text', dest='strip_body',
            action='store_const', const='all',
            help="Strip the node + ALL descendants' body text (heading skeleton only).")
        p.set_defaults(strip_body=None)

    def _add_emit_args(p):
        """Add the shared EMIT/destination flags (copy/extract): where the view lands in
        the output file, and what to do on a marker-transparent title collision there."""
        p.add_argument('--parent', default=None,
            help="Place under this destination section (default: the output's single H1 "
                 "root, else top level). Lets copy/extract land under an existing heading.")
        p.add_argument('--after-sibling', default=None,
            help='Position among the parent\'s children: "^" = first, name = after that '
                 'sibling, default = append last.')
        p.add_argument('--on-conflict', default='merge',
            choices=['merge', 'clobber-body', 'full-subtree', 'append'],
            help="When a same-(marker-stripped)-title section already exists at the "
                 "destination: merge = upsert children, refresh body only if the incoming "
                 "carries prose (default); clobber-body = refresh body+header, keep "
                 "unnamed children; full-subtree = replace body + all children; append = "
                 "place a duplicate (the legacy dump-and-append).")
        p.add_argument('--append', action='store_true',
            help="Sugar for --on-conflict append: always place a fresh copy even if a "
                 "same-title section already exists (the pre-merge behavior).")

    # Read command
    read_parser = subparsers.add_parser('read', help='Print section content to stdout (read-only)')
    read_parser.add_argument('source', help='Source markdown file')
    read_parser.add_argument('section', help='Section path, or "." for the file root (head for SELECT/TRANSFORM)')
    _add_select_transform_args(read_parser)

    # Copy command
    copy_parser = subparsers.add_parser('copy', help='Copy section to file (non-destructive)')
    copy_parser.add_argument('source', help='Source markdown file')
    copy_parser.add_argument('section', help='Section path, or "." for the file root (head for SELECT/TRANSFORM)')
    copy_parser.add_argument('output', help='Output file')
    _add_select_transform_args(copy_parser)
    _add_emit_args(copy_parser)

    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Cut section to file (destructive — removes from source)')
    extract_parser.add_argument('source', help='Source markdown file')
    extract_parser.add_argument('section', help='Section path (head for --children)')
    extract_parser.add_argument('output', help='Output file')
    _add_select_transform_args(extract_parser)
    _add_emit_args(extract_parser)

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a section (and its subtree) from a file')
    delete_parser.add_argument('file', help='Markdown file')
    delete_parser.add_argument('section',
        help='Section path to delete, or "." for the document root. "." EMPTIES THE '
             'FILE - every section is removed. A timestamped backup is written first, '
             'and the restore command is printed with the real path filled in.')

    # Insert command
    insert_parser = subparsers.add_parser('insert',
        help='Insert section(s) from a markdown fragment (its first heading = the new title)')
    insert_parser.add_argument('file', help='Markdown file')
    insert_parser.add_argument('parent',
        help='DESTINATION section — the payload nests UNDER this node. "." = the file root.')
    insert_parser.add_argument('content', nargs='?', default=None,
        help="Markdown fragment BEGINNING with the new section's heading (omit if using "
             "--stdin). That first heading becomes the new section's title; text under it "
             "becomes its body and deeper headings become its subsections. Levels re-level "
             "automatically to nest under the destination, so write them at any depth. "
             "Headings inside code fences are never touched. Several top-level headings "
             "insert as siblings.")
    _ins_pos = insert_parser.add_mutually_exclusive_group()
    _ins_pos.add_argument('--after-sibling', default=None,
        help='Position: "^" = first child, name = after that sibling, default = append last')
    _ins_pos.add_argument('--before-sibling', default=None,
        help='Position: insert BEFORE this sibling ("^" = first child)')
    insert_parser.add_argument('--on-conflict', default='merge',
        choices=['merge', 'clobber-body', 'full-subtree', 'append'],
        help="When a same-(marker-stripped)-title section already exists under the "
             "destination: merge = upsert children, refresh body only if the payload "
             "carries prose (default); clobber-body = refresh body+header, keep unnamed "
             "children; full-subtree = replace body + all children; append = place a "
             "duplicate. Same vocabulary as copy/extract.")
    insert_parser.add_argument('--append', action='store_true',
        help="Sugar for --on-conflict append: place a duplicate even if a same-title "
             "section already exists. NOTE two identical sibling titles are then "
             "unaddressable by path — prefer a distinct title.")
    insert_parser.add_argument('--stdin', action='store_true', help=_STDIN_HELP)

    # Move command
    move_parser = subparsers.add_parser('move', help='Move sections between existing files (target must exist; use copy for new files)')
    move_parser.add_argument('source', help='Source markdown file')
    move_parser.add_argument('section_paths', help='Section path(s) to move (:,:-separated for multiple)')
    move_parser.add_argument('--target', default=None, help='Target markdown file (must exist; default: same as source)')
    move_parser.add_argument('--parent', default=None, help="New parent section path (default, or \".\": the file's single H1, else root)")
    move_parser.add_argument('--after-sibling', default=None,
        help='Sibling marker (default: append to end, "^" = first position, name = after that sibling)')
    move_parser.add_argument('--flatten', action='store_true',
        help='Flatten section hierarchy before moving')
    _add_select_transform_args(move_parser, flatten=False)

    # List command
    list_parser = subparsers.add_parser('list', help='List document outline')
    list_parser.add_argument('file', help='Markdown file')
    list_parser.add_argument('section', nargs='?', default=None,
        help='Optional section path to display (positional alias for --path, e.g. "Parent:/:Child")')
    list_parser.add_argument('--path', help='Section path to display (e.g., "Parent:/:Child")')
    list_parser.add_argument('--max-depth', type=int, help='Maximum depth to display (default: unlimited; use 3+ since # root consumes level 1)')

    # List-paths command
    list_paths_parser = subparsers.add_parser('list-paths', help='Output all valid :/:-separated paths')
    list_paths_parser.add_argument('file', help='Markdown file')
    list_paths_parser.add_argument('--max-depth', type=int, help='Maximum depth to output (default: unlimited; use 3+ since # root consumes level 1)')

    # Map command
    map_parser = subparsers.add_parser('map', help='Display document outline with line counts')
    map_parser.add_argument('file', help='Markdown file')
    map_parser.add_argument('section', nargs='?', default=None,
        help='Optional section path to display (positional alias for --path, e.g. "Parent:/:Child")')
    map_parser.add_argument('--path', help='Section path to display (e.g., "Parent:/:Child")')
    map_parser.add_argument('--max-depth', type=int, help='Maximum depth to display (default: unlimited; use 3+ since # root consumes level 1)')

    # Convert command — bullets OR bold body structure -> child headings (one verb)
    convert_parser = subparsers.add_parser('convert',
        help="Convert in-body structure to child headings: top-level `- ` bullets (default) "
             "or **Bold:** lines (--from bold).")
    convert_parser.add_argument('file', help='Markdown file')
    convert_parser.add_argument('section', nargs='?', default=None,
        help='Section whose bullets to convert (REQUIRED for --from bullets; optional for '
             '--from bold, where omitting it processes the whole file).')
    convert_parser.add_argument('--from', dest='convert_from', default='bullets',
        choices=['bullets', 'bold'],
        help="Source structure: 'bullets' (top-level `- ` items, default) or 'bold' (**Title:** lines).")
    convert_parser.add_argument('--body-marker', default='\n',
        help="bullets: split each entry into heading|body at the FIRST occurrence of this "
             "string (default newline = the bullet line is the heading, continuation lines the body).")
    convert_parser.add_argument('--level', type=int, default=None,
        help='Heading level for the new children (default: section level + 1). bullets only.')
    convert_parser.add_argument('--checkbox-to-trailing', action='store_true',
        help="bullets: relocate a task-list checkbox to the canonical trailing tag "
             "('- [ ] X' -> heading 'X  [ ]'), instead of a leading '[ ] X'.")
    convert_parser.add_argument('--dry-run', action='store_true',
        help='Print the result without writing (no backup).')

    # Reshape command — apply SELECT/TRANSFORM to a section's subtree IN PLACE
    reshape_parser = subparsers.add_parser('reshape',
        help='Apply SELECT/TRANSFORM flags to a section in place (strip bodies/markers, '
             'prune via keep/omit, flatten). reshape FILE X --strip-all-body-text = heading skeleton.')
    reshape_parser.add_argument('file', help='Markdown file')
    reshape_parser.add_argument('section', help='Section path (the HEAD reshaped in place)')
    reshape_parser.add_argument('--keep-sections', default=None,
        help='Keep only these head-relative paths under the section (prune the rest).')
    reshape_parser.add_argument('--omit-sections', default=None,
        help='Drop these head-relative paths from the section.')
    reshape_parser.add_argument('--flatten', action='store_true',
        help='Collapse the section subtree to a flat heading sequence in place.')
    reshape_parser.add_argument('--strip-markers', action='store_true',
        help='Strip the canonical marker zone from every heading in the section.')
    _rg = reshape_parser.add_mutually_exclusive_group()
    _rg.add_argument('--strip-target-body-text', dest='strip_body', action='store_const',
        const='target', help="Strip the section's OWN body text.")
    _rg.add_argument('--strip-child-body-text', dest='strip_body', action='store_const',
        const='child', help="Strip the descendants' body text (header breadcrumbs).")
    _rg.add_argument('--strip-all-body-text', dest='strip_body', action='store_const',
        const='all', help="Strip the section + all descendants' body text (heading skeleton).")
    reshape_parser.set_defaults(strip_body=None)

    # Abridge command — convenience alias for `reshape --strip-all-body-text`
    abridge_parser = subparsers.add_parser('abridge',
        help='Strip a section to a heading skeleton in place (= reshape --strip-all-body-text)')
    abridge_parser.add_argument('file', help='Markdown file')
    abridge_parser.add_argument('section', help='Section path to abridge')

    # Replace command
    replace_parser = subparsers.add_parser('replace',
        help="Replace a section's body from a markdown fragment (heading preserved)")
    replace_parser.add_argument('file', help='Markdown file')
    replace_parser.add_argument('section', help='Section path whose body to replace')
    replace_parser.add_argument('content', nargs='?', default=None,
        help="New body content (omit if using --stdin). Parsed as MARKDOWN: text before "
             "the first heading becomes the body, and unfenced headings become "
             "subsections of the target, re-leveled automatically to fit. Fenced content "
             "is preserved byte-exact. The target's own heading is never changed - use "
             "`rename` for that.")
    replace_parser.add_argument('--stdin', action='store_true', help=_STDIN_HELP)
    replace_parser.add_argument('--remove-subsections', action='store_true', help='Also remove all subsections (default: preserve)')
    replace_parser.add_argument('--full-subtree', action='store_true',
        help="Scope of replacement for EXISTING children - nothing to do with heading "
             "levels, which always re-level. Default merges, keeping children the "
             "payload does not name; --full-subtree replaces body + all children.")

    # Reorder command
    reorder_parser = subparsers.add_parser('reorder', help='Reorder sections (specified first, others follow in original order)')
    reorder_parser.add_argument('file', help='Markdown file')
    reorder_parser.add_argument('sections', help=':,:-separated section titles (partial list OK)')
    reorder_parser.add_argument('--parent', default='', help="Parent section path (default: the file's single H1 root, so a parent-less reorder reorders its ## sections)")

    # Extract-abridge command — copy (full) to OUTPUT + reshape source to a skeleton
    extract_abridge_parser = subparsers.add_parser('extract-abridge',
        help='Copy a section to a file (full), then strip the source to a heading skeleton '
             '(breadcrumbs). Wrapper: copy + reshape --strip-all-body-text.')
    extract_abridge_parser.add_argument('file', help='Source markdown file')
    extract_abridge_parser.add_argument('section', help='Section path to extract')
    extract_abridge_parser.add_argument('output', help='Output file')


    # Subst command — LITERAL fixed-string substitution (positional old/new), under a write lock
    subst_parser = subparsers.add_parser('subst',
        help='Find/replace under a write lock — subst FILE OLD NEW. LITERAL by default '
             '(regex metachars in OLD/NEW match/insert themselves); add --regex for a Python regex (or use `gsub`).')
    subst_parser.add_argument('file', help='Markdown file')
    subst_parser.add_argument('old', help='Text to find (LITERAL by default; a Python regex with --regex). '
             'Must be non-empty — an empty OLD would match every line, so it is refused.')
    subst_parser.add_argument('new', help='Replacement (verbatim by default; supports \\1 backrefs with --regex)')
    subst_parser.add_argument('--regex', action='store_true',
        help='Treat OLD as a Python regex and NEW as a regex replacement (\\1 backrefs). Same as the `gsub` verb.')
    subst_parser.add_argument('--all', dest='all_matches', action='store_true',
        help='Replace EVERY match per line (default: first match per line)')
    subst_parser.add_argument('--ignore-case', action='store_true', help='Case-insensitive match')
    subst_parser.add_argument('--section', default=None,
        help='Limit the substitution to this section subtree (default: whole-file body; frontmatter untouched)')
    subst_parser.add_argument('--dry-run', action='store_true', help='Print the result to stdout without writing (no backup)')

    # Gsub command — Python-REGEX find/replace; the regex alias of subst (= subst --regex).
    gsub_parser = subparsers.add_parser('gsub',
        help='Regex find/replace under a write lock — gsub FILE PATTERN REPL (Python regex; REPL supports \\1 backrefs). Same as `subst --regex`.')
    gsub_parser.add_argument('file', help='Markdown file')
    gsub_parser.add_argument('pattern', help='Python regex to find. Must be non-empty — an empty PATTERN would match every line, so it is refused.')
    gsub_parser.add_argument('replacement', help='Replacement (supports \\1 backreferences)')
    gsub_parser.add_argument('--all', dest='all_matches', action='store_true',
        help='Replace EVERY match per line (default: first match per line; --all = R-gsub-style global)')
    gsub_parser.add_argument('--ignore-case', action='store_true', help='Case-insensitive match')
    gsub_parser.add_argument('--section', default=None,
        help='Limit the substitution to this section subtree (default: whole-file body; frontmatter untouched)')
    gsub_parser.add_argument('--dry-run', action='store_true', help='Print the result to stdout without writing (no backup)')

    # Body-line-append command — append a body line/bullet to a section's body.
    # Named to disambiguate from `line-append` (raw O_APPEND to a flat log file): this
    # appends a BODY line to a parsed section; `line-append` appends a raw line to a flat
    # file. `item-append` is kept as a deprecated alias.
    body_line_append_parser = subparsers.add_parser('body-line-append', aliases=['item-append'],
        help="Append a body LINE/bullet to a section's body (bottom, or --top). For a child HEADING use `insert`; for a flat-file raw line use `line-append`.")
    body_line_append_parser.add_argument('file', help='Markdown file')
    body_line_append_parser.add_argument('section', help='Section path whose body to append to')
    body_line_append_parser.add_argument('content', nargs='?', default=None, help='Body line/bullet to append (omit if using --stdin)')
    body_line_append_parser.add_argument('--top', action='store_true', help='Prepend to the top of the body instead of appending to the bottom')
    body_line_append_parser.add_argument('--stdin', action='store_true', help=_STDIN_HELP)

    # Line-append command — O_APPEND a raw line to a flat append-only file
    line_append_parser = subparsers.add_parser('line-append', help='Append a raw line to a flat append-only file (e.g. ACTIVITY_LOG.md), under the lock')
    line_append_parser.add_argument('file', help='Flat markdown/text file (created if absent)')
    line_append_parser.add_argument('content', nargs='?', default=None, help='Line to append (omit if using --stdin)')
    line_append_parser.add_argument('--stdin', action='store_true', help='Read the line(s) from stdin')

    # Rename command — retitle a section node in place
    rename_parser = subparsers.add_parser('rename', help='Retitle a section in place (body + children preserved)')
    rename_parser.add_argument('file', help='Markdown file')
    rename_parser.add_argument('section', help='Section path to rename')
    rename_parser.add_argument('--to', dest='new_title', default=None,
        help='Replace the WHOLE heading (no :/: or :,: separators).')
    rename_parser.add_argument('--state', default=None,
        help='Edit only the FIRST bracket — the state tag: --state x -> "[x]", '
             '--state implement -> "[implement]", --state " " -> "[ ]". Every other '
             'marker (depth-tier, a provisional "*", a trailing paren) is left '
             'byte-identical. Not validated against any vocabulary.')
    rename_parser.add_argument('--tier', default=None,
        help='Edit only the SECOND bracket — the depth-tier: --tier v2 -> "[v2]". '
             'Requires an existing state bracket to sit after.')

    # Test command
    test_parser = subparsers.add_parser('test', help='Run built-in unit tests')

    # Cleanup-backups command
    cleanup_parser = subparsers.add_parser('cleanup-backups', help='Delete all but most recent backup per file')
    cleanup_parser.add_argument('directory', nargs='?', default='~/.claude/backups/md_tools', help='Directory to clean (default: ~/.claude/backups/md_tools)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    def _split_set(val):
        """Parse a :,:-separated path-set argument into a list (None -> None)."""
        if not val:
            return None
        return [p.strip() for p in val.split(':,:') if p.strip()]

    try:
        if args.command == 'test':
            success = run_tests()
        elif args.command == 'read':
            success = read_section(
                args.source, args.section,
                keep=_split_set(args.keep_sections), omit=_split_set(args.omit_sections),
                children=args.children, depth=args.depth, flatten=args.flatten,
                strip_body=args.strip_body, strip_markers_flag=args.strip_markers)
        elif args.command == 'copy':
            success = copy_section(
                args.source, args.section, args.output,
                keep=_split_set(args.keep_sections), omit=_split_set(args.omit_sections),
                children=args.children, depth=args.depth, flatten=args.flatten,
                strip_body=args.strip_body, strip_markers_flag=args.strip_markers,
                parent=args.parent, after_sibling=args.after_sibling,
                policy=('append' if args.append else args.on_conflict))
        elif args.command == 'extract':
            success = extract_section(
                args.source, args.section, args.output,
                keep=_split_set(args.keep_sections), omit=_split_set(args.omit_sections),
                children=args.children, depth=args.depth, flatten=args.flatten,
                strip_body=args.strip_body,
                strip_markers_flag=args.strip_markers,
                parent=args.parent, after_sibling=args.after_sibling,
                policy=('append' if args.append else args.on_conflict))
        elif args.command == 'delete':
            success = delete_section(args.file, args.section)
        elif args.command == 'insert':
            content = sys.stdin.read() if args.stdin else (args.content or '')
            success = insert_section(args.file, args.parent, content,
                                     after_sibling=args.after_sibling,
                                     before_sibling=args.before_sibling,
                                     policy=('append' if args.append else args.on_conflict))
        elif args.command == 'move':
            success = move_sections(
                args.source, args.target, args.section_paths, args.parent,
                args.after_sibling, args.flatten,
                keep=_split_set(args.keep_sections), omit=_split_set(args.omit_sections),
                children=args.children, depth=args.depth, strip_body=args.strip_body,
                strip_markers_flag=args.strip_markers)
        elif args.command == 'list':
            success = list_sections(args.file, path=(getattr(args, 'section', None) or getattr(args, 'path', None)), max_depth=getattr(args, 'max_depth', None))
        elif args.command == 'list-paths':
            success = list_paths(args.file, max_depth=getattr(args, 'max_depth', None))
        elif args.command == 'map':
            success = map_sections(args.file, path=(getattr(args, 'section', None) or getattr(args, 'path', None)), max_depth=getattr(args, 'max_depth', None))
        elif args.command == 'convert':
            success = convert_to_headings(
                args.file, section_path=args.section, mode=args.convert_from,
                body_marker=args.body_marker, level=args.level,
                dry_run=args.dry_run, checkbox_to_trailing=args.checkbox_to_trailing)
        elif args.command == 'reshape':
            success = reshape_section(
                args.file, args.section,
                keep=_split_set(args.keep_sections), omit=_split_set(args.omit_sections),
                flatten=args.flatten, strip_body=args.strip_body,
                strip_markers_flag=args.strip_markers)
        elif args.command == 'abridge':
            success = abridge_section(args.file, args.section)
        elif args.command == 'replace':
            if args.stdin:
                content = sys.stdin.read()
            else:
                content = args.content or ''
            success = replace_section(args.file, args.section, content,
                                      remove_subsections=args.remove_subsections,
                                      full_subtree=args.full_subtree)
        elif args.command == 'reorder':
            success = reorder_sections(args.file, args.sections, args.parent)
        elif args.command == 'extract-abridge':
            success = extract_abridge_section(args.file, args.section, args.output)
        elif args.command == 'subst':
            success = subst_file(args.file, args.old, args.new, section_path=args.section,
                                 dry_run=args.dry_run, ignore_case=args.ignore_case,
                                 all_matches=args.all_matches, regex=args.regex)
        elif args.command == 'gsub':
            # gsub = subst --regex (PATTERN/REPL are positional; Python regex + \1 backrefs).
            success = subst_file(args.file, args.pattern, args.replacement, section_path=args.section,
                                 dry_run=args.dry_run, ignore_case=args.ignore_case,
                                 all_matches=args.all_matches, regex=True)
        elif args.command in ('body-line-append', 'item-append'):
            if args.stdin:
                content = sys.stdin.read()
            else:
                content = args.content if args.content is not None else ''
            success = body_line_append(args.file, args.section, content, top=args.top)
        elif args.command == 'line-append':
            if args.stdin:
                content = sys.stdin.read().rstrip('\n')
            else:
                content = args.content if args.content is not None else ''
            success = line_append(args.file, content)
        elif args.command == 'rename':
            success = rename_section(args.file, args.section, args.new_title,
                                     state=args.state, tier=args.tier)
        elif args.command == 'cleanup-backups':
            success = cleanup_backups(args.directory)

        return 0 if success else 1

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
