from sikumon.database.orm_models import MeetingORM
from sikumon.database.repositories import MeetingRepository


def test_repository_create_update_get_list_and_delete(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    created = repository.create(
        MeetingORM(
            title="ישיבת צוות",
            original_filename="team.m4a",
            audio_path="C:/Sikumon/team.m4a",
        )
    )

    loaded = repository.get(created.id)
    assert loaded is not None
    assert loaded.title == "ישיבת צוות"
    assert loaded.transcript_revision == 0
    assert [meeting.id for meeting in repository.list()] == [created.id]

    loaded.title = "נשמרה מחדש"
    repository.save(loaded)
    assert repository.get(created.id).title == "נשמרה מחדש"

    repository.update(created.id, title="ישיבת צוות מעודכנת")
    assert repository.get(created.id).title == "ישיבת צוות מעודכנת"
    assert repository.delete(created.id)
    assert repository.get(created.id) is None
    assert not repository.delete(created.id)
