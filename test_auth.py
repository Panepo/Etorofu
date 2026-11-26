import json
import unittest
from unittest.mock import patch

import httpx

import server


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.login_status = 200
        self.verify_status = 200
        self.login_body = {"token": "test-token"}
        self.verify_body = {"id": "test-user"}

        def upstream(request):
            self.requests.append(request)
            if request.method == "POST":
                return httpx.Response(self.login_status, json=self.login_body)
            return httpx.Response(self.verify_status, json=self.verify_body)

        self.env_patch = patch.dict("os.environ", {"SHIRATSUYU_BASE_URL": "https://auth.example/api"})
        self.env_patch.start()
        self.upstream_patch = patch.object(
            server, "shiratsuyu_client",
            side_effect=lambda: httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
        )
        self.upstream_patch.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="https://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.upstream_patch.stop()
        self.env_patch.stop()

    async def login(self):
        return await self.client.post("/auth/login", json={"email": "user@example.com", "password": "secret"})

    async def test_login_and_protected_access_then_logout(self):
        self.assertEqual((await self.client.get("/reports")).status_code, 401)
        redirect = await self.client.get("/", headers={"Accept": "text/html"})
        self.assertEqual(redirect.status_code, 303)
        self.assertEqual(redirect.headers["location"], "/login")
        self.assertEqual((await self.client.get("/login")).status_code, 200)

        response = await self.login()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("test-token", response.text)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("Secure", response.headers["set-cookie"])
        self.assertIn("SameSite=strict", response.headers["set-cookie"])
        self.assertEqual(str(self.requests[0].url), "https://auth.example/api/auth")
        self.assertEqual(json.loads(self.requests[0].content), {
            "email": "user@example.com", "password": "secret", "server": "shiratsuyu"
        })
        self.assertEqual(self.requests[1].headers["authorization"], "Bearer test-token")
        self.assertEqual((await self.client.get("/")).status_code, 200)
        self.assertEqual((await self.client.get("/cron.html")).status_code, 200)
        self.assertEqual((await self.client.post("/auth/logout")).status_code, 200)
        self.assertEqual((await self.client.get("/reports")).status_code, 401)

    async def test_rejected_login_and_malformed_response(self):
        for status, expected in ((401, 401), (404, 403), (500, 502)):
            self.login_status = status
            response = await self.login()
            self.assertEqual(response.status_code, expected)
            self.assertNotIn("etorofu_session", response.cookies)
            if status == 500:
                self.assertIn("HTTP 500", response.json()["detail"])
        self.login_status = 200
        self.login_body = {"name": "no token"}
        self.assertEqual((await self.login()).status_code, 502)
        self.assertEqual(len([r for r in self.requests if r.method == "GET"]), 0)

    async def test_expired_session_and_upstream_failure_fail_closed(self):
        self.assertEqual((await self.login()).status_code, 200)
        self.verify_status = 401
        response = await self.client.get("/scheduled-topics")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Max-Age=0", response.headers["set-cookie"])
        self.verify_status = 500
        response = await self.client.get("/reports", headers={"Authorization": "Bearer test-token"})
        self.assertEqual(response.status_code, 503)
        self.verify_status = 200
        self.verify_body = {}
        self.assertEqual((await self.client.get("/reports", headers={"Authorization": "Bearer test-token"})).status_code, 502)

    async def test_login_requires_validated_token_and_api_accepts_bearer(self):
        self.verify_status = 403
        self.assertEqual((await self.login()).status_code, 401)
        self.assertNotIn("etorofu_session", self.client.cookies)
        self.verify_status = 200
        self.assertEqual((await self.client.get("/openapi.json", headers={"Authorization": "Bearer test-token"})).status_code, 200)
        self.assertEqual((await self.client.get("/openapi.json")).status_code, 401)

    async def test_created_login_response_is_accepted(self):
        self.login_status = 201
        response = await self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual((await self.client.get("/openapi.json")).status_code, 200)

    async def test_login_behind_root_path(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app, root_path="/etorofu"),
            base_url="https://test/etorofu",
        ) as client:
            response = await client.get("/", headers={"Accept": "text/html"})
            self.assertEqual(response.headers["location"], "/etorofu/login")
            self.assertEqual((await client.get("/login")).status_code, 200)
            response = await client.post("/auth/login", json={"email": "user@example.com", "password": "secret"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual((await client.get("/cron.html")).status_code, 200)

    async def test_password_not_reflected_and_cross_origin_write_rejected(self):
        password = "s" * 1025
        response = await self.client.post("/auth/login", json={"email": "user@example.com", "password": password})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(password, response.text)
        self.assertEqual((await self.login()).status_code, 200)
        response = await self.client.post(
            "/research", json={"topic": "test"}, headers={"Origin": "https://other.example"}
        )
        self.assertEqual(response.status_code, 403)

    async def test_network_failure_and_missing_configuration(self):
        def unavailable(request):
            raise httpx.ConnectError("unavailable", request=request)

        with patch.object(server, "shiratsuyu_client", side_effect=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(unavailable)
        )):
            self.assertEqual((await self.login()).status_code, 503)
            self.assertEqual((await self.client.get(
                "/reports", headers={"Authorization": "Bearer test-token"}
            )).status_code, 503)
        with patch.dict("os.environ", {"SHIRATSUYU_BASE_URL": ""}):
            self.assertEqual((await self.login()).status_code, 503)


if __name__ == "__main__":
    unittest.main()
