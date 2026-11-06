---
name: example-skill
description: A skill file with YAML frontmatter, as Claude Code skills carry. The block is held opaque and reattached byte-verbatim.
argument-hint: "[--flag]"
effort: medium
---

# Example skill

Body prose before the first subsection.

## Procedure

1. Run `md_tools list FILE` first.
2. Then operate by path.

```bash
# a heading-looking line inside a fence is content, never structure
md_tools read FILE "Section"
```

### Notes  [ ]

- A bullet with `code` and a trailing marker on the heading above.
