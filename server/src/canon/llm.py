"""The model calls Canon makes at answer time, behind one small interface so tests can pass stubs.

A model only ever returns JSON in a schema we give it. It drafts sentences from facts and checks that a sentence
says what its facts say; it never decides what is current, disputed or owned.
"""

import json
from typing import Protocol

import anthropic

from canon.config import settings


class JsonModel(Protocol):
    async def json(self, system: str, prompt: str, schema: dict) -> dict: ...


class ModelError(RuntimeError):
    pass


class Claude:
    def __init__(self, model: str, *, effort: str, max_tokens: int = 16000, client=None):
        self.model, self.effort, self.max_tokens = model, effort, max_tokens
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.AsyncAnthropic()
        return self._client

    async def json(self, system: str, prompt: str, schema: dict) -> dict:
        # Streamed so a long think never trips the SDK's non-streaming time guard.
        async with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
        ) as stream:
            message = await stream.get_final_message()
        if message.stop_reason in ("refusal", "max_tokens"):
            raise ModelError(f"{self.model} stopped early: {message.stop_reason}")
        text = next((b.text for b in message.content if b.type == "text"), "")
        return json.loads(text)


def answer_model() -> Claude:
    return Claude(settings().answer_model, effort="high", max_tokens=32000)


def check_model() -> Claude:
    return Claude(settings().extract_model, effort="low", max_tokens=4000)
