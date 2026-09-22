import pytest


@pytest.fixture(autouse=True)
def graphview_home(tmp_path_factory, monkeypatch):
    """Exports record a line of history in the user's home: never the real one in tests."""
    home = tmp_path_factory.mktemp("graphview-home")
    monkeypatch.setenv("GRAPHVIEW_HOME", str(home))
    return home
