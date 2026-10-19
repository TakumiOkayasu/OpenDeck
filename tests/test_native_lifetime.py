import subprocess
import sys
from textwrap import dedent

import pytest


@pytest.mark.parametrize("operation", ["close", "start", "failure", "overflow"])
def test_discarded_payload_finalizer_can_reenter_source(operation: str):
    code = dedent(
        """
        import sys

        from opendeck.source import Source

        source = Source[object](capacity=1)
        source.start()
        finalized = []

        def discard():
            match sys.argv[1]:
                case "close":
                    source.close()
                case "start":
                    source.start()
                case "failure":
                    source.fail("input failure")
                case "overflow":
                    assert not source.publish(object())

        class Payload:
            def __del__(self):
                finalized.append(True)
                discard()

        assert source.publish(Payload())
        discard()
        assert finalized == [True]
        source.close()
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, operation],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
