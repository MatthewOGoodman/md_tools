# md_tools

Whole-section operations on Markdown files, addressed by heading path.

`md_tools` parses a Markdown document into a tree of headings (code fences are
content, never structure), lets you address any section by a partial path such
as `"Parent:/:Child"`, and rewrites the file with that section listed, read,
inserted, replaced, moved, copied, extracted, reshaped, renamed or deleted.
Every write holds an exclusive advisory lock for the whole read-modify-write
and commits atomically, so several processes editing the same file serialize
instead of clobbering each other, and a crash can never leave a truncated
file. Destructive verbs write a timestamped backup first.

It was built to let an AI coding agent edit large, shared Markdown state files
(project status, configuration, logs) by section name rather than by line
number, where a concurrent editor can shift every line between a read and a
write. It is equally useful from a shell.

## Install

```bash
pip install -e .            # into the environment whose python should run it
md_tools --help
```

Dependencies: [`markdown-parser-py`](https://github.com/VarunGumma/markdown-parser-py)
and `regex`. Python 3.10 or newer. pip writes the environment's interpreter path
into the `md_tools` console script, so the source file keeps a portable shebang.

## The verbs

| Verb | What it does |
|---|---|
| `list`, `list-paths`, `map` | Show the heading tree, every path, or line counts per section. Run `list` first. |
| `read` | Print a section (or a selected, transformed view of a subtree) to stdout. |
| `insert` | Create a section from a Markdown fragment under a destination, positioned by sibling. |
| `replace` | Replace a section's body in place, keeping its heading and (by default) its children. |
| `copy`, `move`, `extract` | Carry sections to another file or place, merging on title match. |
| `reshape`, `abridge`, `extract-abridge` | Prune, flatten, de-mark or strip a subtree in place or on the way out. |
| `delete` | Remove a section and its subtree. |
| `reorder` | Reorder siblings under a parent. |
| `rename` | Retitle a section, or edit one trailing marker (`--state`, `--tier`) and nothing else. |
| `subst`, `gsub` | Literal or regex find and replace, whole file or one section, line by line. |
| `body-line-append`, `line-append` | Append a body line to a section, or a raw line to a flat log. |
| `convert` | Turn top-level bullets or bold leads into child headings. |
| `cleanup-backups` | Keep only the newest backup per file. |

```bash
md_tools list STATUS.md
md_tools read STATUS.md "2. Active Threads:/:md_tools"
md_tools insert STATUS.md "7. Inbox" --after-sibling "^" --stdin <<'EOF2'
#### Try the new verb  [ ]
One-phrase description.
EOF2
md_tools rename STATUS.md "Try the new verb" --state x
md_tools subst STATUS.md "old phrase" "new phrase" --section "7. Inbox"
```

### Paths

- `:/:` separates levels: `"Parent:/:Child:/:Grandchild"`. `:,:` separates several paths.
- A locator is a right-anchored partial path: leading levels may be omitted, and each
  component may be a prefix or substring of the real heading, case-insensitively.
- Trailing markers on a heading (`[state]`, `[v1]`, `*[ ]`, `(#)`) are transparent to
  matching, so `"md_tools"` resolves `"md_tools  [implement] (#)"`.
- One match resolves; two or more refuse and list the candidates; none prints suggestions.

### Selecting and transforming a view

`read`, `copy`, `extract`, `move` and `reshape` share a flag set that selects a node set
under a head and transforms it in one pass: `--keep-sections`, `--omit-sections`,
`--children [--depth N]`, `--flatten`, `--strip-markers`, and the `--strip-*-body-text`
family. Pipeline order is fixed (resolve head, subset, lift, transform), so flag order
never matters.

## Documentation

- `docs/md_tools_USAGE.md` — the complete verb and flag vignette.
- `docs/md_tools_SKILL.md` — the condensed reference written for an AI agent's
  always-loaded context, including the editing discipline the tool is meant to enforce.
- `md_tools <verb> --help` — per-verb usage.

## Tests

```bash
pip install -e '.[dev]'
pytest                                   # the suite
md_tools test                            # the built-in self-test
bash test_scripts/run_md_tools_tests.sh  # both, under the interpreter that serves the command
```

## License

MIT.
