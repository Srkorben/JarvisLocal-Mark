import os
import uuid
from unittest import TestCase, skipUnless

from jarvis_local.process_lock import windows_singleton


@skipUnless(os.name == "nt", "El mutex nominal se valida solamente en Windows")
class WindowsSingletonTests(TestCase):
    def test_second_owner_is_rejected_until_first_releases(self) -> None:
        name = rf"Local\MarkScout.Tests.{uuid.uuid4()}"
        with windows_singleton(name) as first:
            self.assertTrue(first)
            with windows_singleton(name) as second:
                self.assertFalse(second)
        with windows_singleton(name) as after_release:
            self.assertTrue(after_release)
