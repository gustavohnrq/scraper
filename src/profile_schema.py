from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ClientProfile(BaseModel):
    tipo_cliente: str = "familia"
    regioes_prioritarias: list[str] = Field(default_factory=list)
    regioes_aceitaveis: list[str] = Field(default_factory=list)
    preco_max: float
    preco_min: float | None = None
    quartos_min: int | None = None
    quartos_exatos: int | None = None
    suite_obrigatoria: bool = False
    segundo_banheiro_completo_obrigatorio: bool = False
    vaga_obrigatoria: bool = False
    vagas_min: int | None = None
    metragem_min: float | None = None
    observacoes: str = ""
    quantidade_max_resultados: int = 5

    @model_validator(mode="after")
    def validate_quartos(self) -> "ClientProfile":
        if self.quartos_exatos is None and self.quartos_min is None:
            self.quartos_min = 1
        return self


class AdherenceLevel(str):
    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"


def score_to_level(score: float) -> Literal["alta", "media", "baixa"]:
    if score >= 80:
        return "alta"
    if score >= 60:
        return "media"
    return "baixa"
