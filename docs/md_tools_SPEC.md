# md_tools — code architecture

How the code is organized and executes. Unless noted, every function below is a module-level helper in `md_tools.py`. Written for a reader who has the source open; the user-facing verb reference is `md_tools_USAGE.md`.

**Control flow — the `_locked` / `*_bare` split.** Every write verb is implemented as a `*_bare(...)` worker (`insert_section_bare`, `move_sections_bare`, `replace_section_bare`, `subst_file_bare`, `rename_section_bare`, …) that assumes its locks are already held. The CLI never calls a worker directly — it goes through `_locked(write_targets, worker, ...)`, which takes an exclusive advisory `flock` on each target's parent directory, runs the worker, then commits through `commit()` → `atomic_write()` (temp file in the same dir + `os.replace`). This is what serializes concurrent `md_tools` writers instead of letting them clobber each other, and why a crash cannot leave a truncated file. Read-only verbs (`read`, `list`, `list-paths`, `map`) skip the lock path entirely.

**Section-path verbs** share one entry point: `parse_and_resolve()`, which parses the file and resolves a partial locator to a single node (see "Path Resolution Helpers").

## Path Resolution Helpers

| Function | Purpose | Inputs | Output |
|----------|---------|--------|--------|
| `detect_single_root(tree)` | Check if tree has exactly one root heading | `tree: MarkdownTree` | `str` (root title) or `None` |
| `prepend_root_prefix(path, root_prefix)` | Prepend root title to user path if missing | `path: str, root_prefix: str\|None` | `str` (full path) |
| `_collect_node_paths(node, prefix=())` | Yield every non-root node with its title-tuple — the locator registry | `node: MarkdownNode, prefix: tuple` | generator of `(node, tuple)` |
| `_strip_state_tags(title)` | Strip the trailing marker zone (`[state]` / `[v1]` / `*[ ]` / `(#)`) off a title | `title: str` | `str` (bare title) |
| `_locator_matches(locator_parts, full_parts, mode)` | Contiguous right-anchored partial-locator match at one tier | `locator_parts: tuple, full_parts: tuple, mode: str` | `bool` |
| `find_node_with_suggestions(tree, path, file_path)` | Resolve a partial locator to a unique node (see resolution model below) | `tree: MarkdownTree, path: str, file_path: str\|None` | `(node, False)` on success, `(None, True)` on failure |
| `build_node_path(node)` | Walk parent chain to reconstruct :/: path | `node: MarkdownNode` | `str` (:/:-separated path) |
| `collect_all_paths(node, prefix, max_depth, current_depth)` | Recursively collect all valid paths | `node: MarkdownNode, ...` | `list[str]` |
| `suggest_matches(query, all_paths, max_suggestions)` | Rank suggestions for a failed path | `query: str, all_paths: list, max_suggestions: int` | `list[str]` (up to N) |
| `format_path_error(query, all_paths, file_path)` | Print structured error + suggestions to stderr | `query: str, all_paths: list, file_path: str\|None` | `None` (side effect: stderr) |
| `parse_and_resolve(file_path, section_path)` | Parse + resolve in one call — the shared entry point for every section-path verb | `file_path: str, section_path: str` | `(tree, node, resolved_path)`, or `(None, None, None)` on failure |
| `resolve_output_path(source_file, output_file)` | Default the output path to the source file's directory; create dirs | `source_file: str, output_file: str` | `str` (resolved path) |

**Resolution model.** A locator is a **partial path** — a contiguous, right-anchored slice of a node's ancestor chain. `find_node_with_suggestions` tries an exact rooted path first (fast path), then falls through registry tiers — exact (case-insensitive) → prefix → substring — each right-anchored and normalized through `_strip_state_tags`, so even a stale `[state]` tag in the locator still matches. A redundant leading single-H1 root component is dropped. Exactly one match resolves; two or more refuse with the candidate paths; zero falls through to `format_path_error`. There is no distinct "leaf" tier — a leaf query is just a one-component locator.

## Tree Operation Helpers

| Function | Purpose | Inputs | Output |
|----------|---------|--------|--------|
| `print_tree_recursive(node, indent, last, current_depth, max_depth)` | Print tree with indentation and depth limit | `node: MarkdownNode, ...` | `None` (side effect: stdout) |
| `calculate_position(parent, sibling, before=False)` | Compute the insertion index for `--after-sibling` / `--before-sibling` | `parent: MarkdownNode, sibling: str, before: bool` | `int` (index) or `None` |
| `flatten_subtree(node)` | Flatten hierarchy into temp tree at root level | `node: MarkdownNode` | `MarkdownTree` |
| `_replace_node_body(node, content, remove_subsections=False)` | In-memory body set; optionally drop the node's subsections | `node: MarkdownNode, content: str, remove_subsections: bool` | `None` (mutates node) |

## SELECT → TRANSFORM → EMIT Helpers

The function-space redesign — a uniform `list[MarkdownNode]` SELECT/TRANSFORM pipeline shared by `read`/`copy`/`extract`/`move` (+ `reshape` for the in-place application), and a shared EMIT back-end for placing the result into a destination tree.

**SELECT → TRANSFORM**

| Function | Purpose | Output |
|----------|---------|--------|
| `collect_children(node, depth=1)` | Descendants at relative TREE depth N (level-skip safe; `depth<=0` → `[node]`) | `list[MarkdownNode]` (refs) |
| `_resolve_rel_path(head, parts)` | Per-component descent under head, `_strip_state_tags`-normalized + case-insensitive | `MarkdownNode` or `None` |
| `_resolve_keep_omit_paths(head, rel_paths, kind)` | Resolve a head-relative path list to nodes; unresolvable paths warn, never error | `list[MarkdownNode]` |
| `select_keep(head, keep_rel_paths)` | ALLOWLIST: prune head's subtree to the keep-closure (relative path preserved) | head's surviving children (list) |
| `select_omit(head, omit_rel_paths)` | DENYLIST: delete each resolved path from head's subtree (inverse of keep) | head's surviving children (list) |
| `_prune_to_keep_closure(head, keep_nodes)` | The keep-closure prune (each kept subtree + its ancestor chain to head) | `None` (in place) |
| `strip_markers(node)` | Recursively de-mark every title via `_strip_state_tags` | `None` (in place) |
| `strip_bodies(node, scope)` | Strip body text — scope `target` / `child` / `all` (heading skeleton) | `None` (in place) |
| `_flatten_in_place(node)` | Collapse node's subtree to flat direct children (`reshape --flatten`) | `None` (in place) |
| `_resolve_head(tree, head_path)` | Resolve the SELECT head (`"."` → detected H1, not a synthetic ROOT) | `MarkdownNode` or `None` |
| `_select_active(keep, omit, children, flatten, strip_body, strip_markers_flag)` | True if any SELECT/TRANSFORM flag is set — else each verb keeps its native single-section behavior | `bool` |
| `build_view(tree, head_path, ...)` | The fixed-order SELECT → TRANSFORM pipeline driver | `list[MarkdownNode]` or `None` |

**EMIT** — where a view lands. A node re-levels to `parent.level+1` and is matched against the destination parent's children by marker-transparent title.

| Function | Purpose | Output |
|----------|---------|--------|
| `_title_key(title)` | Marker-transparent lowercased identity key used for upsert matching | `str` |
| `_merge_node_into(target, incoming, *, clobber_body)` | Merge an incoming node into an existing target node per the conflict policy | `None` (mutates target) |
| `_clones_clamped(node, delta, max_level=6)` | True if re-leveling would pin any descendant at `max_level` | `bool` |
| `_emit_view_nodes(nodes, parent_level=0, max_level=6)` | Clone + re-level each node to the output root level; reports clamping | `(clones, clamped_any)` |
| `_warn_if_clamped(clamped, where)` | Warn to stderr when heading levels had to be clamped | `None` (side effect: stderr) |
| `place_view(output_tree, nodes, *, parent, after_sibling, policy)` | The EMIT back-end — place nodes into the destination tree under the merge policy | `bool` (success) |
| `_view_to_tree(nodes, output_tree=None, where="")` | Re-level a view node-list to root and graft it onto a tree | `MarkdownTree` |
| `_read_output_tree(output_file)` | Parse an existing output file, or return a fresh empty tree | `MarkdownTree` |

**Verb wrappers**

| Function | Purpose | Output |
|----------|---------|--------|
| `reshape_section_bare(file, head, ...)` | Apply SELECT/TRANSFORM to a section IN PLACE (no-op skips the write; `--keep`-resolves-nothing guard) | `bool` |
| `copy_section_bare(...)` | Copy sections to an output file; source unmodified | `bool` |
| `abridge_section` / `extract_section` / `extract_abridge_section` | Thin wrappers — abridge = `reshape --strip-all-body-text`; extract = copy + delete/reshape (keep→`reshape --omit`, omit→`reshape --keep`, children→delete-each); extract-abridge = copy + `reshape --strip-all-body-text` | `bool` |

## Write-Safety Helpers

The concurrency + atomicity layer behind every write verb (see the `_locked` / `*_bare` split above). This is what lets two `md_tools` processes edit the same shared file — STATUS.md, CLAUDE.md, ACTIVITY_LOG.md — without silent lost updates.

| Function | Purpose | Output |
|----------|---------|--------|
| `_lock_dir_for(path)` | Realpath parent dir, used as the flock coordination token | `str` (directory path) |
| `_dir_lock(directory, timeout, poll=0.05)` | Contextmanager: exclusive advisory flock on a directory fd | contextmanager |
| `file_lock(path, timeout)` | Contextmanager: exclusive lock for a single file | contextmanager |
| `multi_file_lock(*paths, timeout)` | Contextmanager: lock distinct parent dirs in a deadlock-free order | contextmanager |
| `_locked(write_targets, worker, *args, **kwargs)` | Run a `*_bare` worker while holding locks on its write targets | worker's return value |
| `atomic_write(path, text)` | Write via temp file in the same dir + `os.replace` | `None` (writes file) |
| `commit(path, text)` | The shared write back-end: backup → newline-normalize → `atomic_write` | `None` (writes file) |
| `normalize_blank_runs(text)` | Collapse blank-line runs outside code fences | `str` (normalized text) |
| `_frontmatter_split(text)` | Split leading YAML frontmatter off as a byte-verbatim prefix | `(raw_prefix, body)` |

`_frontmatter_split` is why whole-section ops are safe on `SKILL.md` files: the frontmatter is held off-tree and reattached byte-verbatim, which also means `md_tools` cannot address anything inside it.

## Text and Fence Helpers

Body-text processing that operates below the section tree. All of it is fence-aware — a markdown heading or bullet inside a fenced code block is never treated as structure.

| Function | Purpose | Output |
|----------|---------|--------|
| `_fence_line_flags(lines)` | Per-line flags marking which lines sit inside code fences | `list[bool]` |
| `_convert_bullets_in_node(node, body_marker, level, checkbox_to_trailing)` | Convert a node's top-level bullets into child headings (`convert`) | `int` (count converted) |
| `_split_at_first_unfenced_header(text)` | Split text at the first unfenced markdown header | `(before, after)` |
| `_dedent_headers(text)` | Shift header levels so the shallowest becomes level 1 | `str` (re-leveled text) |
| `_regex_sub_text(text, rx, replacement, count)` | Line-by-line regex substitution engine (`gsub`, `subst --regex`) | `(new_text, count)` |
| `_subst_text(text, rx, new, count)` | Line-by-line literal substitution engine (`subst`) | `(new_text, count)` |

## Backup Helpers

`md_tools.py` defines none of these — it imports them from `md_tools_backup.py` (`from md_tools_backup import create_backup, cleanup_backups`), the package's second module, which also holds the `find_root_dir` walk that names a backup after its project. It is a library, not a surface anyone invokes directly, so the function-level detail lives with the code rather than here.

What matters at this level: destructive verbs auto-create a timestamped backup before writing, and backups land in `~/.claude/backups/<tool_name>/` (see "Backup Locations"). The only user-facing entry point is the `cleanup-backups` verb, which keeps the most recent backup per file — `md_tools cleanup-backups --help`. The tool's own `--help` and file-header docstring document the backup behavior.

## Observations

**The parse-and-resolve chain is already factored.** `parse_and_resolve(file_path, section_path)` combines parse file → `detect_single_root` → `prepend_root_prefix` → `find_node_with_suggestions` → `build_node_path`, returning `(tree, node, resolved_path)`. Every CLI verb taking a section path goes through it, so those resolution helpers are never wired together by hand.

**`prepend_root_prefix` is vestigial.** Now that `find_node_with_suggestions` resolves partial paths and drops a redundant leading H1 root itself, prepending the root before resolving is a no-op the resolver neutralizes anyway. It survives in `parse_and_resolve`, `insert_section_bare`, and `move_sections_bare`; removing it is a pending cleanup.

**`collect_all_paths`, `suggest_matches`, `format_path_error`, `_collect_node_paths`, and `_locator_matches`** are called only from inside `find_node_with_suggestions` — sub-helpers of the resolver, not independent surfaces.

**`resolve_output_path(source_file, output_file)`** resolves the output dir → defaults to the source file's dir → creates dirs. Used by the copy/extract family.

**Backup helpers live in `md_tools_backup.py`, not here** — see "Backup Helpers".
