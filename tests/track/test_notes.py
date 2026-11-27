from __future__ import annotations

from getmeajob.files import read_jsonl
from getmeajob.track.notes import NotesLog, notes_path
from getmeajob.workspace import Workspace


def test_same_value_writes_nothing(tmp_ws: Workspace) -> None:
    log = NotesLog(tmp_ws)
    assert log.set("a:b:1", "notes", "  call Friday\r\n", "xlsx")
    assert not log.set("a:b:1", "notes", "call Friday", "xlsx")
    assert log.set("a:b:1", "next_action", "send portfolio", "xlsx")
    assert log.get("a:b:1").notes == "call Friday"
    assert log.get("a:b:1").next_action == "send portfolio"
    assert len(read_jsonl(notes_path(tmp_ws))) == 2


def test_clearing_a_note_is_recorded(tmp_ws: Workspace) -> None:
    log = NotesLog(tmp_ws)
    log.set("a:b:1", "notes", "old", "xlsx")
    assert log.set("a:b:1", "notes", "", "xlsx")
    assert "a:b:1" not in log.current()
    assert not log.set("a:b:1", "notes", None, "xlsx")
