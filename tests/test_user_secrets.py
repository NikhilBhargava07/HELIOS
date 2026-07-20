## Verify temporary DynamoDB broker-secret pointers without contacting AWS.

import unittest
from unittest.mock import patch

from backend.users.profiles import public_profile
from backend.users.secrets import get_broker_secret, save_broker_secret


class BrokerSecretPointerTests(unittest.TestCase):
    ## Save secrets under a user-specific key and return an opaque backend pointer.
    @patch("backend.users.secrets.utc_now_text", return_value="2026-07-20T00:00:00+00:00")
    @patch("backend.users.secrets.put_item")
    def test_save_returns_dynamodb_pointer(self, put_item, _utc_now_text):
        pointer = save_broker_secret("google|user:1", "Alpaca", "secret-value")

        self.assertEqual(
            pointer,
            "dynamodb://USER_SECRET#google-user-1/BROKER#alpaca",
        )
        self.assertEqual(put_item.call_args.args[0]["secret_key"], "secret-value")

    ## Resolve only supported pointers and return the backend-only secret value.
    @patch("backend.users.secrets.get_item", return_value={"secret_key": "secret-value"})
    def test_get_resolves_pointer(self, get_item):
        value = get_broker_secret(
            "dynamodb://USER_SECRET#google_user-1/BROKER#alpaca"
        )

        self.assertEqual(value, "secret-value")
        get_item.assert_called_once_with(
            "USER_SECRET#google_user-1",
            "BROKER#alpaca",
        )

    ## Require the active DynamoDB pointer before reporting a broker connection.
    ## A legacy Secrets Manager ARN must return to onboarding instead of failing later during broker access.
    def test_legacy_secret_arn_is_not_connected(self):
        profile = public_profile({
            "user_id": "google-user-1",
            "email": "user@example.com",
            "name": "Example User",
            "broker": "alpaca",
            "broker_secret_arn": "arn:aws:secretsmanager:legacy",
        })

        self.assertFalse(profile["broker_connected"])


if __name__ == "__main__":
    unittest.main()
