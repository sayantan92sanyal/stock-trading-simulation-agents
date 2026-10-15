import json
import threading
import urllib.error
import urllib.request

import pytest

import debate
import debate_server


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    monkeypatch.setattr(debate, "DEBATES_DIR", tmp_path / "debates")
    monkeypatch.setattr(debate_server, "ICONS_DIR", tmp_path / "icons")
    monkeypatch.setattr(debate_server, "VIEWER_HTML", tmp_path / "viewer.html")
    (tmp_path / "viewer.html").write_text("<html>debate viewer</html>")
    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "technical.png").write_bytes(b"fakepngbytes")

    server = debate_server.ThreadingHTTPServer(("127.0.0.1", 0), debate_server.DebateHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()
    thread.join()


def _get(port, path):
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_serves_viewer_html(running_server):
    url = f"http://127.0.0.1:{running_server}/"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        assert b"debate viewer" in resp.read()


def test_serves_icon_png(running_server):
    url = f"http://127.0.0.1:{running_server}/icons/technical.png"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        assert resp.read() == b"fakepngbytes"


def test_api_debates_empty_list_when_none_exist(running_server):
    status, body = _get(running_server, "/api/debates")
    assert status == 200
    assert body == []


def test_api_debate_returns_seeded_debate(running_server):
    state = debate.start_debate("Should I buy MSFT?")
    status, body = _get(running_server, f"/api/debate/{state['debate_id']}")
    assert status == 200
    assert body["topic"] == "Should I buy MSFT?"


def test_api_debate_404_for_unknown_id(running_server):
    status, body = _get(running_server, "/api/debate/does-not-exist-01")
    assert status == 404
    assert "error" in body


def test_unknown_path_returns_404(running_server):
    status, body = _get(running_server, "/not-a-real-route")
    assert status == 404
