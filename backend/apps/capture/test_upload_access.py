import asyncio
import json
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from asgiref.sync import sync_to_async
from django.test import TransactionTestCase, override_settings

from backend.config import asgi

from .pc_registry import create_agent, revoke_agent
from .upload_access import reserve_fragment_upload


class UploadAccessTests(TransactionTestCase):
    def setUp(self):
        root = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(CAPTURE_FRAGMENT_ROOT=root, CAPTURE_V2_MAX_CONCURRENT_UPLOADS=5))
        self.agent, token = create_agent(name="PC de prueba", box="box-3")
        self.header = (b"authorization", f"Agent {token}".encode("ascii"))

    async def request(self, *headers):
        scope = {
            "type": "http", "method": "POST", "path": "/api/v2/internal/fragments",
            "client": ("127.0.0.1", 1234), "headers": list(headers),
        }
        receive = AsyncMock()
        send = AsyncMock()
        await asgi.application(scope, receive, send)
        return scope, receive, send

    async def test_missing_credential_rejects_without_reading(self):
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            _, receive, send = await self.request()
            receive.assert_not_awaited()
            self.assertEqual(send.await_args_list[0].args[0]["status"], 401)
            self.assertEqual(json.loads(send.await_args.args[0]["body"])["error"]["code"], "AUTH_REQUIRED")
            django_app.assert_not_awaited()

    async def test_authorized_upload_is_forwarded_without_consuming_body(self):
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            scope, receive, send = await self.request(self.header)
            django_app.assert_awaited_once_with(scope, receive, send)
            receive.assert_not_awaited()

    async def test_revoked_agent_is_rejected_before_django_reads_upload(self):
        await sync_to_async(revoke_agent)(self.agent)
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            _, receive, send = await self.request(self.header)
            receive.assert_not_awaited()
            self.assertEqual(send.await_args_list[0].args[0]["status"], 401)
            self.assertEqual(json.loads(send.await_args.args[0]["body"])["error"]["code"], "AUTH_INVALID_TOKEN")
            django_app.assert_not_awaited()

    async def test_same_box_retry_waits_without_reading_upload(self):
        with reserve_fragment_upload(self.agent.box) as reserved:
            self.assertTrue(reserved)
            _, receive, send = await self.request(self.header)
            receive.assert_not_awaited()
            response = send.await_args_list[0].args[0]
            self.assertEqual(response["status"], 503)
            self.assertIn((b"retry-after", b"5"), response["headers"])
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            await self.request(self.header)
            django_app.assert_awaited_once()

    async def test_five_boxes_with_same_ip_can_upload_at_once(self):
        headers = [self.header]
        for number in range(4, 8):
            _, token = await sync_to_async(create_agent)(name=f"PC {number}", box=f"box-{number}")
            headers.append((b"authorization", f"Agent {token}".encode("ascii")))
        all_entered = asyncio.Event()
        release = asyncio.Event()
        entered = []

        async def django_app(scope, receive, send):
            entered.append(scope["client"][0])
            if len(entered) == 5:
                all_entered.set()
            await release.wait()

        with patch.object(asgi, "http_application", django_app):
            async with asyncio.TaskGroup() as tasks:
                for header in headers:
                    tasks.create_task(self.request(header))
                try:
                    await asyncio.wait_for(all_entered.wait(), timeout=5)
                    self.assertEqual(entered, ["127.0.0.1"] * 5)
                    with reserve_fragment_upload("box-other") as reserved:
                        self.assertFalse(reserved)
                finally:
                    release.set()
        with reserve_fragment_upload("box-other") as reserved:
            self.assertTrue(reserved)

    async def test_interrupted_upload_releases_the_box_slot(self):
        interrupted = AsyncMock(side_effect=asyncio.CancelledError)
        with patch.object(asgi, "http_application", interrupted):
            with self.assertRaises(asyncio.CancelledError):
                await self.request(self.header)
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            await self.request(self.header)
            django_app.assert_awaited_once()
