from __future__ import annotations

import codecs
from typing import Final

from task_runner_service.sandbox import OutputChunk, OutputSink, OutputStream

STREAMS: Final[tuple[OutputStream, ...]] = ("stdout", "stderr")


class OutputRelay:
    def __init__(self, step_id: str, sink: OutputSink, max_bytes: int) -> None:
        self._step_id = step_id
        self._sink = sink
        self._max_bytes = max_bytes
        self._consumed = 0
        self._truncated = False
        self._sequence = 0
        self._decoders: dict[OutputStream, codecs.IncrementalDecoder] = {
            name: codecs.getincrementaldecoder("utf-8")("replace") for name in STREAMS
        }

    @property
    def step_id(self) -> str:
        return self._step_id

    @property
    def bytes_written(self) -> int:
        return self._consumed

    @property
    def truncated(self) -> bool:
        return self._truncated

    @property
    def emitted(self) -> int:
        return self._sequence

    def allowance(self, size: int) -> int:
        remaining = self._max_bytes - self._consumed

        if size <= remaining:
            return size

        self._truncated = True

        return max(remaining, 0)

    async def emit(self, stream: OutputStream, text: str) -> None:
        chunk = OutputChunk(
            step_id=self._step_id,
            stream=stream,
            sequence=self._sequence,
            text=text,
        )
        self._sequence += 1

        await self._sink.emit(chunk)

    async def write(self, stream: OutputStream, data: bytes) -> None:
        if not data:
            return

        allowed = self.allowance(len(data))

        if allowed == 0:
            return

        self._consumed += allowed
        text = self._decoders[stream].decode(data[:allowed])

        if text:
            await self.emit(stream, text)

    async def close(self) -> None:
        for stream in STREAMS:
            text = self._decoders[stream].decode(b"", final=True)

            if text:
                await self.emit(stream, text)
