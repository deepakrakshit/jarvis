from __future__ import annotations


class STTPlaceholder:
    """Future Speech-to-Text backend abstraction point.

    Browser-side Web Speech API currently provides live STT for GUI mode.
    """

    def transcribe(self, _audio_chunk: bytes) -> str:
        raise NotImplementedError("STT backend not wired in Python yet.")
