import pytest

import opendeck


def test_view_contract_allows_a_consumer_to_draw_opaque_image_bytes():
    calls: list[bytes] = []

    class RecordingView(opendeck.View):
        def draw(self, image: bytes) -> None:
            calls.append(image)

    def draw(view: opendeck.View, image: bytes) -> None:
        view.draw(image)

    image = b"\x89PNG\x00\xff"
    draw(RecordingView(), image)
    assert calls == [image]
    with pytest.raises(TypeError):
        opendeck.View()
