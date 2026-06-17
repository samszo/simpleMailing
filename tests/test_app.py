import json
import unittest
from unittest.mock import MagicMock, patch

from app import ListmonkAPIError, ListmonkClient


class ListmonkClientTests(unittest.TestCase):
    def test_auth_header_uses_basic_scheme(self):
        client = ListmonkClient("http://localhost:9000", "admin", "secret")
        self.assertEqual(client.auth_header, "Basic YWRtaW46c2VjcmV0")

    @patch("app.urlopen")
    def test_get_lists_handles_results_container(self, mock_urlopen):
        response = MagicMock()
        response.read.return_value = json.dumps(
            {
                "data": {
                    "results": [
                        {"id": 1, "name": "Newsletter"},
                        {"id": 2, "name": "Clients"},
                    ]
                }
            }
        ).encode("utf-8")

        mock_urlopen.return_value.__enter__.return_value = response

        client = ListmonkClient("http://localhost:9000", "admin", "secret")
        self.assertEqual(
            client.get_lists(),
            [
                {"id": 1, "name": "Newsletter"},
                {"id": 2, "name": "Clients"},
            ],
        )

    def test_send_campaign_fails_when_campaign_id_is_missing(self):
        client = ListmonkClient("http://localhost:9000", "admin", "secret")
        client._request = MagicMock(return_value={"data": {}})

        with self.assertRaises(ListmonkAPIError):
            client.send_campaign([1], "sender@example.com", "Sujet", "<p>Hello</p>")


if __name__ == "__main__":
    unittest.main()
