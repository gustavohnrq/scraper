from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def export_outputs(result: dict, output_dir: Path) -> dict[str, Path]:
    json_path = output_dir / "resultado_curadoria.json"
    csv_path = output_dir / "selecionados_resumo.csv"
    msg_path = output_dir / "mensagem_whatsapp.txt"
    wa_path = output_dir / "wa_me_link.txt"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    pd.DataFrame(result.get("selecionados", [])).to_csv(csv_path, index=False)
    msg_path.write_text(result.get("mensagem_whatsapp", ""), encoding="utf-8")
    wa_path.write_text(result.get("wa_me_url", ""), encoding="utf-8")

    return {
        "json": json_path,
        "csv": csv_path,
        "mensagem": msg_path,
        "wa": wa_path,
    }
