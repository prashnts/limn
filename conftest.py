# Tests never touch the real capture store (RAM on the Pi, limn_cam/scan.py)
import pytest


@pytest.fixture(autouse=True)
def _captures(tmp_path, monkeypatch):
    monkeypatch.setenv('LIMN_CAPTURES', str(tmp_path / 'captures'))


def pytest_configure(config):
    # The UI tests (plot/tests/test_ui.py) run in Firefox unless --browser says otherwise
    if config.pluginmanager.hasplugin('playwright') and not config.getoption('browser', None):
        config.option.browser = ['firefox']
