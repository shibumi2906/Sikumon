from datetime import UTC, datetime
from uuid import uuid4

from sikumon.domain.transcript import TranscriptSegment
from sikumon.ui.transcript_view import TranscriptView


def segments() -> tuple[TranscriptSegment, ...]:
    meeting_id = uuid4()
    now = datetime.now(UTC)
    return (
        TranscriptSegment(uuid4(), meeting_id, 0, 500, 1_500, "שלום 123", now, now),
        TranscriptSegment(
            uuid4(), meeting_id, 1, 2_000, 3_000, "פגישה עם Alice!", now, now
        ),
    )


def test_dirty_state_tracks_actual_text_and_reversion(qapp) -> None:
    view = TranscriptView()
    source = segments()
    changes: list[bool] = []
    view.dirty_changed.connect(changes.append)
    view.set_segments(source, revision=4)

    assert not view.is_dirty
    assert view.source_revision == 4
    assert not view.save_button.isEnabled()

    view.segment_editors[0].setPlainText("שלום 456")
    qapp.processEvents()
    assert view.is_dirty
    assert view.save_button.isEnabled()
    assert view.unsaved_label.text() == "יש שינויים שלא נשמרו"

    view.segment_editors[0].setPlainText("שלום 123")
    qapp.processEvents()
    assert not view.is_dirty
    assert not view.save_button.isEnabled()
    assert changes == [True, False]


def test_editors_are_rtl_timestamps_ltr_and_lookup_uses_stable_id(qapp) -> None:
    view = TranscriptView()
    source = segments()
    view.set_segments(source, revision=1)
    view.show()
    qapp.processEvents()
    segment_id = str(source[1].id)

    assert all(editor.layoutDirection().name == "RightToLeft" for editor in view.segment_editors)
    assert all(label.layoutDirection().name == "LeftToRight" for label in view.timestamp_labels)
    assert view.editor_for_segment(segment_id) is view.segment_editors[1]
    assert view.focus_segment(segment_id)
    assert view.segment_editors[1].hasFocus()
    assert not view.focus_segment(str(uuid4()))

    view.segment_editors[1].setPlainText("פגישה עם Bob 42, בסדר?")
    qapp.processEvents()
    assert view.current_texts()[segment_id] == "פגישה עם Bob 42, בסדר?"


def test_save_blocking_and_discard_keep_local_state_deterministic(qapp) -> None:
    view = TranscriptView()
    source = segments()
    view.set_segments(source, revision=2, save_blocked=True)
    view.segment_editors[0].setPlainText("תיקון")
    assert view.is_dirty
    assert not view.save_button.isEnabled()

    view.set_save_blocked(False)
    assert view.save_button.isEnabled()
    view.discard_changes()
    assert not view.is_dirty
    assert view.segment_editors[0].toPlainText() == source[0].text


def test_copy_export_actions_and_export_data_follow_visible_edits(qapp) -> None:
    view = TranscriptView()
    source = segments()
    copied: list[bool] = []
    exported: list[bool] = []
    view.copy_requested.connect(lambda: copied.append(True))
    view.export_requested.connect(lambda: exported.append(True))
    view.set_segments(source, revision=3)

    view.segment_editors[0].setPlainText("טקסט ערוך")
    view.copy_button.click()
    view.export_button.click()
    qapp.processEvents()

    result = view.export_segments()
    assert copied == [True]
    assert exported == [True]
    assert result[0].text == "טקסט ערוך"
    assert result[0].start_time_ms == 500
    assert result[1].end_time_ms == 3_000

    view.set_segments(())
    assert not view.actions_bar.isVisible()
