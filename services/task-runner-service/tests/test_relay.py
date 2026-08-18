from __future__ import annotations

from task_runner_service.relay import OutputRelay
from task_runner_service.sandbox import OutputChunk

STEP = "step-1"

SNOWMAN = "☃".encode()


class Recorder:
    def __init__(self) -> None:
        self.chunks: list[OutputChunk] = []

    async def emit(self, chunk: OutputChunk) -> None:
        self.chunks.append(chunk)


def relay(max_bytes: int = 1024) -> tuple[OutputRelay, Recorder]:
    recorder = Recorder()

    return OutputRelay(STEP, recorder, max_bytes), recorder


async def test_a_chunk_carries_its_step_and_stream() -> None:
    subject, recorder = relay()

    await subject.write("stdout", b"hello")

    assert recorder.chunks[0] == OutputChunk(
        step_id=STEP, stream="stdout", sequence=0, text="hello"
    )


async def test_an_empty_write_emits_nothing() -> None:
    subject, recorder = relay()

    await subject.write("stdout", b"")

    assert recorder.chunks == []
    assert subject.bytes_written == 0


async def test_sequence_is_shared_across_both_streams() -> None:
    subject, recorder = relay()

    await subject.write("stdout", b"one")
    await subject.write("stderr", b"two")
    await subject.write("stdout", b"three")

    assert [chunk.sequence for chunk in recorder.chunks] == [0, 1, 2]
    assert [chunk.stream for chunk in recorder.chunks] == ["stdout", "stderr", "stdout"]


async def test_output_within_budget_is_not_truncated() -> None:
    subject, _ = relay(max_bytes=10)

    await subject.write("stdout", b"0123456789")

    assert subject.bytes_written == 10
    assert not subject.truncated


async def test_output_beyond_budget_is_cut_and_flagged() -> None:
    subject, recorder = relay(max_bytes=4)

    await subject.write("stdout", b"0123456789")

    assert subject.truncated
    assert subject.bytes_written == 4
    assert recorder.chunks[0].text == "0123"


async def test_writes_after_the_budget_is_spent_emit_nothing() -> None:
    subject, recorder = relay(max_bytes=4)

    await subject.write("stdout", b"0123")
    await subject.write("stdout", b"4567")

    assert len(recorder.chunks) == 1
    assert subject.bytes_written == 4
    assert subject.truncated


async def test_the_budget_is_shared_across_both_streams() -> None:
    subject, _ = relay(max_bytes=6)

    await subject.write("stdout", b"abc")
    await subject.write("stderr", b"defgh")

    assert subject.bytes_written == 6
    assert subject.truncated


async def test_a_character_split_across_two_writes_is_reassembled() -> None:
    subject, recorder = relay()

    await subject.write("stdout", SNOWMAN[:1])
    await subject.write("stdout", SNOWMAN[1:])

    assert "".join(chunk.text for chunk in recorder.chunks) == "☃"


async def test_each_stream_decodes_independently() -> None:
    subject, recorder = relay()

    await subject.write("stdout", SNOWMAN[:2])
    await subject.write("stderr", b"plain")
    await subject.write("stdout", SNOWMAN[2:])

    assert [chunk.text for chunk in recorder.chunks] == ["plain", "☃"]


async def test_a_character_cut_by_truncation_is_flushed_on_close() -> None:
    subject, recorder = relay(max_bytes=2)

    await subject.write("stdout", SNOWMAN)
    await subject.close()

    assert subject.truncated
    assert "".join(chunk.text for chunk in recorder.chunks) == "�"


async def test_close_emits_nothing_when_no_bytes_are_held() -> None:
    subject, recorder = relay()

    await subject.write("stdout", b"complete")
    await subject.close()

    assert len(recorder.chunks) == 1


async def test_close_is_safe_on_an_untouched_relay() -> None:
    subject, recorder = relay()

    await subject.close()

    assert recorder.chunks == []
    assert subject.emitted == 0
