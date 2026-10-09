"""Translation-input draft state, independent of Tk and Windows."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PreviewRequest:
    serial: int
    revision: int
    text: str
    session: object
    context: str


class InputDraft:
    def __init__(self):
        self.source = ""
        self.revision = 0
        self.serial = 0
        self.pending = None
        self.ready = None
        self.result = None

    def edit(self, text):
        text = (text or "").strip()
        if text == self.source:
            return False
        self.source = text
        self.revision += 1
        self.discard()
        return True

    def discard(self):
        self.pending = self.ready = self.result = None

    def begin(self, session, context):
        if not self.source:
            raise ValueError("先写一句要翻译的话")
        self.serial += 1
        request = PreviewRequest(self.serial, self.revision, self.source, session, context)
        self.pending = request
        self.ready = self.result = None
        return request

    def accept(self, request, result, session, context):
        if (self.pending is not request or request.revision != self.revision
                or request.text != self.source or request.session is not session
                or request.context != context):
            if self.pending is request:
                self.pending = None
            return False
        self.pending = None
        if not result.get("text", "").strip():
            return False
        self.ready, self.result = request, dict(result)
        return True

    def can_insert(self, session, context):
        request = self.ready
        return bool(self.result and request and request.revision == self.revision
                    and request.text == self.source and request.session is session
                    and request.context == context)
