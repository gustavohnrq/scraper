from __future__ import annotations

import pandas as pd

from .profile_schema import ClientProfile, score_to_level
from .scoring import score_listing


def curate(df: pd.DataFrame, profile: ClientProfile) -> dict:
    results: list[dict] = []
    discarded: list[dict] = []

    for row in df.to_dict(orient="records"):
        sr = score_listing(row, profile)
        item = {
            "id": row.get("id", ""),
            "titulo": row.get("titulo", ""),
            "link": row.get("link", ""),
            "preco": row.get("preco"),
            "regiao": row.get("regiao", ""),
            "score": sr.score,
            "grau_aderencia": score_to_level(sr.score),
            "pontos_aderencia": sr.pontos_aderencia,
            "pontos_atencao": sr.pontos_atencao,
            "motivo_escolha": sr.motivo,
            "trecho_descricao": sr.trecho_descricao,
            **sr.inferencias,
            "mandatory_ok": sr.mandatory_ok,
        }
        if sr.mandatory_ok:
            results.append(item)
        else:
            discarded.append(
                {
                    "id": item["id"],
                    "titulo": item["titulo"],
                    "motivo_descarte": sr.motivo_descarte or "Não atendeu critérios obrigatórios",
                    "score": item["score"],
                }
            )

    results.sort(key=lambda x: (x["score"], len(x["pontos_atencao"]) * -1), reverse=True)
    discarded.sort(key=lambda x: x["score"], reverse=True)

    selected = results[: profile.quantidade_max_resultados]
    for idx, it in enumerate(selected, start=1):
        it["posicao"] = idx

    near_miss = discarded[: min(8, max(profile.quantidade_max_resultados, 5))]
    for d in near_miss:
        d.pop("score", None)

    return {"selecionados": selected, "descartados_relevantes": near_miss}
