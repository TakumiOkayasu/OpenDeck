import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("capability", ["read", "input", "subject"])
def test_capability_view_rejects_none_without_crashing(capability):
    script = textwrap.dedent(
        f"""
        from opendeck import {capability}_view

        try:
            {capability}_view(None)
        except TypeError:
            pass
        else:
            raise AssertionError('None must be rejected when the view is created')
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_subject_removal_remains_effective_after_concurrent_registration():
    script = textwrap.dedent(
        """
        import sys
        from threading import Barrier, Thread

        from opendeck import _native as core

        class Observer:
            def on_change(self):
                pass

        previous = sys.getswitchinterval()
        sys.setswitchinterval(0.000001)
        try:
            for attempt in range(64):
                panel = core.Panel(['primary'], [], 1)
                panel.start()
                subject = core.subject_view(panel.buttons['primary'])
                observer = Observer()
                subject.add(observer)
                barrier = Barrier(3)

                def register():
                    barrier.wait()
                    for _ in range(4000):
                        subject.add(observer)

                def unregister():
                    barrier.wait()
                    for _ in range(4000):
                        subject.remove(observer)

                workers = [Thread(target=register), Thread(target=unregister)]
                for worker in workers:
                    worker.start()
                barrier.wait()
                for worker in workers:
                    worker.join()

                subject.remove(observer)
                accepted, notifications = panel.receive('primary', True, 1.0)
                assert accepted
                assert not notifications, (
                    f'removed observer retained after attempt {attempt}: '
                    f'{len(notifications)} registrations'
                )
        finally:
            sys.setswitchinterval(previous)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
