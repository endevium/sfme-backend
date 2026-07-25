import json

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from api.middleware import SQLInjectionProtectionMiddleware


class SecurityMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = SQLInjectionProtectionMiddleware(lambda request: HttpResponse("ok", status=200))

    def test_allows_safe_request(self):
        request = self.factory.get("/api/students/", {"q": "module evaluation"})
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)

    def test_blocks_plain_path_traversal_in_query(self):
        request = self.factory.get("/api/students/", {"q": "../etc/passwd"})
        response = self.middleware(request)
        self.assertEqual(response.status_code, 403)

    def test_blocks_double_encoded_path_traversal_in_query(self):
        request = self.factory.get("/api/students/", {"q": "%252e%252e%252fetc/passwd"})
        response = self.middleware(request)
        self.assertEqual(response.status_code, 403)

    def test_blocks_path_traversal_in_url(self):
        request = self.factory.get("/api/%2e%2e%2fsecret")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 403)

    def test_blocks_path_traversal_in_json_body(self):
        body = json.dumps({"file": "..%5cwindows%5cwin.ini"})
        request = self.factory.post(
            "/api/feedback/submit/",
            data=body,
            content_type="application/json",
        )
        response = self.middleware(request)
        self.assertEqual(response.status_code, 403)
