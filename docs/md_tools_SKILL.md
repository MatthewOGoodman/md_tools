### Tool: `md_tools`

**ALL whole-section operations on .md files MUST use this tool.** Canonical commands, in order:
`list`, `read`, `insert`, `replace`, `reshape`, `copy`, `move`, `extract`, `delete`.

**Order rationale** (groups of two, increasing impact):
1. **Inspection** (`list`, `read`) — non-destructive reads. Always run `list` first to learn the path.
2. **In-place edits** (`insert`, `replace`, `reshape`) — add or rewrite content within one file. `replace` may be destructive (can clear body, can remove subsections via `--remove-subsections`); `reshape` applies the SELECT/TRANSFORM flags to a section IN PLACE (strip bodies/markers, flatten, prune via keep/omit — `reshape FILE X --strip-all-body-text` = heading skeleton).
3. **Cross-document ops** (`copy`, `move`, `extract`) — move content between files; `copy` is non-destructive, `move`/`extract` mutate the source.
4. **Removal** (`delete`) — removes a subtree wholesale.

Composite/auxiliary commands: `abridge` (= `reshape --strip-all-body-text`), `extract-abridge` (copy + reshape), `reorder`, `map`, `list-paths`, `convert` (bullets OR bold → child headings; `--from bullets`|`bold`, `--body-marker`, `--checkbox-to-trailing`), `cleanup-backups`.

Write-hardening verbs: `subst` (literal find/replace; `--regex` for regex), `gsub` (regex find/replace, = `subst --regex`), `body-line-append` (append a body line/bullet to a section — alias `item-append`), `line-append` (append a raw line to a flat log), `rename` (retitle a section in place).

**Concurrent-write safety:** every write verb holds an exclusive advisory `flock` for the whole read-modify-write and commits atomically (temp + `os.replace`), so two `md_tools` processes editing the same shared file (STATUS.md, CLAUDE.md, ACTIVITY_LOG.md) are serialized — no silent lost updates — and a crash can't leave a truncated file. (Raw `Edit`/`sed -i`/`>` on those files have no such serialization.)

Self-contained script for CLAUDE.md management.

**⚠️ CRITICAL: Context-Aware Editing**

CLAUDE.md and active plan files are already loaded in your context (via system prompt and plan mode respectively). The Edit tool requires a prior Read() call — but Read() on these files is redundant and wastes context tokens.

**Rule:** For whole-section operations on files already in context, use `md_tools` via Bash. It operates externally — no Read() required. Use `Edit` only for targeted in-section text substitutions (e.g., fixing a phrase within prose you mostly want to keep).

**Usage:**
```bash
# 1. list — ALWAYS run first. Understand the hierarchical paths before any other op.
md_tools list CLAUDE.md
md_tools list CLAUDE.md "Section Name"                  # positional section (alias for --path)
md_tools list CLAUDE.md --path "Section Name"            # Show specific subtree (auto-detects root)
md_tools list CLAUDE.md --path "Parent:/:Child"          # Narrower subtree
md_tools list CLAUDE.md --max-depth 5                    # Avoid; see --max-depth discipline below.
md_tools list-paths CLAUDE.md                            # All :/:-separated paths, one per line
md_tools list-paths CLAUDE.md --max-depth 5              # Avoid.

# 2. read — print section content to stdout (non-destructive inspection; like cat for a section)
md_tools read CLAUDE.md "Section Name"
md_tools read CLAUDE.md "Parent:/:Child"

# 3. insert — create new section(s) from a markdown fragment.
#    ARGUMENTS ARE: file, DESTINATION, payload. The payload's FIRST heading
#    becomes the new section's title — insert mirrors `replace`, which also
#    parses its content as markdown rather than writing it as literal text.
#    A payload title that ALREADY EXISTS under the destination MERGES into it
#    (children upserted) rather than creating a second section of that name —
#    the same EMIT rule copy/move/extract follow. Two identical sibling titles
#    would be unaddressable by path, so `--append` is the explicit opt-in.
md_tools insert CLAUDE.md "Active Work" "# Title

Content." --after-sibling "Some TODO"

# Heading levels RE-LEVEL automatically to nest under the destination, so write
# the payload at whatever depth reads naturally:
md_tools insert STATUS.md "2. Active Threads" --after-sibling "^" --stdin <<'EOF'
# New Thread  [implement]

One-line description of the thread.

## First TODO  [ ]

start: ...

## Second TODO  [ ]
EOF
#   -> "### New Thread  [implement]" with two "#### " TODOs nested under it.
#      Headings inside a ``` code fence are content, never structure, so a gated
#      code block passes through byte-exact.

# Positioning options:
#   <destination>             REQUIRED 2nd positional — the payload nests UNDER
#                             this section. "." = the file root (its single H1
#                             when there is one, so the payload becomes a ##).
#   --after-sibling "Name"    Insert after this sibling (among the destination's children)
#   --before-sibling "Name"   Insert BEFORE this sibling (mutually exclusive with --after-sibling)
#   --after-sibling "^"       Insert as first child ("^" also works for --before-sibling)
#   (no positioning flag)     Append as last child
#
# State tags are written straight into the payload heading ("# Title  [x]").
# To change a tag on an EXISTING heading use `md_tools rename --state` (below),
# which edits that one marker and leaves the rest of the heading untouched.
#
# A payload with no leading heading is REFUSED — that is the shape of a call
# written for the superseded "title first, body second" form, and failing loudly
# beats silently creating a section named after the intended destination.

# 4. replace — replace an existing section's body in place. Preserves heading.
md_tools replace CLAUDE.md "Section Name" "New body content."
md_tools replace CLAUDE.md "Section Name" --remove-subsections "New body, drop children."
md_tools replace CLAUDE.md "Section Name" --stdin <<'EOF'
Multi-line replacement
content here.
EOF

# 5. copy — write section to a file (non-destructive; source unchanged). Places under
#    --parent (default: the output's H1 root) and MERGES on marker-transparent title-match
#    instead of appending a duplicate; --on-conflict {merge|clobber-body|full-subtree|append}
#    (default merge), --append = legacy duplicate. A fresh output file is placed as-is.
md_tools copy CLAUDE.md "Parent:/:Child" output.md
md_tools copy SRC.md "Thread Alpha" ARC.md --parent "Thread Alpha"   # land under an existing heading

# 6. move — relocate sections between or within files (target must exist; :,:-separated for multiple)
#    Always merges on title-match (the shared EMIT back-end); a same-file move relocates cleanly.
md_tools move source.md "Section1:,:Section2" --target=target.md --parent="Header" --after-sibling="^"

# 7. extract — cut section to a file (DESTRUCTIVE; = copy + delete from source). Inherits
#    copy's place-and-merge EMIT (--parent / --after-sibling / --on-conflict / --append).
md_tools extract CLAUDE.md "Parent:/:Child" output.md

# 8. delete — remove a section (and its subtree) from the file
md_tools delete CLAUDE.md "Parent:/:Child"
md_tools delete CLAUDE.md "."          # EMPTIES the file — removes the document
                                       # root and every section under it. Allowed,
                                       # but it warns and prints a restore command
                                       # naming the backup it just wrote.

# 9. reshape — apply SELECT/TRANSFORM flags to a section IN PLACE (rewrites the file)
md_tools reshape CLAUDE.md "Python Setup" --strip-all-body-text   # heading skeleton (breadcrumb outline)
md_tools reshape STATUS.md "1. Prioritization" --omit-sections "Thread Order"   # drop a subsection in place
md_tools reshape STATUS.md "1. Prioritization" --keep-sections "Goal:,:Focus"   # keep only these under it
md_tools abridge CLAUDE.md "Python Setup"   # convenience alias for `reshape --strip-all-body-text`

# Extract content to a file but leave a heading-skeleton breadcrumb in source:
md_tools extract-abridge CLAUDE.md "Python Setup" PYTHON_SETUP.md   # = copy (full) + reshape --strip-all-body-text

# Auxiliary: reorder sections at same level
md_tools reorder CLAUDE.md "Section1:,:Section2:,:Section3" --parent="Parent:/:Path"
# Sibling names match MARKER-TRANSPARENTLY (and case-insensitively) — name a section
# by its title without retyping its " [state] [v1] (#)" zone:
md_tools reorder STATUS.md "Beta thread:,:Alpha thread" --parent="2. Active Threads"
# Named sections move to the top in the order given; unnamed siblings keep their
# relative order after them. A name matching nothing warns and is skipped; if NOTHING
# matches, no file is written and the command EXITS NON-ZERO — so a script can detect
# it instead of reading "Reordered 0 section(s)" as success. Two siblings that differ
# ONLY by marker are AMBIGUOUS: the command refuses and lists them — pass the exact
# full heading to disambiguate. There is no opt-out flag; exact-title match is tried
# first, so a full heading always addresses one node.


# Auxiliary: map - quantitative analysis (line counts per section, identifies verbose sections)
md_tools map CLAUDE.md                                   # Hierarchical structure + line counts
md_tools map CLAUDE.md --path "Section Name"
md_tools map CLAUDE.md --max-depth 5                     # Avoid.

# convert — turn in-body structure into child headings (one verb, two modes; fence-aware)
md_tools convert STATUS.md "Some Section"               # top-level `- ` bullets -> child headings (default body-marker '\n' = bullet line is the heading)
md_tools convert FILE "Section" --body-marker " :: "     # split each bullet at the first " :: " into heading | body
md_tools convert FILE "Section" --checkbox-to-trailing   # "- [ ] X" -> heading "X  [ ]" (canonical trailing tag)
md_tools convert FILE [SECTION] --from bold              # **Bold:** lines -> child headings (whole file if SECTION omitted)

# subst — LITERAL fixed-string find/replace, serialized + atomic (THE tool for inline edits to shared .md).
# OLD/NEW are positional literals: regex metachars (| ( ) . * [ ] /) in them match/insert themselves —
# no s/// delimiter, nothing to escape — so a string full of punctuation replaces predictably.
md_tools subst STATUS.md "old phrase" "new phrase"        # whole-file body (first match per line); frontmatter untouched
md_tools subst STATUS.md "old" "new" --all --section "2. Active Threads"   # scope to one subtree; --all = every match per line
md_tools subst STATUS.md "a(b)|c" "X"                     # literal: matches the string "a(b)|c"
md_tools subst STATUS.md "" "X"                           # REFUSED: an empty OLD matches every line (an empty NEW is fine — that deletes)
md_tools subst STATUS.md "old" "new" --dry-run            # preview to stdout, no write

# gsub — Python-REGEX find/replace (= subst --regex; use subst for literal strings). PATTERN/REPL positional; REPL supports \1.
md_tools gsub STATUS.md '(\w+)=(\d)' '\2:\1' --all --section "2. Active Threads"   # regex + backreferences

# body-line-append — add a body line/bullet to a section (bottom, or --top); for a child
# HEADING use `insert`, not this. (alias: item-append)
md_tools body-line-append STATUS.md "Some Thread" "- new bullet"

# line-append — append a raw line to a flat append-only file (O_APPEND, under the lock)
md_tools line-append ~/.claude/ACTIVITY_LOG.md "2026-06-09  proj  tool  feature  desc"

# rename — retitle a section in place, OR edit one marker on its heading
# (body + children preserved; no :/: or :,: in the title)
md_tools rename CLAUDE.md "Old Heading" --to "New Heading"   # replace the WHOLE heading
md_tools rename STATUS.md "Some Thread" --state x            # edit ONLY the state bracket
md_tools rename STATUS.md "Some Thread" --tier v2            # edit ONLY the 2nd bracket
#   --state / --tier address a bracket by POSITION (state first, depth-tier second)
#   and leave every other byte of the heading alone:
#       "name  *[implement] [v1] (#)"  --state x  ->  "name  *[x] [v1] (#)"
#   That is the point — rebuilding a full title by hand to flip one tag is how a
#   depth-tier, a provisional "*" or a priority paren gets silently dropped.
#   Values are NOT checked against any controlled vocabulary; placement only.
#   --tier needs an existing state bracket to sit after, else it refuses.
```

**Workflow: reshape → replace.** `reshape FILE X --strip-all-body-text` strips a section to a heading skeleton in place; then use `replace` to fill in abbreviated text section-by-section. The empty headings are still in the tree — `replace` populates each one's body without changing structure.

**SELECT → TRANSFORM (read / copy / extract / move / reshape).** These verbs share a flag set that selects + reshapes a node-set in one pass. With ANY of these flags present, the section positional is the **HEAD** (use `"."` for the file's H1 root); without them every verb keeps its native single-section behavior.

- **SELECT** — `--keep-sections "A:,:B:/:C"` (ALLOWLIST: keep only these head-relative paths; the **relative path from the head down is preserved**, and naming a node keeps its **whole subtree** — naming a parent ⊇ naming any child) · `--omit-sections "A:,:B"` (DENYLIST; the exact inverse of keep) · `--children [--depth N]` (lift the head's depth-N children, dropping its wrapper — `--depth 1` = immediate children, `2` = grandchildren).
- **TRANSFORM** — `--flatten` (collapse each selected subtree to a flat heading sequence) · `--strip-markers` (drop the canonical marker zone `[state]`/`[v1]`/`*[ ]`/`(#)` from every emitted heading) · `--strip-target-body-text` / `--strip-child-body-text` / `--strip-all-body-text` (remove a node's own / its descendants' / its whole subtree's body text, headings preserved).

The fixed pipeline order is `resolve head → SUBSET (keep/omit) → LIFT (children) → TRANSFORM`, so flag order on the command line never matters. The head is the level reference (it is itself not emitted); each emitted node re-levels so its heading sits at the output root level. A head/keep/omit path that doesn't resolve is skipped with a stderr warning (never an error) — so an allowlist runs safely on a non-canonical file. Per-verb effect:

- **read** → prints the view; **copy** → writes the view to the output file, place-and-merging it under `--parent` (both non-destructive to source).
- **extract** / **move** → the SELECTED content is removed from / relocated out of the source; the **head node and everything not selected stay** (`keep` deletes the named subtrees, `omit` keeps only the omitted).
- **reshape** → applies the flags to the section **IN PLACE** (the file is rewritten).

**EMIT (where it lands) — insert / copy / extract / move / replace.** These five share one destination back-end: a node re-levels to `parent.level+1` and is matched against the destination parent's children by **marker-transparent title** (`[state]`/`*[ ]`/`[v1]`/`(#)` ignored). A new title is placed as-is; a collision merges per `--on-conflict {merge|clobber-body|full-subtree|append}` (default `merge`: upsert children, refresh the target body+header only when the incoming carries leading prose, else leave the target heading/markers untouched). `--append` keeps the legacy duplicate. `move` is always `merge`; `replace --full-subtree` is the `full-subtree` policy on a content fragment. `insert` reports a merge as `MERGED into existing '<title>'` rather than as a fresh insert, because it changed a section that was already there.

```bash
# a "threads-only" export of a STATUS.md
md_tools read STATUS.md "." --keep-sections "2. Active Threads:,:3. Inactive Threads" --children --strip-markers
# cut Goal out to its own file, leaving Prioritization (and Focus, Thread Order) in source
md_tools extract STATUS.md "1. Prioritization" goal.md --keep-sections "Goal"
```

**Path separators:**
- `:/:`  separates hierarchy levels: `"Parent:/:Child:/:Grandchild"`
- `:,:` separates multiple paths in move/reorder: `"Section A:,:Section B"`

**Path resolution (any section-path argument).** A locator is a **partial path**: a *contiguous, right-anchored* slice of a node's ancestor chain ending at the target. You may **omit leading levels** (the H1 root is always droppable — `"ROOT:/:X"` ≡ `"X"`), and each component may be a **prefix** (or, failing that, a substring) of the real heading. Resolution loosens in tiers — exact (case-insensitive) → prefix → substring — and:
- **State tags are transparent.** A trailing ` [state]` (and ` [v1]` / the canonical provisional `*[ ]` prefix / an incidental `[v1*]`, or a leading `[ ]` from a converted task-bullet) is stripped on both sides for prefix/substring matching — so `"cluster-env-setup"` resolves `"cluster-env-setup  [implement]"`, and even a **stale** tag in your locator (`"…  [queued]"`) still matches. A literal full title (exact tier) still addresses a node *by* its tag.
- **Unique wins; ambiguity refuses.** Exactly one match resolves (an info line prints the canonical path). Two+ matches print `Error: Ambiguous match … Did you mean:` with the candidate full paths and exit non-zero — **add an ancestor** (`"2. Active Threads:/:cluster-env-setup"`) or paste the **exact full path** (it takes the fast path) to disambiguate.
- **Gaps are rejected.** Skipping a *non-root* middle level (`"Grandparent:/:grandchild"`) is a no-match (with suggestions), by design — name the parent or the leaf, not a gapped chain.
- **Case-insensitive** throughout; **single-root auto-detection** means a bare `"Section"` resolves under the document's H1.

**CRITICAL:** For inserting NEW sections into .md files, ALWAYS use `md_tools insert`, NOT the Edit, Write, or NotebookEdit tools. `md_tools insert` correctly handles section hierarchy and creates backups.

**NEVER** pipe `md_tools list` or other md_tools output through `head`, `tail`, or other truncating commands.

**`--max-depth` discipline:**
- **Default:** Omit `--max-depth` entirely — unlimited depth shows full hierarchy
- **Narrow scope with `--path`**, not `--max-depth` — target a subtree instead of truncating depth
- **NEVER go below 3** when `--max-depth` is needed:
  - `--max-depth 1`: Useless — `#` headings just duplicate the filename
  - `--max-depth 2`: Hides `###`, `####`, etc, which contains informative and contextual details for the `##` headers
- **Headers use negligible context** compared to section content — don't truncate depth to save tokens

**When to use md_tools vs Edit/Write:**

| Situation | Use | Why |
|-----------|-----|-----|
| Insert new section into file already in context | `md_tools insert` | No Read() needed — avoids redundant context load |
| Move/extract/delete/reorder existing sections | `md_tools` (various) | Hierarchical tree operations |
| Find/replace LITERAL text WITHIN a section of a shared .md | `md_tools subst --section` (`gsub` / `subst --regex` for regex) | Serialized + atomic; no Read() needed |
| Reword prose in a non-shared file you've Read | `Edit` tool | Fine when no concurrent writer |
| File NOT yet in context | `Read` then `Edit` | Normal workflow for unfamiliar files |

**Anti-patterns:**
- ❌ Calling Read() on CLAUDE.md before Edit — it's already in your context
- ❌ Calling Read() on the active plan file before Edit — it's already in your context
- ❌ Using Edit to add a new section when md_tools insert can place it precisely
- ❌ Using `md_tools insert` with temporary files and move (the old workaround) — insert now has full positioning

**Section Title Best Practices:**
- **Avoid ampersands (&)** in section titles - they cause issues with md_tools path parsing
- Use "and" instead: "Tools and Protocols" not "Tools & Protocols"
- Avoid parentheses in titles when possible

**On PATH:** `md_tools` is the console script `pip install` writes into the environment's `bin/`, so it resolves by name. **ALWAYS use the short command** (`md_tools`) — NEVER a full path to the script.

**Automatic backups:** Destructive operations (`insert`, `replace`, `extract`, `delete`, `reshape`, `move`, `reorder`, `subst`, `gsub`, `body-line-append`, `rename`, `convert`, and `copy`/`extract` when they **overwrite an existing output**) auto-create timestamped backups in `~/.claude/backups/md_tools/`. (A `copy`/`extract` to a brand-new output file is not backed up; `line-append` is pure `O_APPEND` — no backup.) Clean up with `md_tools cleanup-backups` (keeps only the most recent backup per file).

#### Gotcha: `subst`/`gsub` are LINE-ORIENTED, and regex is the quoting escape hatch

**A multi-line OLD/PATTERN can never match.** Both verbs substitute line by line, so a search string spanning a newline matches nothing — and the call reports `subst: no matches in FILE; file left unchanged`, which reads like a wrong search string rather than a structural impossibility. Split into one call per line, or use `md_tools replace` when the target is a whole section body.

**When the text carries quotes, backticks, or `$`, reach for `gsub` rather than fighting the shell.** A literal `subst` argument containing an apostrophe closes the surrounding single-quoted shell string and fragments the argument — the symptom is `md_tools: error: unrecognized arguments: <fragment>`, with the tail of your text parsed as flags. Anchor a regex on a unique prefix and let `.*` absorb everything problematic:

```bash
md_tools gsub FILE '^- \*\*Unique prefix.*$' 'replacement with no apostrophes'
```

Single-quote the whole argument (backticks and `$` are then inert) and keep apostrophes out of the replacement. `--dry-run` confirms the match count before writing.
