"""A real delivery over HTTP to a local receiver: the sender, the signature and the body."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from mandate.api.notify import HttpSender, check_url, sign

pytestmark = pytest.mark.integration


class Receiver(BaseHTTPRequestHandler):
    seen: list[tuple[dict[str, str], bytes]] = []
    answer = 200

    def do_POST(self) -> None:  # noqa: N802 - the http.server API
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Receiver.seen.append((dict(self.headers.items()), body))
        self.send_response(Receiver.answer)
        self.end_headers()

    def log_message(self, *_args: Any) -> None:
        return


@pytest.fixture
def receiver() -> Any:
    server = HTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    Receiver.seen = []
    Receiver.answer = 200
    yield f"http://127.0.0.1:{server.server_address[1]}/hook"
    server.shutdown()


def test_a_signed_delivery_arrives(receiver: str) -> None:
    body = json.dumps({"event": "webhook.test"}).encode()
    headers = {"Content-Type": "application/json", "X-Mandate-Timestamp": "1700000000",
               "X-Mandate-Signature": sign("whsec_x", "1700000000", body)}  # fmt: skip
    result = HttpSender(allow_private=True).post(receiver, body, headers)
    assert result.ok and result.status == 200
    (got_headers, got_body) = Receiver.seen[0]
    assert got_body == body
    assert got_headers["X-Mandate-Signature"] == sign("whsec_x", "1700000000", got_body)


def test_an_error_answer_is_reported_and_a_private_address_is_refused(receiver: str) -> None:
    Receiver.answer = 503
    result = HttpSender(allow_private=True).post(receiver, b"{}", {})
    assert (result.ok, result.status, result.retryable) == (False, 503, True)
    refused = HttpSender(allow_private=False).post(receiver, b"{}", {})
    assert refused.status is None and refused.error and len(Receiver.seen) == 1
    with pytest.raises(Exception, match="https"):
        check_url(receiver, allow_private=False)
