import os
import unittest

import httpx

import _path  # noqa: F401

import app.ticket_client as tc
from app.ticket_client import TicketServiceError, create_ticket, list_tickets


class TicketClientTests(unittest.TestCase):
    def setUp(self):
        os.environ["TICKET_SERVICE_URL"] = "http://ticket.test"
        self._orig_client = tc.httpx.Client

    def tearDown(self):
        tc.httpx.Client = self._orig_client
        os.environ.pop("TICKET_SERVICE_URL", None)

    def _patch(self, handler):
        transport = httpx.MockTransport(handler)
        orig = self._orig_client
        tc.httpx.Client = lambda **kwargs: orig(transport=transport, **kwargs)

    def test_create_success(self):
        def handler(request):
            self.assertEqual(str(request.url), "http://ticket.test/tickets")
            return httpx.Response(201, json={"id": 5, "status": "NEW", "sessionId": "s1"})

        self._patch(handler)
        ticket = create_ticket("s1", "title", category="complaint", priority="high")
        self.assertEqual(ticket["id"], 5)
        self.assertEqual(ticket["status"], "NEW")

    def test_create_http_error_raises(self):
        def handler(request):
            return httpx.Response(500, json={"detail": "boom"})

        self._patch(handler)
        with self.assertRaises(TicketServiceError) as ctx:
            create_ticket("s1", "t")
        self.assertIn("HTTP 500", str(ctx.exception))

    def test_create_connection_error_raises(self):
        def handler(request):
            raise httpx.ConnectError("refused")

        self._patch(handler)
        with self.assertRaises(TicketServiceError) as ctx:
            create_ticket("s1", "t")
        self.assertIn("不可达", str(ctx.exception))

    def test_list_filters_by_session(self):
        captured = {}

        def handler(request):
            captured["session"] = request.url.params.get("sessionId")
            return httpx.Response(200, json=[{"id": 1, "sessionId": "s1"}])

        self._patch(handler)
        tickets = list_tickets(session_id="s1")
        self.assertEqual(captured["session"], "s1")
        self.assertEqual(len(tickets), 1)


if __name__ == "__main__":
    unittest.main()
