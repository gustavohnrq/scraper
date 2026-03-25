from __future__ import annotations

from dataclasses import dataclass

from .parser_utils import normalize_text
from .profile_schema import ClientProfile
from .rules import infer_listing


@dataclass
class ScoreResult:
    score: float
    mandatory_ok: bool
    pontos_aderencia: list[str]
    pontos_atencao: list[str]
    motivo: str
    inferencias: dict[str, bool]
    trecho_descricao: str
    motivo_descarte: str | None = None


def _price_score(price: float | None, profile: ClientProfile) -> tuple[float, bool, str]:
    if price is None:
        return 0, False, "Preço não informado"
    if profile.preco_min and price < profile.preco_min:
        return 20, False, "Abaixo da faixa"
    if price <= profile.preco_max:
        return 100, True, "Dentro da faixa"
    overflow = (price - profile.preco_max) / max(profile.preco_max, 1)
    if overflow <= 0.07:
        return 70, False, "Levemente acima da faixa"
    return max(0, 40 - overflow * 100), False, "Acima da faixa"


def _rooms_match(q: float | None, profile: ClientProfile) -> tuple[float, bool, str]:
    if q is None:
        return 0, False, "Quartos não informados"
    qi = int(q)
    if profile.quartos_exatos is not None:
        if qi == profile.quartos_exatos:
            return 100, True, "Quartos exatos"
        if abs(qi - profile.quartos_exatos) == 1:
            return 50, False, "Quartos próximos"
        return 0, False, "Quartos fora do perfil"
    if profile.quartos_min is not None and qi >= profile.quartos_min:
        return 100, True, "Quartos mínimos atendidos"
    return 0, False, "Abaixo do mínimo de quartos"


def _region_score(region: str, profile: ClientProfile) -> tuple[float, bool, str]:
    r = normalize_text(region)
    prioridades = [normalize_text(x) for x in profile.regioes_prioritarias]
    aceitaveis = [normalize_text(x) for x in profile.regioes_aceitaveis]
    if r in prioridades:
        return 100, True, "Região prioritária"
    if r in aceitaveis:
        return 75, True, "Região aceitável"
    return 20, False, "Fora das regiões alvo"


def score_listing(row: dict, profile: ClientProfile) -> ScoreResult:
    infer = infer_listing(
        texto_norm=row.get("texto_total_norm", ""),
        suites=row.get("suites"),
        banheiros=row.get("banheiros"),
        vagas=row.get("vagas"),
        metragem=row.get("metragem"),
    )

    aderencia: list[str] = []
    atencao: list[str] = infer.observacoes.copy()

    s_price, ok_price, m_price = _price_score(row.get("preco"), profile)
    s_region, ok_region, m_region = _region_score(str(row.get("regiao", "")), profile)
    s_rooms, ok_rooms, m_rooms = _rooms_match(row.get("quartos"), profile)

    if ok_price:
        aderencia.append(m_price)
    else:
        atencao.append(m_price)

    if ok_region:
        aderencia.append(m_region)
    else:
        atencao.append(m_region)

    if ok_rooms:
        aderencia.append(m_rooms)
    else:
        atencao.append(m_rooms)

    mandatory_ok = ok_price and ok_region and ok_rooms

    s_suite = 100 if infer.suite_confirmada else 20
    if profile.suite_obrigatoria and not infer.suite_confirmada:
        atencao.append("Suíte obrigatória não confirmada")
        mandatory_ok = False

    s_ban = 100 if infer.banheiro_completo_confirmado else 25
    if profile.segundo_banheiro_completo_obrigatorio and not infer.banheiro_completo_confirmado:
        atencao.append("2º banheiro completo obrigatório não confirmado")
        mandatory_ok = False

    s_vaga = 100 if infer.vaga_confirmada else 20
    if profile.vaga_obrigatoria and not infer.vaga_confirmada:
        atencao.append("Vaga obrigatória não confirmada")
        mandatory_ok = False

    metragem = row.get("metragem")
    if profile.metragem_min is not None:
        if metragem is not None and metragem >= profile.metragem_min:
            s_metragem = 100
            aderencia.append("Metragem adequada")
        else:
            s_metragem = 20
            atencao.append("Metragem mínima não confirmada")
    else:
        s_metragem = 70

    txt = row.get("texto_total_norm", "")
    keywords = ["reformado", "nascente", "vista livre", "planta", "vazado"]
    hits = sum(1 for k in keywords if k in txt)
    s_text = min(100, 40 + hits * 15)

    quality_penalty = 0
    if infer.alerta_ambiguo:
        quality_penalty += 12
    if not row.get("link"):
        quality_penalty += 8

    score = (
        0.26 * s_region
        + 0.24 * s_price
        + 0.2 * s_rooms
        + 0.08 * s_suite
        + 0.08 * s_ban
        + 0.06 * s_vaga
        + 0.04 * s_metragem
        + 0.04 * s_text
        - quality_penalty
    )
    score = max(0, min(100, round(score, 1)))

    if score >= 80:
        aderencia.append("Bom potencial comercial de visita")
    if score < 55:
        atencao.append("Aderência geral baixa para envio prioritário")

    trecho = str(row.get("descricao", ""))[:180]
    motivo = "Equilíbrio entre critérios obrigatórios e potencial de visita."

    motivo_descarte = None
    if not mandatory_ok:
        motivo_descarte = "; ".join(atencao[:3])

    return ScoreResult(
        score=score,
        mandatory_ok=mandatory_ok,
        pontos_aderencia=aderencia,
        pontos_atencao=atencao,
        motivo=motivo,
        inferencias={
            "suite_confirmada": infer.suite_confirmada,
            "banheiro_completo_confirmado": infer.banheiro_completo_confirmado,
            "vaga_confirmada": infer.vaga_confirmada,
            "metragem_confirmada": infer.metragem_confirmada,
        },
        trecho_descricao=trecho,
        motivo_descarte=motivo_descarte,
    )
