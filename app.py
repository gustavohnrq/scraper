from __future__ import annotations

import json
from io import BytesIO

import pandas as pd
from flask import Flask, Response, render_template_string, request, send_file

from config import DEFAULT_PHONE
from main import build_result
from src.normalizer import normalize_schema
from src.profile_schema import ClientProfile
from src.selector import curate

app = Flask(__name__)
LAST_RESULT: dict | None = None

HTML = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8" />
  <title>Curadoria Imobiliária BSB</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; }
    input, textarea, select { width: 100%; padding: 8px; margin-top: 4px; margin-bottom: 10px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    table { border-collapse: collapse; width: 100%; margin-top: 12px; }
    th, td { border: 1px solid #ddd; padding: 8px; font-size: 13px; }
    th { background: #f3f3f3; }
    .btn { padding: 10px 14px; }
    .small { color: #666; font-size: 12px; }
    .box { padding: 10px; background: #fafafa; border: 1px solid #eee; }
  </style>
</head>
<body>
  <h2>Curadoria Imobiliária Residencial - Brasília</h2>
  <p class="small">Interface web local leve (Flask), sem dependência de Streamlit/PyArrow.</p>

  <form method="post" enctype="multipart/form-data">
    <label>CSV de imóveis</label>
    <input type="file" name="csv_file" accept=".csv" required />

    <div class="grid">
      <div>
        <label>Tipo de cliente</label>
        <select name="tipo_cliente">
          <option>familia</option>
          <option>investidor</option>
          <option>upgrade</option>
          <option>primeira compra</option>
        </select>

        <label>Regiões prioritárias (vírgula)</label>
        <input name="regioes_prioritarias" value="Asa Norte" />

        <label>Regiões aceitáveis (vírgula)</label>
        <input name="regioes_aceitaveis" value="Sudoeste,Noroeste" />

        <label>Preço máximo</label>
        <input name="preco_max" type="number" step="1000" value="1250000" />

        <label>Preço mínimo (opcional)</label>
        <input name="preco_min" type="number" step="1000" value="" />

        <label>Quartos exatos (opcional)</label>
        <input name="quartos_exatos" type="number" value="3" />
      </div>

      <div>
        <label>Quartos mínimos (opcional)</label>
        <input name="quartos_min" type="number" value="" />

        <label>Suíte obrigatória</label>
        <select name="suite_obrigatoria"><option value="true" selected>Sim</option><option value="false">Não</option></select>

        <label>2º banheiro completo obrigatório</label>
        <select name="segundo_banheiro"><option value="true" selected>Sim</option><option value="false">Não</option></select>

        <label>Vaga obrigatória</label>
        <select name="vaga_obrigatoria"><option value="true" selected>Sim</option><option value="false">Não</option></select>

        <label>Metragem mínima (opcional)</label>
        <input name="metragem_min" type="number" step="0.1" value="85" />

        <label>Quantidade máxima de resultados</label>
        <input name="quantidade_max_resultados" type="number" value="5" />
      </div>
    </div>

    <label>Observações</label>
    <textarea name="observacoes" rows="3">Cliente família. Busca boa planta e imóvel com potencial real de moradia.</textarea>

    <label>Telefone (wa.me)</label>
    <input name="phone" value="{{ phone_default }}" />

    <button class="btn" type="submit">Rodar análise</button>
  </form>

  {% if result %}
    <hr/>
    <h3>Ranking (Selecionados)</h3>
    <div>{{ selected_table|safe }}</div>

    <h3>Descartados relevantes</h3>
    <div>{{ discarded_table|safe }}</div>

    <h3>Mensagem WhatsApp</h3>
    <div class="box"><pre>{{ result['mensagem_whatsapp'] }}</pre></div>

    <h3>Link wa.me</h3>
    <div class="box"><a href="{{ result['wa_me_url'] }}" target="_blank">{{ result['wa_me_url'] }}</a></div>

    <p>
      <a href="/download/json">Baixar JSON</a> |
      <a href="/download/csv">Baixar CSV selecionados</a>
    </p>
  {% endif %}
</body>
</html>
"""


def _to_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "sim", "yes"}


def _to_float_or_none(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def _to_int_or_none(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


@app.route("/", methods=["GET", "POST"])
def index() -> str:
    global LAST_RESULT
    result = None
    selected_table = ""
    discarded_table = ""

    if request.method == "POST":
        file = request.files.get("csv_file")
        if not file:
            return "CSV não enviado", 400

        raw_df = pd.read_csv(file)
        norm = normalize_schema(raw_df)

        profile = ClientProfile(
            tipo_cliente=request.form.get("tipo_cliente", "familia"),
            regioes_prioritarias=[x.strip() for x in request.form.get("regioes_prioritarias", "").split(",") if x.strip()],
            regioes_aceitaveis=[x.strip() for x in request.form.get("regioes_aceitaveis", "").split(",") if x.strip()],
            preco_max=float(request.form.get("preco_max", "0") or "0"),
            preco_min=_to_float_or_none(request.form.get("preco_min")),
            quartos_exatos=_to_int_or_none(request.form.get("quartos_exatos")),
            quartos_min=_to_int_or_none(request.form.get("quartos_min")),
            suite_obrigatoria=_to_bool(request.form.get("suite_obrigatoria", "true")),
            segundo_banheiro_completo_obrigatorio=_to_bool(request.form.get("segundo_banheiro", "true")),
            vaga_obrigatoria=_to_bool(request.form.get("vaga_obrigatoria", "true")),
            metragem_min=_to_float_or_none(request.form.get("metragem_min")),
            observacoes=request.form.get("observacoes", ""),
            quantidade_max_resultados=int(request.form.get("quantidade_max_resultados", "5") or "5"),
        )

        curated = curate(norm.dataframe, profile)
        result = build_result(profile, curated, request.form.get("phone", DEFAULT_PHONE))
        LAST_RESULT = result

        selected_table = pd.DataFrame(result["selecionados"]).to_html(index=False, escape=False)
        discarded_table = pd.DataFrame(result["descartados_relevantes"]).to_html(index=False, escape=False)

    return render_template_string(
        HTML,
        result=result,
        selected_table=selected_table,
        discarded_table=discarded_table,
        phone_default=DEFAULT_PHONE,
    )


@app.route("/download/json", methods=["GET"])
def download_json() -> Response:
    if not LAST_RESULT:
        return Response("Nenhum resultado disponível", status=404)
    data = json.dumps(LAST_RESULT, ensure_ascii=False, indent=2).encode("utf-8")
    return send_file(BytesIO(data), as_attachment=True, download_name="resultado_curadoria.json", mimetype="application/json")


@app.route("/download/csv", methods=["GET"])
def download_csv() -> Response:
    if not LAST_RESULT:
        return Response("Nenhum resultado disponível", status=404)
    csv_data = pd.DataFrame(LAST_RESULT.get("selecionados", [])).to_csv(index=False).encode("utf-8")
    return send_file(BytesIO(csv_data), as_attachment=True, download_name="selecionados_resumo.csv", mimetype="text/csv")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8501, debug=False)
