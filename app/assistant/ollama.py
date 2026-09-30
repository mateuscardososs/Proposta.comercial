from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from datetime import date
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from app.assistant.contracts import AssistantCommand, assistant_command_adapter
from app.assistant.provider import ProviderMessage, ProviderResponseError, ProviderUnavailableError


LOCAL_OLLAMA_HOSTS = {"127.0.0.1", "localhost", "::1", "host.docker.internal"}
OLLAMA_INFERENCE_LOCK = threading.BoundedSemaphore(value=1)


class OllamaProvider:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        connect_timeout: float,
        read_timeout: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in LOCAL_OLLAMA_HOSTS:
            raise ValueError("O endereco do Ollama deve apontar para um host local permitido.")
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=read_timeout,
            pool=connect_timeout,
        )
        self.transport = transport

    def interpret(
        self,
        messages: Sequence[ProviderMessage],
        *,
        today: date,
        timezone: str,
    ) -> AssistantCommand:
        if not self.model:
            raise ProviderUnavailableError(
                "Ollama esta configurado, mas nenhum modelo foi definido em OLLAMA_MODEL."
            )

        system_message = ProviderMessage(
            role="system",
            content=(
                "Voce interpreta pedidos operacionais em portugues. "
                "Use somente uma destas ferramentas: consultar_tarefas, criar_tarefa ou fora_do_escopo. "
                "Nunca invente identificadores. Preserve nomes como foram falados. "
                f"Hoje e {today.isoformat()} no fuso {timezone}. "
                "Datas relativas podem permanecer em portugues para validacao pelo sistema. "
                "Retorne apenas o objeto estruturado solicitado, sem raciocinio interno."
            ),
        )
        payload = {
            "model": self.model,
            "messages": [
                item.model_dump()
                for item in [system_message, *messages]
            ],
            "stream": False,
            "format": assistant_command_adapter.json_schema(),
            "options": {"temperature": 0},
        }

        try:
            with OLLAMA_INFERENCE_LOCK:
                with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                    response = client.post(f"{self.base_url}/api/chat", json=payload)
                    response.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ProviderUnavailableError(
                "Ollama nao esta disponivel no endereco configurado."
            ) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                message = "O modelo configurado nao esta disponivel no Ollama."
            else:
                message = "O Ollama respondeu com erro ao interpretar a mensagem."
            raise ProviderUnavailableError(message) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("Falha de comunicacao com o Ollama.") from exc

        try:
            content = response.json()["message"]["content"]
            decoded = json.loads(content)
            return assistant_command_adapter.validate_python(decoded)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            raise ProviderResponseError(
                "O Ollama retornou uma resposta que nao passou na validacao."
            ) from exc
