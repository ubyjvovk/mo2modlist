import os
import unittest
import uuid
from unittest.mock import patch

from mo2_modlists import credentials


@unittest.skipUnless(os.name == "nt", "Windows Credential Manager integration")
class CredentialTests(unittest.TestCase):
    def test_isolated_credential_roundtrip_and_removal(self):
        target = "MO2Modlists-Test/" + uuid.uuid4().hex
        with patch.dict(credentials.TARGETS, {"test": target}):
            try:
                self.assertIsNone(credentials.read("test"))
                credentials.save("test", "fixture-not-a-real-provider-key")
                self.assertEqual(credentials.read("test"), "fixture-not-a-real-provider-key")
                credentials.remove("test")
                self.assertIsNone(credentials.read("test"))
            finally:
                credentials.remove("test")
