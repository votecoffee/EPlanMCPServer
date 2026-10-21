import pytest

from scripts.package import ROOT_FILES, selected_files


def minimal_repo(tmp_path):
    repo = tmp_path / "app"
    repo.mkdir()
    for name in ROOT_FILES:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("public fixture", encoding="utf-8")
    return repo


def test_package_excludes_private_material_inside_public_folders(tmp_path):
    repo = minimal_repo(tmp_path)
    for name in ("docs/guide.md", "examples/synthetic/report.json", "src/service.py"):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("public fixture", encoding="utf-8")
    for name in (
        "docs/.local/receipt.md",
        "examples/private/customer.json",
        "tests/work/customer.py",
        "docs/outputs/notes.md",
        "src/.venv/private.py",
    ):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private sentinel", encoding="utf-8")
    selected = {p.relative_to(repo).as_posix() for p in selected_files(repo)}
    assert "docs/guide.md" in selected
    assert "examples/synthetic/report.json" in selected
    assert not any("private sentinel" in p.read_text(encoding="utf-8") for p in selected_files(repo))


def test_package_rejects_source_symlinks(tmp_path, monkeypatch):
    repo = minimal_repo(tmp_path)
    (repo / "src").mkdir()
    link = repo / "src/link.py"
    link.write_text("private sentinel", encoding="utf-8")
    original = type(link).is_symlink
    monkeypatch.setattr(type(link), "is_symlink", lambda path: path == link or original(path))
    with pytest.raises(ValueError, match="symbolic links"):
        selected_files(repo)
