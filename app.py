from __future__ import annotations

import json
import pandas as pd
import streamlit as st

from config import DEFAULT_PHONE
from main import build_result
from src.normalizer import normalize_schema
from src.profile_schema import ClientProfile
from src.selector import curate

st.set_page_config(page_title="Curadoria Imobiliária BSB", layout="wide")
st.title("Curadoria Imobiliária Residencial - Brasília")

uploaded = st.file_uploader("Envie o CSV de imóveis", type=["csv"])

st.subheader("Perfil do cliente")
col1, col2 = st.columns(2)
with col1:
    tipo = st.selectbox("Tipo de cliente", ["familia", "investidor", "upgrade", "primeira compra"])
    prioridades = st.text_input("Regiões prioritárias (separadas por vírgula)", "Asa Norte")
    aceitaveis = st.text_input("Regiões aceitáveis (separadas por vírgula)", "Sudoeste,Noroeste")
    preco_max = st.number_input("Preço máximo", min_value=0.0, value=1250000.0, step=50000.0)
    preco_min = st.number_input("Preço mínimo (opcional)", min_value=0.0, value=0.0, step=50000.0)
    quartos_exatos = st.number_input("Quartos exatos (0 para ignorar)", min_value=0, max_value=10, value=3)
with col2:
    quartos_min = st.number_input("Quartos mínimos", min_value=0, max_value=10, value=0)
    suite_ob = st.checkbox("Suíte obrigatória", value=True)
    ban_ob = st.checkbox("2º banheiro completo obrigatório", value=True)
    vaga_ob = st.checkbox("Vaga obrigatória", value=True)
    metragem_min = st.number_input("Metragem mínima (0 para ignorar)", min_value=0.0, value=85.0)
    qtd_res = st.slider("Quantidade máxima de resultados", min_value=3, max_value=10, value=5)
    phone = st.text_input("Telefone (wa.me)", DEFAULT_PHONE)
obs = st.text_area("Observações", "Cliente família. Busca boa planta e imóvel com potencial real de moradia.")

if st.button("Rodar análise"):
    if uploaded is None:
        st.error("Envie um CSV para continuar.")
    else:
        raw_df = pd.read_csv(uploaded)
        norm = normalize_schema(raw_df)
        profile = ClientProfile(
            tipo_cliente=tipo,
            regioes_prioritarias=[x.strip() for x in prioridades.split(",") if x.strip()],
            regioes_aceitaveis=[x.strip() for x in aceitaveis.split(",") if x.strip()],
            preco_max=preco_max,
            preco_min=preco_min or None,
            quartos_exatos=quartos_exatos or None,
            quartos_min=quartos_min or None,
            suite_obrigatoria=suite_ob,
            segundo_banheiro_completo_obrigatorio=ban_ob,
            vaga_obrigatoria=vaga_ob,
            metragem_min=metragem_min or None,
            observacoes=obs,
            quantidade_max_resultados=qtd_res,
        )
        curated = curate(norm.dataframe, profile)
        result = build_result(profile, curated, phone)

        st.success("Análise concluída")
        st.subheader("Ranking")
        st.dataframe(pd.DataFrame(result["selecionados"]))

        st.subheader("Descartados relevantes")
        st.dataframe(pd.DataFrame(result["descartados_relevantes"]))

        st.subheader("Mensagem WhatsApp")
        st.text_area("Mensagem pronta", result["mensagem_whatsapp"], height=220)

        st.subheader("Link wa.me")
        st.code(result["wa_me_url"])

        st.download_button(
            "Baixar JSON",
            data=json.dumps(result, ensure_ascii=False, indent=2),
            file_name="resultado_curadoria.json",
            mime="application/json",
        )
        st.download_button(
            "Baixar CSV selecionados",
            data=pd.DataFrame(result["selecionados"]).to_csv(index=False).encode("utf-8"),
            file_name="selecionados_resumo.csv",
            mime="text/csv",
        )
