from soundcork.devices import read_file_from_speaker_http


def test_read_file_from_speaker_http_passes_timeout(monkeypatch):
    calls = []

    class Response:
        def read(self) -> bytes:
            return b"<info />"

    def fake_urlopen(url: str, timeout: int):
        calls.append((url, timeout))
        return Response()

    monkeypatch.setattr("soundcork.devices.urllib.request.urlopen", fake_urlopen)

    result = read_file_from_speaker_http("192.0.2.10", "/info", timeout=7)

    assert result == "<info />"
    assert calls == [("http://192.0.2.10:8090/info", 7)]
