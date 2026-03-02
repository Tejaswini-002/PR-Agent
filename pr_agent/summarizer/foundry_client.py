import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from openai import OpenAI

from pr_agent.config import Config


class FoundryClient:
    def __init__(self, config: Config) -> None:
        api_key = config.foundry_api_key or "not-needed"
        self._client = OpenAI(
            base_url=config.foundry_base_url,
            api_key=api_key,
            timeout=None,  # No client-side timeout; wait for Azure Foundry response
        )
        self._model = config.foundry_model

    def _create_chat_json(self, prompt: dict[str, Any], model: str) -> dict[str, Any]:
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=prompt["messages"],
                temperature=0,
                top_p=1,
                max_tokens=1400,
                response_format={"type": "json_object"},
            )
        except Exception:  # noqa: BLE001
            response = self._client.chat.completions.create(
                model=model,
                messages=prompt["messages"],
                temperature=0,
                top_p=1,
                max_tokens=1400,
            )
        content = response.choices[0].message.content or ""
        cleaned = self._strip_code_fences(content)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            snippet = self._extract_json_object(cleaned)
            if snippet:
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    pass
            return {"summary": [content]}

    def chat_json(self, prompt: dict[str, Any], *, model: str | None = None) -> dict[str, Any]:
        chosen_model = model or self._model
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._create_chat_json, prompt, chosen_model)
            return future.result()
        finally:
            executor.shutdown(wait=False)

    def chat_text(self, prompt: dict[str, Any], *, model: str | None = None) -> str:
        chosen_model = model or self._model

        def _call() -> str:
            response = self._client.chat.completions.create(
                model=chosen_model,
                messages=prompt["messages"],
                temperature=0,
                top_p=1,
                max_tokens=1200,
            )
            return response.choices[0].message.content or ""

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_call)
            return future.result()
        finally:
            executor.shutdown(wait=False)

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3:
                return "\n".join(lines[1:-1]).strip()
            return stripped.strip("`")
        return stripped

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return text[start : end + 1]
