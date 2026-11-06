"""Unit tests for md_tools_backup.py"""

import os
import time
from pathlib import Path

import pytest
import md_tools_backup
from md_tools_backup import (
    find_root_dir,
    _get_backup_prefix,
    create_backup,
    cleanup_backups,
)


# ============================================================================
# TestFindRootDir
# ============================================================================

class TestFindRootDir:

    def test_finds_claude_md(self, tmp_path):
        """Finds CLAUDE.md walking up from a subdirectory."""
        proj = tmp_path / "proj"
        sub = proj / "subdir"
        sub.mkdir(parents=True)
        (proj / "CLAUDE.md").write_text("# test\n")
        (sub / "file.txt").write_text("content")

        result = find_root_dir(str(sub / "file.txt"))
        assert result == str(proj)

    def test_finds_custom_marker(self, tmp_path):
        """Finds .git directory when specified as marker."""
        proj = tmp_path / "proj"
        sub = proj / "sub"
        sub.mkdir(parents=True)
        (proj / ".git").mkdir()
        (sub / "f.txt").write_text("x")

        result = find_root_dir(str(sub / "f.txt"), markers=[".git"])
        assert result == str(proj)

    def test_multiple_markers_any(self, tmp_path):
        """Finds directory when any one marker matches."""
        proj = tmp_path / "proj"
        sub = proj / "sub"
        sub.mkdir(parents=True)
        (proj / ".git").mkdir()  # Only .git, no CLAUDE.md
        (sub / "f.txt").write_text("x")

        result = find_root_dir(str(sub / "f.txt"), markers=["CLAUDE.md", ".git"])
        assert result == str(proj)

    def test_returns_none_no_marker(self, tmp_path):
        """Returns None when no marker exists in any parent."""
        sub = tmp_path / "a" / "b" / "c"
        sub.mkdir(parents=True)
        (sub / "f.txt").write_text("x")

        result = find_root_dir(str(sub / "f.txt"))
        assert result is None

    def test_start_is_root_dir(self, tmp_path):
        """Works when start_path IS the directory with the marker."""
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "CLAUDE.md").write_text("# test\n")

        result = find_root_dir(str(proj))
        assert result == str(proj)

    def test_start_is_file_in_root(self, tmp_path):
        """Works when start_path is a file in the root directory."""
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "CLAUDE.md").write_text("# test\n")
        (proj / "foo.txt").write_text("x")

        result = find_root_dir(str(proj / "foo.txt"))
        assert result == str(proj)


# ============================================================================
# TestGetProjectPath
# ============================================================================

class TestGetBackupPrefix:

    def test_project_root_file(self, tmp_path):
        """File at project root gets project name as prefix."""
        proj = tmp_path / "myproject"
        proj.mkdir()
        (proj / "CLAUDE.md").write_text("# test\n")
        f = proj / "file.txt"
        f.write_text("x")

        prefix = _get_backup_prefix(str(f))
        assert prefix == "myproject"

    def test_project_subdir_file(self, tmp_path):
        """File in subdirectory gets project_subdir prefix."""
        proj = tmp_path / "myproject"
        sub = proj / "subdir"
        sub.mkdir(parents=True)
        (proj / "CLAUDE.md").write_text("# test\n")
        f = sub / "file.txt"
        f.write_text("x")

        prefix = _get_backup_prefix(str(f))
        assert prefix == "myproject_subdir"

    def test_no_project_fallback(self, tmp_path):
        """File not in a project uses last 2 directory components."""
        deep = tmp_path / "some" / "deep" / "dir"
        deep.mkdir(parents=True)
        f = deep / "file.txt"
        f.write_text("x")

        prefix = _get_backup_prefix(str(f))
        assert "deep_dir" in prefix

    def test_dot_claude_prefix_fix(self, tmp_path):
        """Prefix starting with .claude is fixed to home.claude."""
        dotclaude = tmp_path / ".claude"
        dotclaude.mkdir()
        (dotclaude / "CLAUDE.md").write_text("# test\n")
        f = dotclaude / "settings.json"
        f.write_text("{}")

        prefix = _get_backup_prefix(str(f))
        assert prefix.startswith("home.claude") or not prefix.startswith(".claude")


# ============================================================================
# TestCreateBackup
# ============================================================================

class TestCreateBackup:

    def test_creates_backup_file(self, tmp_path, monkeypatch):
        """Backup file is created with correct content."""
        monkeypatch.setenv("HOME", str(tmp_path))
        source = tmp_path / "source.txt"
        source.write_text("original content")

        result = create_backup(str(source), "test_tool")

        assert result is not None
        assert os.path.exists(result)
        with open(result) as f:
            assert f.read() == "original content"

    def test_tool_name_directory(self, tmp_path, monkeypatch):
        """Backup goes to ~/.claude/backups/{tool_name}/."""
        monkeypatch.setenv("HOME", str(tmp_path))
        source = tmp_path / "source.txt"
        source.write_text("x")

        result = create_backup(str(source), "my_tool")

        assert "my_tool" in result
        assert os.path.isdir(tmp_path / ".claude" / "backups" / "my_tool")

    def test_correct_filename_format(self, tmp_path, monkeypatch):
        """Backup filename has correct format with timestamp."""
        monkeypatch.setenv("HOME", str(tmp_path))
        source = tmp_path / "source.txt"
        source.write_text("x")

        result = create_backup(str(source), "test_tool")

        basename = os.path.basename(result)
        assert ".backup_" in basename
        assert basename.endswith(".txt")

    def test_invocation_dedup_skips(self, tmp_path, monkeypatch):
        """Second call with same file in same invocation returns None."""
        monkeypatch.setenv("HOME", str(tmp_path))
        source = tmp_path / "source.txt"
        source.write_text("x")

        first = create_backup(str(source), "test_tool")
        second = create_backup(str(source), "test_tool")

        assert first is not None
        assert second is None

    def test_different_files_not_deduped(self, tmp_path, monkeypatch):
        """Different files are both backed up."""
        monkeypatch.setenv("HOME", str(tmp_path))
        source1 = tmp_path / "file1.txt"
        source2 = tmp_path / "file2.txt"
        source1.write_text("one")
        source2.write_text("two")

        r1 = create_backup(str(source1), "test_tool")
        r2 = create_backup(str(source2), "test_tool")

        assert r1 is not None
        assert r2 is not None
        assert r1 != r2

    def test_hourly_dedup_skips(self, tmp_path, monkeypatch):
        """Skips if backup from same hour already exists."""
        monkeypatch.setenv("HOME", str(tmp_path))
        source = tmp_path / "source.txt"
        source.write_text("x")

        # Create first backup normally
        first = create_backup(str(source), "test_tool")
        assert first is not None

        # Reset _backed_up to simulate a new invocation (but same hour)
        md_tools_backup._backed_up.clear()

        # Second call should find existing backup from same hour
        second = create_backup(str(source), "test_tool")
        # Should return the existing backup path, not create new
        assert second == first


# ============================================================================
# TestCleanupBackups
# ============================================================================

class TestCleanupBackups:

    def test_keeps_most_recent(self, tmp_path):
        """Keeps only the most recent backup per file group."""
        d = tmp_path / "backups"
        d.mkdir()
        (d / "proj.file.backup_20260101_100000.txt").write_text("old1")
        (d / "proj.file.backup_20260101_120000.txt").write_text("old2")
        (d / "proj.file.backup_20260101_150000.txt").write_text("newest")

        cleanup_backups(str(d))

        remaining = list(d.glob("*.backup_*"))
        assert len(remaining) == 1
        assert "150000" in remaining[0].name

    def test_separate_file_groups(self, tmp_path):
        """Keeps newest of each file group independently."""
        d = tmp_path / "backups"
        d.mkdir()
        (d / "file_a.backup_20260101_100000.txt").write_text("a_old")
        (d / "file_a.backup_20260101_120000.txt").write_text("a_new")
        (d / "file_b.backup_20260101_100000.txt").write_text("b_old")
        (d / "file_b.backup_20260101_120000.txt").write_text("b_new")

        cleanup_backups(str(d))

        remaining = list(d.glob("*.backup_*"))
        assert len(remaining) == 2
        names = [r.name for r in remaining]
        assert any("file_a" in n and "120000" in n for n in names)
        assert any("file_b" in n and "120000" in n for n in names)

    def test_empty_directory(self, tmp_path):
        """Returns True for empty directory."""
        d = tmp_path / "empty"
        d.mkdir()

        result = cleanup_backups(str(d))
        assert result is True

    def test_tilde_expansion(self, tmp_path, monkeypatch):
        """Handles ~ in directory path."""
        monkeypatch.setenv("HOME", str(tmp_path))
        d = tmp_path / "backups"
        d.mkdir()
        (d / "f.backup_20260101_100000.txt").write_text("x")

        result = cleanup_backups("~/backups")
        assert result is True
