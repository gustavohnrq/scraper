from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .parser_utils import extract_number, first_non_empty, normalize_text


ALIASES: dict[str, list[str]] = {
    "id": ["id", "codigo", "codigo_imovel"],
    "link": ["link", "url", "anuncio_link"],
    "titulo": ["titulo", "title", "nome"],
    "preco": ["preco", "valor", "preco_venda", "price"],
    "regiao": ["regiao", "bairro", "setor", "localizacao"],
    "bairro": ["bairro"],
    "cidade": ["cidade", "municipio"],
    "metragem": ["metragem", "area", "area_util", "m2"],
    "quartos": ["quartos", "dormitorios", "qtd_quartos"],
    "suites": ["suites", "suítes", "qtd_suites"],
    "banheiros": ["banheiros", "wc", "qtd_banheiros"],
    "vagas": ["vagas", "garagem", "qtd_vagas"],
    "andar": ["andar", "pavimento"],
    "condominio": ["condominio", "valor_condominio"],
    "iptu": ["iptu", "valor_iptu"],
    "caracteristicas": ["caracteristicas", "features", "diferenciais"],
    "descricao": ["descricao", "descrição", "texto"],
    "anunciante": ["anunciante", "corretor", "imobiliaria"],
    "data_coleta": ["data_coleta", "scraped_at", "data"],
}


@dataclass
class NormalizationResult:
    dataframe: pd.DataFrame
    schema_map: dict[str, str]


def _find_column(columns: list[str], aliases: list[str]) -> str | None:
    normalized = {normalize_text(c): c for c in columns}
    for alias in aliases:
        if normalize_text(alias) in normalized:
            return normalized[normalize_text(alias)]
    return None


def normalize_schema(df: pd.DataFrame) -> NormalizationResult:
    original_columns = list(df.columns)
    schema_map: dict[str, str] = {}

    for target, aliases in ALIASES.items():
        found = _find_column(original_columns, aliases)
        if found:
            schema_map[target] = found

    out = pd.DataFrame()
    for target in ALIASES:
        source = schema_map.get(target)
        out[target] = df[source] if source else None

    out["id"] = out["id"].fillna(df.index.astype(str)).astype(str)
    out["titulo"] = out["titulo"].fillna("").astype(str)
    out["descricao"] = out["descricao"].fillna("").astype(str)
    out["caracteristicas"] = out["caracteristicas"].fillna("").astype(str)

    for col in ["preco", "metragem", "quartos", "suites", "banheiros", "vagas", "condominio", "iptu"]:
        out[col] = out[col].apply(extract_number)

    out["regiao"] = out.apply(
        lambda r: first_non_empty(r.get("regiao"), r.get("bairro"), r.get("cidade")), axis=1
    )
    out["regiao_norm"] = out["regiao"].map(normalize_text)
    out["texto_total"] = (out["titulo"].fillna("") + " " + out["caracteristicas"].fillna("") + " " + out["descricao"].fillna(""))
    out["texto_total_norm"] = out["texto_total"].map(normalize_text)

    return NormalizationResult(dataframe=out, schema_map=schema_map)
