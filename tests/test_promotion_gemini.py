from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.config import Settings
from app.services.promotion_generation_service import (
    GeminiPromotionGenerator,
    PromotionGenerationError,
    PROMOTION_IMAGE_BASE_PROMPT,
    PROMOTION_MARKETING_BASE_PROMPT,
)

_PNG = b"\x89PNG\r\n\x1a\n" + (b"synthetic-image" * 6)


def test_text_generation_uses_base_prompt_configured_text_model_and_no_invented_claims():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps({"subject": "Conheça a AD Balanças", "body": "Entre em contato e agende uma conversa para conhecer nossas soluções. Consulte condições especiais."})}]}}]},
        )

    settings = Settings(gemini_api_key="synthetic-key", gemini_model="text-synthetic", gemini_image_model="image-synthetic")
    generator = GeminiPromotionGenerator(settings, transport=httpx.MockTransport(handler))

    result = generator.generate_copy("Convide clientes a conhecer nossos serviços.")

    assert result.subject == "Conheça a AD Balanças"
    assert captured["url"].endswith("/models/text-synthetic:generateContent")
    payload = captured["payload"]
    assert PROMOTION_MARKETING_BASE_PROMPT in payload["systemInstruction"]["parts"][0]["text"]
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


def test_text_generation_rejects_unprovided_price_or_percentage():
    generator = GeminiPromotionGenerator(
        Settings(gemini_api_key="synthetic-key"),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": json.dumps({"subject": "Desconto de 20%", "body": "Economize R$ 100. Consulte condições especiais."})}]}}]},
            )
        ),
    )

    with pytest.raises(PromotionGenerationError) as error:
        generator.generate_copy("Convide para uma conversa sobre serviços técnicos.")

    assert error.value.code == "unsupported_commercial_claim"
    assert "R$ 100" not in str(error.value)


def test_missing_gemini_key_keeps_error_clear_without_disclosing_any_secret():
    generator = GeminiPromotionGenerator(Settings(gemini_api_key=""))

    with pytest.raises(PromotionGenerationError, match="GEMINI_API_KEY"):
        generator.generate_copy("Descrição sintética")


def test_approximate_period_is_optional_and_must_not_be_added_by_model():
    accepted = GeminiPromotionGenerator(
        Settings(gemini_api_key="synthetic-key"),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": json.dumps({"subject": "Serviços para sua empresa", "body": "Na próxima semana, fale conosco e agende uma conversa sobre serviços."})}]}}]},
            )
        ),
    )
    assert "próxima semana" in accepted.generate_copy("Convide para conversar na próxima semana.").body

    invented_period = GeminiPromotionGenerator(
        Settings(gemini_api_key="synthetic-key"),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": json.dumps({"subject": "Convite", "body": "Aproveite durante esta semana; fale conosco e agende."})}]}}]},
            )
        ),
    )
    with pytest.raises(PromotionGenerationError) as error:
        invented_period.generate_copy("Convide para conhecer nossos serviços, sem período definido.")
    assert error.value.code == "unsupported_period_claim"


def test_image_generation_uses_separate_configured_model_and_optional_reference():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"output_image": {"mime_type": "image/png", "data": base64.b64encode(_PNG).decode()}})

    generator = GeminiPromotionGenerator(
        Settings(gemini_api_key="synthetic-key", gemini_model="text-model", gemini_image_model="image-model"),
        transport=httpx.MockTransport(handler),
    )
    image = generator.generate_image("Imagem industrial sintética.", reference_image=_PNG, reference_mime="image/png")

    assert image.data == _PNG
    assert captured["url"].endswith("/v1beta/interactions")
    assert captured["payload"]["model"] == "image-model"
    assert captured["payload"]["input"][0]["text"].startswith(PROMOTION_IMAGE_BASE_PROMPT)
    assert captured["payload"]["input"][1]["mime_type"] == "image/png"


@pytest.mark.parametrize(
    ("http_status", "expected_code"),
    [(401, "text_unauthorized"), (404, "text_model_unavailable"), (429, "text_rate_limited"), (503, "text_provider_unavailable")],
)
def test_gemini_provider_errors_are_classified_without_body_leak(http_status, expected_code):
    generator = GeminiPromotionGenerator(
        Settings(gemini_api_key="synthetic-key"),
        transport=httpx.MockTransport(lambda _request: httpx.Response(http_status, text="synthetic private provider body")),
    )

    with pytest.raises(PromotionGenerationError) as error:
        generator.generate_copy("Descrição sintética sem dados comerciais.")

    assert error.value.code == expected_code
    assert "synthetic private provider body" not in str(error.value)
