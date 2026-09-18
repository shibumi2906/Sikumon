from pathlib import Path

from sikumon.storage.paths import ApplicationPaths


def test_application_paths_use_override_and_create_directories(tmp_path: Path) -> None:
    root = tmp_path / "isolated-data"
    paths = ApplicationPaths.resolve(root)

    assert paths.root == root
    assert paths.database == root / "sikumon.db"
    assert paths.models == root / "models"
    assert paths.meetings == root / "meetings"
    assert paths.logs == root / "logs"
    assert paths.cache == root / "cache"

    paths.ensure_directories()
    assert all(path.is_dir() for path in (root, paths.models, paths.meetings, paths.logs, paths.cache))


def test_default_application_path_uses_local_app_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert ApplicationPaths.resolve().root == tmp_path / "Sikumon"

