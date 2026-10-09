from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

CapabilityState = Literal["not_implemented", "not_configured", "available", "unavailable"]


class Capability(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    state: CapabilityState
    read_only: bool = False
    detail: str


class CapabilityRegistry:
    """Single source of truth for operations the assistant may claim to perform."""

    def __init__(self, *, email_provider: str = "disabled") -> None:
        email_state: CapabilityState = (
            "not_configured" if email_provider == "disabled" else "available"
        )
        self._capabilities = {
            "task_read": Capability(
                name="task_read", state="available", read_only=True, detail="Consulta o quadro local."
            ),
            "task_create": Capability(
                name="task_create", state="available", detail="Cria tarefa somente apos confirmacao."
            ),
            "email_read": Capability(
                name="email_read",
                state=email_state,
                read_only=True,
                detail=(
                    "Leitura de e-mail desativada por configuracao."
                    if email_state == "not_configured"
                    else "Leitura de e-mail somente leitura."
                ),
            ),
            "email_send": Capability(
                name="email_send", state="not_implemented", detail="Envio de e-mail nao implementado."
            ),
            "finance_read": Capability(
                name="finance_read", state="not_implemented", read_only=True, detail="Consulta financeira nao implementada."
            ),
            "finance_write": Capability(
                name="finance_write", state="not_implemented", detail="Alteracao financeira nao implementada."
            ),
            "document_write": Capability(
                name="document_write", state="available", detail="Relatório técnico de serviço concluído, com prévia e confirmação explícita."
            ),
            "service_write": Capability(
                name="service_write", state="available", detail="Registra eventos e lembretes de servico somente apos confirmacao."
            ),
            "service_read": Capability(
                name="service_read", state="available", read_only=True, detail="Consulta chamados e etapas de servico locais."
            ),
            "tax_issue": Capability(
                name="tax_issue", state="not_implemented", detail="Emissao fiscal nao implementada."
            ),
        }

    def get(self, name: str) -> Capability:
        return self._capabilities[name]

    def provider_context(self) -> list[dict[str, object]]:
        return [item.model_dump(mode="json") for item in self._capabilities.values()]
