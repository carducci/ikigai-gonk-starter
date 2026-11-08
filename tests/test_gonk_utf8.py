"""ikigai's replies are UTF-8 on every platform (carducci#101, 2026-11-08).

On Windows, text=True alone decodes with the locale's code page (cp1252), so a brief holding an
arrow or an em dash came back changed, digested differently from the dispatch's pinned sha256, and
every such dispatch was refused as "changed after its dispatch". The worker must decode and encode
ikigai's streams as UTF-8 whatever the locale.
"""

from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from support import gonk


class Utf8Streams(unittest.TestCase):
    def test_ikigai_is_run_with_utf8_streams_whatever_the_locale(self):
        done = subprocess.CompletedProcess([], 0, stdout="→ — ok", stderr="")
        with mock.patch.object(gonk.subprocess, "run", return_value=done) as run:
            answer = gonk.Ikigai(gonk.Target(socket="/s/gonk.sock")).run("x", stdin="→")
        self.assertEqual("utf-8", run.call_args.kwargs.get("encoding"))
        self.assertEqual("→ — ok", answer.out)


if __name__ == "__main__":
    unittest.main()
