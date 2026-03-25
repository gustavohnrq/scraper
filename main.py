from __future__ import annotations

import argparse
from pathlib import Path

from config import DEFAULT_PHONE, OUTPUT_DIR
from src.exporter import export_outputs
from src.loader import load_csv
from src.messaging import build_profile_summary, build_wa_me_text, build_wa_me_url, build_whatsapp_message
from src.normalizer import normalize_schema
from src.profile_schema import ClientProfile
from src.selector import curate
from src.utils import read_json, setup_logging, timestamp_folder


def build_result(profile: ClientProfile, curated: dict, phone: str) -> dict:
    selecionados = curated["selecionados"]
    mensagem = build_whatsapp_message(profile, selecionados)
    texto_wa = build_wa_me_text(mensagem)
    wa_url = build_wa_me_url(phone, texto_wa)

    return {
        "perfil_resumido": build_profile_summary(profile),
        "criterios": {
            "obrigatorios": [
                "faixa de preço",
                "região prioritária ou aceitável",
                "quartos mínimos/exatos",
                "vaga (se obrigatória)",
            ],
            "importantes": [
                "suíte",
                "banheiro completo",
                "metragem mínima",
                "qualidade da informação",
            ],
            "desejaveis": [
                "características extras",
                "planta funcional",
                "potencial real de visita",
            ],
        },
        "selecionados": selecionados,
        "descartados_relevantes": curated["descartados_relevantes"],
        "mensagem_whatsapp": mensagem,
        "texto_wa_me": texto_wa,
        "wa_me_url": wa_url,
    }


def run(csv_path: Path, perfil_path: Path, phone: str) -> dict:
    setup_logging()
    df = load_csv(csv_path)
    norm = normalize_schema(df)
    profile = ClientProfile(**read_json(perfil_path))
    curated = curate(norm.dataframe, profile)
    result = build_result(profile, curated, phone)

    out_dir = timestamp_folder(OUTPUT_DIR)
    paths = export_outputs(result, out_dir)
    print("Arquivos gerados:")
    for k, v in paths.items():
        print(f"- {k}: {v}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Curadoria imobiliária para Brasília")
    parser.add_argument("--csv", required=True, help="Caminho do CSV de imóveis")
    parser.add_argument("--perfil", required=True, help="Caminho do JSON de perfil")
    parser.add_argument("--phone", default=DEFAULT_PHONE, help="Telefone no formato 55DDDNÚMERO")
    args = parser.parse_args()

    run(Path(args.csv), Path(args.perfil), args.phone)
