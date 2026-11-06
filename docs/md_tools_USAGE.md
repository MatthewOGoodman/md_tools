# md_tools — usage vignette

`md_tools` performs **whole-section operations on markdown files** by parsing them into a heading tree (code-fence-aware) and operating on nodes by path. It is the required tool for section-level edits to shared `.md` files (STATUS.md, CLAUDE.md, ACTIVITY_LOG.md) — every write verb is `flock`-serialized and commits atomically.

This document is the complete verb + flag reference. For the on-demand skill view see `docs/md_tools_SKILL.md`; for the design rationale see the "md_tools SELECT → TRANSFORM → EMIT redesign" Design Decision in `CLAUDE.md`.

---

## Paths and resolution

- **Hierarchy separator `:/:`** — `"Parent:/:Child:/:Grandchild"`.
- **List separator `:,:`** — multiple paths in one argument: `"Section A:,:Section B"`.
- **Partial paths** — a path is a contiguous, right-anchored slice of a node's ancestor chain ending at the target. You may omit leading levels (the H1 root is always droppable: `"ROOT:/:X"` ≡ `"X"`), and each component may be a case-insensitive prefix/substring of the real heading. Trailing state tags (`  [ ]`, `  [implement]`, `*[ ]`, `(#)`) are ignored for prefix/substring matching, so a stale or omitted tag still resolves. A unique match resolves (the canonical path is echoed to stderr); ambiguity prints candidates and exits non-zero.
- **`"."` = the file's detected H1 root** (used as the HEAD for the SELECT/TRANSFORM flags below).

**Always run `md_tools list FILE` first** to learn the paths before any other operation.

---

## Inspection (non-destructive)

```bash
md_tools list FILE                         # document outline (ALWAYS START HERE)
md_tools list FILE "Section"               # one subtree — positional section (= --path "Section"; map takes it too)
md_tools list FILE --path "Section"        # one subtree (explicit flag form)
md_tools list-paths FILE                   # every :/:-path, one per line
md_tools map FILE                          # outline + per-section line counts (find verbose sections)
md_tools read FILE "Section"               # print a section's content to stdout (like cat for a section)
```

## In-place edits

```bash
# insert — add new section(s) from a markdown fragment (preferred for new TODOs / threads).
# Args are: FILE, DESTINATION, payload. The payload's FIRST heading is the new
# section's title — insert mirrors `replace`, which also parses content as markdown.
md_tools insert FILE "Active Work" "# Title

Body." --after-sibling "Some TODO"

md_tools insert FILE "Active Work" --after-sibling "^" --stdin <<'EOF'
# New TODO  [ ]

multi-line body via heredoc

## A subsection
EOF
#   <destination>       REQUIRED 2nd positional — the payload nests UNDER it.
#                       "." = the file root (its single H1 → payload becomes a ##)
#   --after-sibling "N" = after sibling N (among the destination's children)
#   --before-sibling "N" = before sibling N (mutually exclusive with --after-sibling)
#   --after-sibling "^" = first child     (none) = append last
#
# Payload heading levels RE-LEVEL to nest under the destination, so write them at
# any depth. Headings inside a ``` fence are content, never structure. A payload
# with no leading heading is REFUSED (that is the shape of a call written for the
# superseded "title first, body second" form).
# State tags go straight in the payload heading; to change one on an EXISTING
# heading use `md_tools rename --state`, which edits only that marker.

# replace — replace a section's body in place (heading preserved)
md_tools replace FILE "Section" "New body."
md_tools replace FILE "Section" --remove-subsections "New body, drop children."
md_tools replace FILE "Section" --full-subtree --stdin <<'EOF'   # clobber body + all children
...
EOF
#   default MERGES a body+headers payload: leading prose replaces the body, child
#   headers upsert by title (same→replaced, new→added, unnamed→kept).

# reshape — apply the SELECT/TRANSFORM flags to a section IN PLACE (see the flag layer below)
md_tools reshape FILE "Section" --strip-all-body-text     # strip to a heading skeleton
md_tools reshape FILE "Section" --omit-sections "Sub"     # drop a subsection in place
md_tools reshape FILE "Section" --keep-sections "A:,:B"   # keep only A, B under it
md_tools abridge FILE "Section"                           # alias for `reshape --strip-all-body-text`

# rename — retitle a section in place (body + children preserved; no :/: or :,: in the title)
md_tools rename FILE "Old Heading" --to "New Heading"

# subst — LITERAL fixed-string find/replace (the line-edit tool for shared .md; serialized + atomic).
# OLD/NEW are positional literals (regex metachars | ( ) . * / match/insert themselves; no s/// delimiter, nothing to escape).
md_tools subst FILE "old" "new"                       # whole-file body (first match per line)
md_tools subst FILE "old" "new" --all --section "Section"   # one subtree; --all = every match per line
md_tools subst FILE "a(b)|c" "X"                      # literal: matches the string "a(b)|c"
md_tools subst FILE "old" "new" --ignore-case --dry-run     # case-insensitive; preview, no write
md_tools subst FILE "" "X"                            # REFUSED: an empty OLD would match every line
# An empty NEW is fine — that is how you delete text. Only the SEARCH side must be non-empty.
# Never build OLD from command output: if the capture fails the variable is empty and, without
# this guard, the "substitution" would inject NEW throughout the file and report success.

# gsub — Python-REGEX find/replace (= subst --regex; use subst for literal strings). PATTERN/REPL positional; REPL supports \1.
md_tools gsub FILE '(\w+):(\d+)' '\2-\1' --all       # regex + backreferences (--all = every match)

# body-line-append — append a body line/bullet to a section (bottom, or --top). For a child
# HEADING use `insert`; for a raw line in a flat log use `line-append`. (alias: item-append)
md_tools body-line-append FILE "Some Thread" "- new bullet"

# line-append — append a raw line to a flat append-only file (O_APPEND, no parse)
md_tools line-append ~/.claude/ACTIVITY_LOG.md "2026-06-13  proj  tool  feature  desc"
```

## Cross-document and removal

```bash
md_tools copy    SOURCE "Section" OUTPUT    # copy a section to a file (non-destructive)
md_tools copy    SOURCE "Section" OUTPUT --parent "Header"   # land UNDER an existing destination heading
md_tools move    SOURCE "S1:,:S2" --target TARGET --parent "Header" --after-sibling "^"  # relocate (target must exist)
md_tools extract SOURCE "Section" OUTPUT    # cut a section to a file (removes from source) — wraps copy + delete
md_tools extract-abridge SOURCE "Section" OUTPUT  # copy full to OUTPUT, leave a heading skeleton in source — wraps copy + reshape
md_tools delete  FILE "Section"             # remove a section (and its subtree)
```

`extract` and `extract-abridge` are thin **wrappers** over the primitives above: `extract` = `copy` (the view) + `delete`/`reshape` (remove the emitted content from source); `extract-abridge` = `copy` (full → OUTPUT) + `reshape --strip-all-body-text` (source → heading skeleton). With a SELECT flag, `extract`'s source-side is the inverse op — `--keep K` → `reshape --omit K`, `--omit O` → `reshape --keep O`.

`insert`, `copy`, `extract`, `move`, and `replace` share one **EMIT** back-end — they *place-and-merge* rather than blindly append (see "EMIT — destination placement and merge" below).

---

## SELECT → TRANSFORM flag layer

`read`, `copy`, `extract`, `move`, and the in-place `reshape` share one flag vocabulary that **selects** a node-set and **reshapes** it in a single pass. The moment any of these flags is present, the section positional becomes the **HEAD** (use `"."` for the file's H1 root); without them each verb keeps its native single-section behavior.

**SELECT** — pick the node-set under the head:

| flag | meaning |
|---|---|
| `--keep-sections "A:,:B:/:C"` | ALLOWLIST. Keep only these head-relative paths. The **relative path from the head down is preserved**, and **naming a node keeps its whole subtree** (so naming a parent ⊇ naming any of its children). |
| `--omit-sections "A:,:B"` | DENYLIST — the exact inverse of keep. Drop these, keep the rest. |
| `--children [--depth N]` | Lift the head's depth-N children, dropping the head wrapper. `--depth 1` = immediate children, `2` = grandchildren (counts TREE depth, so a `##`→`####` level-skip makes the `####` depth 1). |

**TRANSFORM** — reshape the selected set:

| flag | meaning |
|---|---|
| `--flatten` | Collapse each selected subtree to a flat heading sequence. |
| `--strip-markers` | Drop the canonical marker zone (`[state]` / `[v1]` / `*[ ]` / `(#)` / `(after: …)`) from every emitted heading. |
| `--strip-target-body-text` | Strip each node's OWN body text (headings + descendants kept). |
| `--strip-child-body-text` | Strip DESCENDANTS' body text only (node body kept) — header breadcrumbs. |
| `--strip-all-body-text` | Strip the node + all descendants' body text (heading skeleton). |

**Fixed pipeline order** (so CLI flag order never matters): `resolve head → SUBSET (keep/omit) → LIFT (children) → TRANSFORM (flatten → strip-body → strip-markers)`. The head is the level reference (itself not emitted); each emitted node re-levels so its heading sits at the output root level. Re-leveling a subtree *upward* past `######` clamps lossily and prints a stderr warning. **A head/keep/omit path that doesn't resolve is skipped with a warning, never an error** — so an allowlist can run safely on a non-canonical file.

**Per-verb effect of the layer:**

- **`read`** prints the view; **`copy`** writes the view to a new file. Both non-destructive.
- **`extract`** / **`move`** remove the selected content from source (`extract` to a file, `move` under a `--parent`); the **head node and everything not selected stay**. `keep` deletes the named subtrees (path-containers + complement retained); `omit` keeps only the omitted (the inverse). A typo'd `--omit` leaves the source unchanged.
- **`reshape`** applies the flags to the section **in place** (rewrites the file). `keep`/`omit` PRUNE in place (prune-preserve).

---

## EMIT — destination placement and merge

`copy`, `extract`, `move`, and `replace` share one **destination** back-end: a node is re-leveled to `parent.level + 1` and placed under the destination parent, matching existing children by **marker-transparent title** (`[state]` / `*[ ]` / `[v1]` / `(#)` are ignored when matching). A **new** title (the common copy-to-fresh-file case) is placed as-is; a **collision** is resolved by policy instead of silently appending a re-leveled duplicate.

**Destination flags** (`copy` / `extract`):

| flag | meaning |
|---|---|
| `--parent "Header"` | Place under this destination section (default: the output's single H1 root, else top level; `"."` also means the H1 root). Lets `copy`/`extract` land under an existing heading the way `move` always could. |
| `--after-sibling "^" \| NAME` | Position among the parent's children: `"^"` = first, NAME = after that sibling, default = append last. |
| `--on-conflict POLICY` | What to do when a same-(marker-stripped)-title section already exists at the destination. Default `merge`. |
| `--append` | Sugar for `--on-conflict append` (place a duplicate — the pre-merge behavior). |

**Conflict policies** (shared vocabulary with `replace`'s `--full-subtree`):

| policy | on a title match |
|---|---|
| `merge` (default) | Upsert the incoming children by title (recursively). The target's body+header refresh **only if** the incoming carries leading prose; a children-only merge leaves the target heading — including a user `(#)` pin / `[v1]` / hand-set state — untouched. |
| `clobber-body` | Refresh the target's body + header from the incoming; keep unnamed children. |
| `full-subtree` | Replace the target's body **and its whole child set** with the incoming. |
| `append` | Place a fresh duplicate even though a same-title section exists. |

`move` always uses `merge` (it has no `--on-conflict` flag); a same-file `move` removes the section's old occurrence first, so it relocates cleanly. `replace`'s default is the same `merge`, and `replace --full-subtree` is the `full-subtree` policy applied to a content fragment.

`insert` carries `--on-conflict` and `--append` too, and keeps its own positioning: it is the only EMIT verb supporting `--before-sibling`, and it reports a missing `--after-sibling`/`--before-sibling` as an error rather than silently leaving the node appended. A merge is announced as `MERGED into existing '<title>'`, not as a fresh insert — it changed a section that already existed. **Why the default is merge and not append:** two sibling sections with the same title are unaddressable by path, so every later `read`/`rename`/`move`/`delete` on that title fails `Ambiguous match` with two identical suggestions, and the file can only be repaired by an out-of-band text edit. `--append` remains available for the rare case where a deliberate duplicate is wanted.

```bash
# Merge a section into an existing same-titled destination (no duplicate):
md_tools copy SRC.md "Thread Alpha" ARC.md                       # -> ARC's "Thread Alpha" gains SRC's children
md_tools copy SRC.md "Done two"     ARC.md --parent "Thread Alpha"  # land under a specific heading
md_tools copy SRC.md "Thread Alpha" ARC.md --append              # opt back into a duplicate
```

### Worked examples

```bash
# The 3 prioritize "blind-export" views (head = the whole file):
md_tools read STATUS.md "." --keep-sections "0. Project Overview:,:1. Prioritization:/:Goal:,:1. Prioritization:/:Focus:,:4. Deliverables and Deadlines:,:5. Blockers" --strip-markers   # goals-only
md_tools read STATUS.md "." --keep-sections "2. Active Threads:,:3. Inactive Threads" --children --strip-markers              # thread-pool (### threads + #### TODOs)
md_tools read STATUS.md "." --keep-sections "2. Active Threads:,:3. Inactive Threads" --children --depth 2 --strip-markers    # todos-only (#### TODOs only)

# keep preserves the relative path from the HEAD; choose the head to control context:
md_tools read STATUS.md "."                --keep-sections "1. Prioritization:/:Goal"   # -> # 1. Prioritization / ## Goal
md_tools read STATUS.md "1. Prioritization" --keep-sections "Goal"                       # -> # Goal  (head is the reference)
md_tools read STATUS.md "1. Prioritization" --keep-sections "Goal:,:Focus" --flatten     # lift/flatten the kept leaves

# Cut Goal out to its own file, leaving Prioritization (with Focus, Thread Order) in source:
md_tools extract STATUS.md "1. Prioritization" goal.md --keep-sections "Goal"

# In-place: strip a verbose CLAUDE.md section to a heading skeleton, then refill with replace:
md_tools reshape CLAUDE.md "Python Setup" --strip-all-body-text
md_tools replace CLAUDE.md "Python Setup" "Condensed summary."
```

---

## Auxiliary

```bash
md_tools reorder FILE "S1:,:S2:,:S3" --parent "Parent"   # move named sections to the top (rest follow in order)
#   Names match marker-transparently + case-insensitively: "Beta thread" resolves
#   "Beta thread  [plan] [v2]". Zero matches => no write + NON-ZERO exit.
md_tools convert FILE "Section"                          # a section's top-level `- ` bullets -> child headings (split heading|body at --body-marker; default '\n' = whole bullet line is the heading)
md_tools convert FILE "Section" --body-marker " :: "     # split each bullet at the first " :: " into heading | body
md_tools convert FILE "Section" --checkbox-to-trailing   # "- [ ] X" -> heading "X  [ ]" (canonical trailing tag)
md_tools convert FILE [SECTION] --from bold              # **Bold:** lines -> child headings (whole file if SECTION omitted)
md_tools convert FILE "Section" --level 4                # heading level for the produced children (default: one below the section)
md_tools cleanup-backups [DIR]                           # keep only the most recent backup per file
md_tools test                                            # built-in self-test
```

## Safety

- **Automatic backups** before every destructive op (`insert`, `replace`, `extract`, `delete`, `reshape`, `move`, `reorder`, `subst`, `gsub`, `body-line-append`, `rename`, `convert`, and `copy`/`extract` when they **overwrite an existing output**) land in `~/.claude/backups/md_tools/`. A `copy`/`extract` to a brand-new output file is not backed up (nothing to lose); `line-append` is pure `O_APPEND` — no backup.
- **Concurrent-write safety** — every write verb holds an exclusive advisory `flock` on the data file's parent directory for the whole read-modify-write and commits via temp-file + `os.replace()`, so two `md_tools` processes editing the same shared file serialize (no silent lost updates) and a crash can't leave a truncated file. POSIX-only; degrades to a no-op (atomic write still applies) where `fcntl` is absent or with `MD_TOOLS_LOCK=0`.
- **YAML frontmatter** is held opaque and byte-verbatim (it never travels with a moved section, and is never addressable by md_tools — edit a frontmatter block with `Edit`).
