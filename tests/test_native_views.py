from opendeck import Input, Observer, Read, Subject, input_view, read_view, subject_view


def test_read_view_accepts_a_contract_implementation_without_a_device():
    class Current(Read[str]):
        def read(self):
            return "available"

        def reset(self):
            raise AssertionError("not part of the supplied capability")

    state = read_view(Current())
    assert state.read() == "available"
    assert not hasattr(state, "reset")
    assert not hasattr(state, "take")


def test_input_view_preserves_the_generic_input_value():
    class Bytes(Input[bytes]):
        def take(self):
            return b"payload"

    input = input_view(Bytes())
    assert input.take() == b"payload"
    assert not hasattr(input, "read")
    assert not hasattr(input, "publish")


def test_subject_view_accepts_an_independent_subject_implementation():
    calls = []

    class Target(Subject):
        def add(self, observer):
            calls.append(("add", observer))

        def remove(self, observer):
            calls.append(("remove", observer))

        def trigger(self):
            raise AssertionError("not part of the supplied capability")

    class Listener(Observer):
        def on_change(self):
            pass

    subject = subject_view(Target())
    observer = Listener()
    subject.add(observer)
    subject.remove(observer)
    assert calls == [("add", observer), ("remove", observer)]
    assert not hasattr(subject, "trigger")
    assert not hasattr(subject, "take")
