## Verify broker secrets are kept in Secrets Manager and never reach the browser.
##
## A broker secret key can place trades, so it lives apart from the table holding
## everything else. These tests pin the three things that matter: a new secret is
## written to Secrets Manager under a name the IAM policy allows, a secret saved
## before the move is still readable, and no route can hand either one to the UI.

import unittest
from unittest.mock import Mock, patch

from backend.users.profiles import public_profile
from backend.users.secrets import (
    broker_secret_name,
    get_broker_secret,
    save_broker_secret,
)


## Stand in for the Secrets Manager client, including the exception it raises on a repeat name.
def secrets_client(existing=False):
    client = Mock()
    client.exceptions.ResourceExistsException = type("ResourceExistsException", (Exception,), {})
    if existing:
        client.create_secret.side_effect = client.exceptions.ResourceExistsException()
    client.put_secret_value.return_value = {"ARN": "arn:aws:secretsmanager:us-east-1:1:secret:helios/users/u/alpaca-b"}
    client.create_secret.return_value = {"ARN": "arn:aws:secretsmanager:us-east-1:1:secret:helios/users/u/alpaca-a"}
    return client


class BrokerSecretNameTests(unittest.TestCase):
    ## The name stays inside the prefix the Lambda's IAM policy is scoped to.
    def test_name_is_scoped_per_user_and_broker(self):
        self.assertEqual(
            broker_secret_name("google|user:1", "Alpaca"),
            "helios/users/google-user-1/alpaca",
        )


class BrokerSecretWriteTests(unittest.TestCase):
    ## A first connection creates the secret and stores the returned ARN on the profile.
    @patch("backend.users.secrets._secrets_client")
    def test_first_connection_creates_the_secret(self, client_factory):
        client = secrets_client()
        client_factory.return_value = client

        pointer = save_broker_secret("google|user:1", "Alpaca", "secret-value")

        self.assertTrue(pointer.startswith("arn:aws:secretsmanager:"))
        self.assertEqual(client.create_secret.call_args.kwargs["Name"], "helios/users/google-user-1/alpaca")
        self.assertEqual(client.create_secret.call_args.kwargs["SecretString"], "secret-value")

    ## Reconnecting replaces the value, because an existing name cannot be created twice.
    @patch("backend.users.secrets._secrets_client")
    def test_reconnecting_updates_the_existing_secret(self, client_factory):
        client = secrets_client(existing=True)
        client_factory.return_value = client

        pointer = save_broker_secret("google|user:1", "Alpaca", "rotated-value")

        self.assertTrue(pointer.startswith("arn:aws:secretsmanager:"))
        self.assertEqual(client.put_secret_value.call_args.kwargs["SecretString"], "rotated-value")

    ## Nothing new is written to the table that holds ordinary memory.
    @patch("backend.users.secrets._secrets_client")
    @patch("backend.memory.dynamodb_store.put_item")
    def test_saving_never_writes_the_secret_to_the_memory_table(self, put_item, client_factory):
        client_factory.return_value = secrets_client()

        save_broker_secret("google|user:1", "Alpaca", "secret-value")

        put_item.assert_not_called()


class BrokerSecretReadTests(unittest.TestCase):
    ## A current pointer is read straight from Secrets Manager.
    @patch("backend.users.secrets._secrets_client")
    def test_reads_a_secrets_manager_pointer(self, client_factory):
        client = Mock()
        client.get_secret_value.return_value = {"SecretString": "secret-value"}
        client_factory.return_value = client

        value = get_broker_secret("arn:aws:secretsmanager:us-east-1:1:secret:helios/users/u/alpaca-a")

        self.assertEqual(value, "secret-value")

    ## A profile saved before the move keeps working until it is migrated.
    @patch("backend.users.secrets.get_item", return_value={"secret_key": "old-value"})
    def test_reads_a_pointer_written_before_the_move(self, get_item):
        value = get_broker_secret("dynamodb://USER_SECRET#google_user-1/BROKER#alpaca")

        self.assertEqual(value, "old-value")
        get_item.assert_called_once_with("USER_SECRET#google_user-1", "BROKER#alpaca")

    ## A missing secret is reported rather than returned as an empty credential.
    @patch("backend.users.secrets._secrets_client")
    def test_missing_secret_raises(self, client_factory):
        client = Mock()
        client.get_secret_value.return_value = {}
        client_factory.return_value = client

        with self.assertRaisesRegex(ValueError, "not found"):
            get_broker_secret("arn:aws:secretsmanager:us-east-1:1:secret:helios/users/u/alpaca-a")


class ProfileExposureTests(unittest.TestCase):
    ## The browser is told whether a broker is connected, never where the secret is or what it says.
    def test_public_profile_hides_the_secret_and_its_location(self):
        profile = public_profile({
            "user_id": "google-user-1",
            "email": "user@example.com",
            "broker": "alpaca",
            "broker_api_key": "PK-VISIBLE",
            "broker_secret_ref": "arn:aws:secretsmanager:us-east-1:1:secret:helios/users/u/alpaca-a",
        })

        self.assertTrue(profile["broker_connected"])
        for value in profile.values():
            self.assertNotIn("secretsmanager", str(value))
        self.assertNotIn("broker_secret_ref", profile)

    ## A profile whose secret reference predates the pointer field is treated as not connected.
    def test_profile_without_a_secret_reference_is_not_connected(self):
        profile = public_profile({
            "user_id": "google-user-1",
            "email": "user@example.com",
            "broker": "alpaca",
            "broker_secret_arn": "arn:aws:secretsmanager:legacy",
        })

        self.assertFalse(profile["broker_connected"])


if __name__ == "__main__":
    unittest.main()
