"""Gemini API istemcisi.

google-genai (yeni, birleşik SDK) kullanır - eski google-generativeai paketi
artık desteklenmiyor. response_mime_type="application/json" ile modeli
doğrudan geçerli JSON döndürmeye zorluyoruz; bu, kod fence'i temizlemekten
(```json ... ```) çok daha güvenilir.
"""
from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from .. import config

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY tanımlı değil (.env dosyasını kontrol edin)")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


class LLMJSONError(RuntimeError):
    """Model JSON döndürmedi ya da beklenen alanlar eksik."""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
def call_json(
    model: str,
    system_instruction: str,
    user_content: str,
    max_output_tokens: int = 2048,
    temperature: float = 0.1,
) -> dict[str, Any]:
    """Modeli çağırır, yanıtı JSON olarak parse edip sözlük döner.

    Emin olunamayan alanlar için modelden None + "reason" döndürmesi istenir
    (bkz. system prompt'lardaki talimat) - burada ekstra bir uydurma-önleme
    katmanı yok, o disiplin prompt seviyesinde sağlanıyor.
    """
    client = _get_client()
    response = client.models.generate_content(
        model=model,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise LLMJSONError(f"Model boş yanıt döndürdü (model={model})")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMJSONError(f"Model geçerli JSON döndürmedi: {text[:300]}") from exc
