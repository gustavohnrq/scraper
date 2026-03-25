from __future__ import annotations

import re
from dataclasses import dataclass


SUITE_PATTERNS = [r"\bsuite\b", r"\bsuites\b", r"\bsu[ií]te\b"]
BANHEIRO_COMPLETO_PATTERNS = [r"banheiro social", r"wc social", r"banheiro completo", r"dois banheiros"]
LAVABO_PATTERN = r"\blavabo\b"
AMBIGUOUS_PATTERNS = [r"dce convert", r"adaptad", r"revers[ií]vel", r"podendo virar quarto"]


@dataclass
class InferenceResult:
    suite_confirmada: bool
    banheiro_completo_confirmado: bool
    vaga_confirmada: bool
    metragem_confirmada: bool
    alerta_ambiguo: bool
    observacoes: list[str]


def infer_listing(
    texto_norm: str,
    suites: float | None,
    banheiros: float | None,
    vagas: float | None,
    metragem: float | None,
) -> InferenceResult:
    obs: list[str] = []

    suite_confirmada = bool((suites or 0) >= 1) or any(re.search(p, texto_norm) for p in SUITE_PATTERNS)

    has_lavabo = re.search(LAVABO_PATTERN, texto_norm) is not None
    banheiro_confirmado_texto = any(re.search(p, texto_norm) for p in BANHEIRO_COMPLETO_PATTERNS)
    if banheiro_confirmado_texto:
        banheiro_completo_confirmado = True
    elif has_lavabo:
        banheiro_completo_confirmado = False
        obs.append("Há lavabo, mas sem confirmação de banheiro social completo.")
    else:
        banheiro_completo_confirmado = False
        if banheiros and banheiros >= 2:
            obs.append("Quantidade de banheiros informada sem contexto de banheiro social completo.")

    vaga_confirmada = bool((vagas or 0) >= 1) or ("vaga" in texto_norm)
    metragem_confirmada = metragem is not None and metragem > 0

    alerta_ambiguo = any(re.search(p, texto_norm) for p in AMBIGUOUS_PATTERNS)
    if alerta_ambiguo:
        obs.append("Anúncio com sinais de ambiguidade (DCE/adaptação/planta reversível).")

    return InferenceResult(
        suite_confirmada=suite_confirmada,
        banheiro_completo_confirmado=banheiro_completo_confirmado,
        vaga_confirmada=vaga_confirmada,
        metragem_confirmada=metragem_confirmada,
        alerta_ambiguo=alerta_ambiguo,
        observacoes=obs,
    )
