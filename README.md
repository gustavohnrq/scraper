# Sistema de Curadoria Imobiliária - Brasília

Sistema local em Python para curadoria comercial de imóveis residenciais (foco DFImóveis e outras bases CSV).

## Funcionalidades
- Leitura de CSV com dados incompletos e normalização de schema via aliases.
- Scoring comercial de 0 a 100 com critérios obrigatórios/importantes/desejáveis.
- Inferências conservadoras para suíte, 2º banheiro completo, vaga e ambiguidades.
- Ranking dos melhores imóveis + descartados relevantes com motivo.
- Geração de mensagem comercial WhatsApp no padrão solicitado.
- Geração de texto URL-encoded e link `wa.me`.
- Exportação em JSON, CSV e TXT em pasta `output/<timestamp>/`.
- Execução via CLI e interface web local leve com Flask.

## Requisitos
- Python 3.11+ (compatível com Python 3.12)

## Instalação (modo CLI - recomendado)
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

## Instalação da interface web local
```bash
pip install -r requirements-web.txt
```

## Execução via CLI
```bash
python main.py --csv data/imoveis_exemplo.csv --perfil data/perfil_exemplo.json --phone 5561999999999
```

## Execução via Web local
```bash
python app.py
```
Acesse: `http://127.0.0.1:8501`

## Nota sobre o erro com Streamlit/PyArrow
Se você estava executando `streamlit run app.py` e encontrou `segmentation fault`, esta versão migra para Flask para evitar dependências nativas que causavam esse problema no seu ambiente Python 3.12/macOS.

## Estrutura
```text
main.py
app.py
config.py
requirements.txt
requirements-web.txt
README.md
/data
/output
/src
```

## Mapeamento flexível de colunas
O módulo `src/normalizer.py` usa `ALIASES` para mapear colunas equivalentes:
- `preco`: `preco`, `valor`, `preco_venda`, `price`
- `metragem`: `metragem`, `area`, `area_util`, `m2`
- `quartos`: `quartos`, `dormitorios`, `qtd_quartos`
- etc.

### Como adaptar para novas colunas
1. Abra `src/normalizer.py`.
2. Inclua o novo nome no dicionário `ALIASES` da chave canônica adequada.
3. Se for um campo numérico novo, inclua na lista de colunas tratadas com `extract_number`.
4. Rode novamente via CLI para validar resultado.

## Regras de inferência implementadas
- `1 suíte + lavabo` **não** confirma `2º banheiro completo`.
- `banheiro social`, `wc social`, `banheiro completo` confirmam banheiro completo.
- Apenas número de banheiros sem contexto => **não confirmado**.
- Sinais de ambiguidade: `DCE convertida`, `adaptada`, `reversível` geram alerta e penalidade.

## Saídas
- `resultado_curadoria.json`
- `selecionados_resumo.csv`
- `mensagem_whatsapp.txt`
- `wa_me_link.txt`

## Exemplo de JSON final
Formato compatível com o solicitado (perfil, critérios, selecionados, descartados, mensagem, texto e URL wa.me).
