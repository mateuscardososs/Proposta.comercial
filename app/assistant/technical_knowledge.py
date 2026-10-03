from __future__ import annotations

from dataclasses import dataclass

from app.assistant.dates import normalize_text


@dataclass(frozen=True)
class TechnicalReference:
    topic: str
    triggers: tuple[str, ...]
    facts: tuple[str, ...]
    source_title: str
    source_url: str


REFERENCES = (
    TechnicalReference(
        topic="tara",
        triggers=("tara", "peso liquido", "peso bruto"),
        facts=(
            "Valor bruto e a indicacao da carga sem dispositivo de tara em operacao.",
            "Valor liquido e a indicacao da carga depois da operacao do dispositivo de tara.",
            "A tara e o valor da carga determinado por um dispositivo de pesagem de tara.",
        ),
        source_title="OIML R 76-1, secoes T.5.2.1 a T.5.2.3",
        source_url="https://www.oiml.org/en/files/pdf_r/r076-1-e06.pdf",
    ),
    TechnicalReference(
        topic="calibracao-verificacao",
        triggers=("calibracao", "calibrar", "verificacao", "verificar"),
        facts=(
            "Calibracao estabelece, sob condicoes especificadas, a relacao entre valores e incertezas fornecidos por padroes e as indicacoes correspondentes.",
            "Verificacao fornece evidencia objetiva de que um item satisfaz requisitos especificados.",
            "Calibracao nao significa necessariamente ajustar o instrumento; verificacao nao deve ser confundida com calibracao.",
        ),
        source_title="Inmetro, diferenca entre calibracao e verificacao, baseado no VIM",
        source_url="https://www.gov.br/inmetro/pt-br/acesso-a-informacao/perguntas-frequentes/acreditacao/qual-a-diferenca-de-calibracao-e-verificacao",
    ),
)


def references_for(message: str) -> list[dict[str, object]]:
    normalized = normalize_text(message)
    selected = []
    for reference in REFERENCES:
        if any(trigger in normalized for trigger in reference.triggers):
            selected.append(
                {
                    "topic": reference.topic,
                    "facts": list(reference.facts),
                    "source_title": reference.source_title,
                    "source_url": reference.source_url,
                }
            )
    return selected
