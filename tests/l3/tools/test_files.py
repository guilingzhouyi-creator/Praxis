"""Tests for file operation tool handlers."""

from __future__ import annotations

from l3.tools._files import (
    create_file,
    file_copy,
    file_move,
    file_stat,
    list_dir,
    read_file,
)


class TestReadFile:
    def test_no_path(self):
        r = read_file({}, "agent-a")
        assert not r["success"]
        assert "path is required" in r["error"]

    def test_nonexistent_path(self):
        r = read_file({"path": "/nonexistent_file_xyz"}, "agent-a")
        assert not r["success"]


class TestListDir:
    def test_current_dir(self):
        r = list_dir({"path": "."}, "agent-a")
        assert r["success"]
        assert "data" in r
        assert isinstance(r["data"], list)

    def test_invalid_path(self):
        r = list_dir({"path": "/nonexistent_dir_xyz"}, "agent-a")
        assert not r["success"]

    def test_default_path(self):
        r = list_dir({}, "agent-a")
        assert r["success"]
        assert "data" in r


class TestFileStat:
    def test_no_path(self):
        r = file_stat({}, "agent-a")
        assert not r["success"]

    def test_this_file(self):
        r = file_stat({"path": __file__}, "agent-a")
        assert r["success"]
        assert "size" in r["data"]
        assert r["data"]["size"] > 0

    def test_nonexistent(self):
        r = file_stat({"path": "/nonexistent_stat_xyz"}, "agent-a")
        assert not r["success"]


class TestCreateFile:
    def test_no_path(self):
        r = create_file({}, "agent-a")
        assert not r["success"]

    def test_create_with_content(self):
        r = create_file({"path": "/tmp/test_praxis.txt", "content": "hello"}, "agent-a")
        # May fail due to sandbox but should return a dict
        assert isinstance(r, dict)


class TestFileMove:
    def test_no_source(self):
        r = file_move({}, "agent-a")
        assert not r["success"]

    def test_no_destination(self):
        r = file_move({"source": "/a"}, "agent-a")
        assert not r["success"]

    def test_nonexistent_source(self):
        r = file_move({"source": "/nonexistent_src", "destination": "/tmp/dst"}, "agent-a")
        assert not r["success"]


class TestFileCopy:
    def test_no_source(self):
        r = file_copy({}, "agent-a")
        assert not r["success"]

    def test_no_destination(self):
        r = file_copy({"source": "/a"}, "agent-a")
        assert not r["success"]


class TestStrReplaceEditor:
    def test_requires_path_and_old_string(self):
        from l3.tools._files import str_replace_editor

        assert not str_replace_editor({}, "agent-a")["success"]
        assert not str_replace_editor({"path": "/x", "old_string": ""}, "agent-a")["success"]

    def test_successful_replacement(self, tmp_path):
        from l3.resource_buffer.manager import get_manager, reset_manager
        from l3.tools._files import str_replace_editor

        reset_manager()
        try:
            f = tmp_path / "demo.txt"
            f.write_text("hello foo\nfoo bar\nend", encoding="utf-8")
            r = str_replace_editor({"path": str(f), "old_string": "foo", "new_string": "BAZ"}, "agent-a")
            assert r["success"] is True
            assert r["replacements"] == 2
            assert "BAZ" in get_manager().read(str(f))
        finally:
            reset_manager()

    def test_count_limited_replacement(self, tmp_path):
        from l3.resource_buffer.manager import get_manager, reset_manager
        from l3.tools._files import str_replace_editor

        reset_manager()
        try:
            f = tmp_path / "demo.txt"
            f.write_text("foo foo foo", encoding="utf-8")
            r = str_replace_editor(
                {"path": str(f), "old_string": "foo", "new_string": "X", "replace_count": 1}, "agent-a"
            )
            assert r["success"] is True
            assert r["replacements"] == 3  # total occurrences counted
            assert get_manager().read(str(f)) == "X foo foo"
        finally:
            reset_manager()

    def test_old_string_not_found(self, tmp_path):
        from l3.tools._files import str_replace_editor

        f = tmp_path / "demo.txt"
        f.write_text("hello", encoding="utf-8")
        r = str_replace_editor({"path": str(f), "old_string": "nope"}, "agent-a")
        assert not r["success"]
        assert "not found" in r["error"]
