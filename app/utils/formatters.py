from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation


def safe_name(value: str) -> str:
    cleaned = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^\w\s.-]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.replace(" ", "_") or "SEM_NOME"


def decimal_from_str(value: str | None, default: str = "0.00") -> Decimal:
    if value is None:
        return Decimal(default)
    text = value.strip()
    if not text:
        return Decimal(default)
    text = text.replace(" ", "")
    if "," in text:
        text = text.replace(".", "")
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Valor numerico invalido: {value}") from exc


def build_client_block(client: object) -> str:
    lines: list[str] = []
    razao_social = str(getattr(client, "razao_social", "")).strip()
    if razao_social:
        lines.append(razao_social)

    cnpj = str(getattr(client, "cnpj", "")).strip()
    if cnpj:
        lines.append(f"CNPJ: {cnpj}")

    end1 = str(getattr(client, "endereco_linha1", "")).strip()
    end2 = str(getattr(client, "endereco_linha2", "")).strip()
    if end1:
        lines.append(end1)
    if end2:
        lines.append(end2)

    cep = str(getattr(client, "cep", "")).strip()
    cidade_uf = str(getattr(client, "cidade_uf", "")).strip()
    if cep and cidade_uf:
        lines.append(f"CEP: {cep} {cidade_uf}")
    elif cep:
        lines.append(f"CEP: {cep}")
    elif cidade_uf:
        lines.append(cidade_uf)

    pais = str(getattr(client, "pais", "")).strip() or "Brasil"
    lines.append(pais)

    caixa_postal = str(getattr(client, "caixa_postal", "")).strip()
    if caixa_postal:
        lines.append(f"Caixa Postal: {caixa_postal}")

    telefone = str(getattr(client, "telefone", "")).strip()
    site = str(getattr(client, "site", "")).strip()
    if telefone:
        lines.append(f"Telefone: {telefone}")
    if site:
        lines.append(site)

    return "\n".join(line for line in lines if line)
