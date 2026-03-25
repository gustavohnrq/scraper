# dfimoveis_firefox_full_extract (mac/linux/windows)
#
# Adaptado para rodar no macOS (e continua compatível com Windows/Linux).
#
# Pré-requisitos no macOS:
#   1) Firefox instalado (Aplicativos)
#   2) geckodriver instalado (Homebrew):
#        brew install geckodriver
#      (ou coloque geckodriver no PATH)
#
# Dependências Python:
#   pip install selenium requests beautifulsoup4
#   (Opcional, recomendado): pip install lxml
#
# Rodar:
#   python coleta_nicho_agrupado_mac.py
#
from __future__ import annotations

import argparse

import os
import shutil
import tempfile
import time
import subprocess
import csv
import re
import random
import sys
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException


# =========================
# PERFIL FIREFOX (AUTO)
# =========================
def guess_firefox_profiles_base_dir() -> Path:
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA", "")
        return Path(appdata) / "Mozilla" / "Firefox" / "Profiles"
    elif sys.platform.startswith("darwin"):
        return Path.home() / "Library" / "Application Support" / "Firefox" / "Profiles"
    else:
        return Path.home() / ".mozilla" / "firefox"


def guess_firefox_profile_dir(prefer_default_release: bool = True) -> str:
    base = guess_firefox_profiles_base_dir()
    if not base.exists():
        raise RuntimeError(f"Pasta de perfis do Firefox não encontrada: {base}")

    candidates: list[Path] = []
    if prefer_default_release:
        candidates = sorted(base.glob("*.default-release"))
    if not candidates:
        candidates = sorted([p for p in base.iterdir() if p.is_dir()])

    if not candidates:
        raise RuntimeError(f"Nenhum perfil do Firefox encontrado em: {base}")

    return str(candidates[0])


# =======================
# CONFIGURE (AJUSTE AQUI)
# =======================
BASE_DIR = Path(__file__).resolve().parent

# -----------------------
# PATH helpers
# -----------------------
def as_path(p: str | Path) -> Path:
    """Converte string/Path para Path.

    - Não usa .resolve() para não quebrar em caminhos inexistentes no Windows.
    - No macOS/Linux, normaliza caminhos com '//' no início (ex.: '//Users/..' -> '/Users/..').
    """
    if isinstance(p, Path):
        return p
    s = str(p).strip()
    # Normaliza '//' no início em POSIX (algumas vezes aparece por erro de digitação)
    if os.name != "nt" and s.startswith("//"):
        s = "/" + s.lstrip("/")
    return Path(s).expanduser()


def ensure_dir(p: str | Path) -> Path:
    """Garante que o diretório existe (mkdir -p) e retorna Path."""
    pp = as_path(p)
    pp.mkdir(parents=True, exist_ok=True)
    return pp


ORIG_PROFILE = guess_firefox_profile_dir()

# -----------------------------------------
# JOBS (multi-coleta)
# Cada job agora pode receber caminhos manuais:
#   - output_dir: onde salvar os CSVs de LINKS e RESULTADO
#   - debug_root_dir: pasta base onde salvar os debugs (cria subpasta por job+data)
#   - diff_output_dir: onde salvar os CSVs de comparação (entradas/saídas)
#
# Alternativamente, você pode setar caminhos *completos* (override):
#   - links_csv: caminho completo do CSV de links
#   - output_csv: caminho completo do CSV de resultado
#   - debug_dir: caminho completo do diretório de debug (sem subpasta automática)
#
# Observação: os valores abaixo estão como BASE_DIR por padrão. Troque pelos caminhos
# reais desejados (ex.: r"C:\coletas\dfimoveis\saida").
# -----------------------------------------
JOBS: list[dict[str, str]] = [
    {
        # ===== DF (link geral; único CSV final) =====
        "name": "venda_DF_geral",
        "url": "https://www.dfimoveis.com.br/venda/df/brasilia/apartamento/2,3,4-quartos?valorinicial=1000000&valorfinal=1750000",
        "output_dir": "/Users/macbook/Desktop/Corretagem_2026/Coletas/DF/Coletas",
        "output_csv": "/Users/macbook/Desktop/Corretagem_2026/Coletas/DF/Coletas/dfimoveis_resultado_DF_geral.csv",
        "debug_root_dir": "/Users/macbook/Desktop/Corretagem_2026/Coletas/Debug_DF",
        "diff_output_dir": "/Users/macbook/Desktop/Corretagem_2026/Coletas/DF/Resultados",
    },
    {
        # ===== WI (link geral; único CSV final) =====
        "name": "venda_WI_geral",
        "wi_url": "https://www.wimoveis.com.br/venda/apartamentos/df/brasilia/desde-2-ate-4-quartos?price=1000000,1750000",
        "wi_output_dir": "/Users/macbook/Desktop/Corretagem_2026/Coletas/WI/Coletas",
        "wi_output_csv": "/Users/macbook/Desktop/Corretagem_2026/Coletas/WI/Coletas/wimoveis_resultado_WI_geral.csv",
        "wi_diff_output_dir": "/Users/macbook/Desktop/Corretagem_2026/Coletas/WI/Resultados",
        "wi_debug_root_dir": "/Users/macbook/Desktop/Corretagem_2026/Coletas/Debug_WI",
    },
]

INICIO_PAG = 1
FIM_PAG = 999999  # auto-stop por páginas vazias/sem novos links

HEADLESS = False
TEMPO_ESPERA = 1.6  # espera “curta” p/ seletores (o safe_get faz o resto)  # espera “curta” p/ seletores (o safe_get faz o resto)

RETRIES_HTTP = 3
HTTP_CONNECT_TIMEOUT = 7
HTTP_READ_TIMEOUT = 20

RECICLE_CADA = 35
AUTO_STOP_EMPTY_PAGES = 2
AUTO_STOP_NO_NEW_PAGES = 3

# Navegação resiliente
NAV_TRIES = 2
PAGELOAD_TIMEOUT = 28
SCRIPT_TIMEOUT = 50

# Página “branca” (aba vazia)
BLANK_DETECT_MIN_CHARS = 1200
BLANK_MAX_RETRIES = 2
BLANK_BACKOFF_BASE = 0.35

# Antibot/captcha: volta ao fluxo "original" (menos agressivo)
CAPTCHA_BACKOFF = 1.0

# ETAPA 2: tentativas por detalhe
DETAIL_HTTP_TRIES = 2
DETAIL_SELENIUM_TRIES = 2
DETAIL_BACKOFF_BASE = 0.55

# =======================
# DEBUG
# =======================
DEBUG_SAVE_FAIL_HTML = True
DEBUG_DIR = BASE_DIR / "debug_detalhes"  # vai ser sobrescrito por JOB
DEBUG_MAX_BODY_CHARS_IN_REASON = 2200  # para não lotar txt
# =======================


# -----------------------
# Parser BS4 (lxml se existir, senão html.parser)
# -----------------------
def bs_parser() -> str:
    try:
        import lxml  # noqa: F401
        return "lxml"
    except Exception:
        return "html.parser"


PARSER = bs_parser()


# ---------- util de SO ----------
def kill_firefox():
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/IM", "firefox.exe"], check=False, capture_output=True)
            subprocess.run(["taskkill", "/F", "/IM", "updater.exe"], check=False, capture_output=True)
        else:
            subprocess.run(["pkill", "-f", "Firefox"], check=False, capture_output=True)
            subprocess.run(["pkill", "-f", "firefox"], check=False, capture_output=True)
    except Exception:
        pass


def copy_profile_to_temp(src: str) -> str:
    if not os.path.isdir(src):
        raise RuntimeError(f"Perfil não existe: {src}")

    tmp_dir = os.path.join(tempfile.gettempdir(), "ff_profile_tmp")
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)

    shutil.copytree(src, tmp_dir)

    for fname in ("parent.lock", "lock", "compatibility.ini"):
        fp = os.path.join(tmp_dir, fname)
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception:
                pass

    cache2 = os.path.join(tmp_dir, "cache2")
    if os.path.isdir(cache2):
        shutil.rmtree(cache2, ignore_errors=True)

    return tmp_dir


def find_firefox_binary_windows() -> str | None:
    candidates = [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Mozilla Firefox\firefox.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def resolve_geckodriver_path() -> str:
    envp = os.environ.get("GECKODRIVER_PATH", "").strip('"').strip()
    if envp:
        if os.path.isfile(envp):
            return envp
        raise RuntimeError(f"GECKODRIVER_PATH definido, mas arquivo não existe: {envp}")

    from shutil import which
    p = which("geckodriver")
    if p and os.path.isfile(p):
        return p

    raise RuntimeError(
        "geckodriver não encontrado."
        "No macOS, instale via Homebrew: brew install geckodriver"
        "Ou garanta que 'geckodriver' esteja no PATH."
        "Alternativamente, defina a variável GECKODRIVER_PATH com o caminho completo do binário."
    )


def launch_firefox_with_profile(profile_path: str) -> webdriver.Firefox:
    opts = FirefoxOptions()
    if HEADLESS:
        opts.add_argument("-headless")

    # performance / fingerprint (mantém seu setup)
    opts.set_preference("permissions.default.image", 2)
    opts.set_preference("browser.cache.disk.enable", False)
    opts.set_preference("browser.cache.memory.enable", True)
    opts.set_preference("dom.webdriver.enabled", False)
    opts.set_preference("useAutomationExtension", False)
    opts.set_preference("media.autoplay.default", 1)
    opts.set_preference("network.http.max-persistent-connections-per-server", 10)
    opts.set_preference("network.http.pipelining", True)

    # Não esperar load completo
    opts.page_load_strategy = "eager"

    # profile
    opts.add_argument("-no-remote")
    opts.add_argument("-profile")
    opts.add_argument(profile_path)

    if sys.platform.startswith("win"):
        ff_bin = os.environ.get("FIREFOX_BINARY") or find_firefox_binary_windows()
        if ff_bin:
            opts.binary_location = ff_bin
        else:
            raise RuntimeError("Firefox não encontrado. Instale ou defina FIREFOX_BINARY.")
    else:
        ff_bin = os.environ.get("FIREFOX_BINARY", "").strip().strip('"')
        if ff_bin and os.path.isfile(ff_bin):
            opts.binary_location = ff_bin

    gecko = resolve_geckodriver_path()
    service = Service(gecko)

    driver = webdriver.Firefox(service=service, options=opts)
    driver.set_page_load_timeout(PAGELOAD_TIMEOUT)
    driver.set_script_timeout(SCRIPT_TIMEOUT)
    return driver


def montar_url_pagina(base: str, pagina: int) -> str:
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{urlencode({'pagina': pagina})}"


def wait_any(driver, css_list, timeout=TEMPO_ESPERA) -> bool:
    end = time.time() + timeout
    for sel in css_list:
        rem = end - time.time()
        if rem <= 0:
            break
        try:
            WebDriverWait(driver, rem).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
            return True
        except Exception:
            continue
    return False


def scroll_until_stable(driver, max_jumps=10, pause=0.10):
    last_h = 0
    stable_count = 0
    for _ in range(max_jumps):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause + random.random() * 0.05)
        h = driver.execute_script("return document.body.scrollHeight;")
        if h == last_h:
            stable_count += 1
            if stable_count >= 2:
                break
        else:
            stable_count = 0
        last_h = h


def page_source_stabilized(curr_len: int, last_len: int, stable_count: int, delta: int = 200, need: int = 3) -> tuple[bool, int, int]:
    """Heurística rápida: considera 'estável' quando o tamanho do HTML muda muito pouco por alguns ciclos.
    Não altera lógica de captcha/gravação; apenas permite sair mais cedo do loop de espera quando a página já hidratou."""
    if last_len >= 0 and abs(curr_len - last_len) <= delta:
        stable_count += 1
    else:
        stable_count = 0
    return (stable_count >= need), curr_len, stable_count


# ---------- debug helpers ----------
def _safe_mkdir(p: Path):
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def debug_save(prefix: str, idx: int, url: str, reason: str, html: str | None = None):
    if not DEBUG_SAVE_FAIL_HTML:
        return
    _safe_mkdir(DEBUG_DIR)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{prefix}_{idx:05d}_{ts}"

    try:
        (DEBUG_DIR / f"{base}.url.txt").write_text(url, encoding="utf-8")
    except Exception:
        pass

    try:
        snippet = ""
        if html:
            soup = BeautifulSoup(html, PARSER)
            snippet = soup.get_text(" ", strip=True)[:DEBUG_MAX_BODY_CHARS_IN_REASON]
        txt = f"REASON:\n{reason}\n\nURL:\n{url}\n\nTEXT_SNIPPET:\n{snippet}\n"
        (DEBUG_DIR / f"{base}.reason.txt").write_text(txt, encoding="utf-8")
    except Exception:
        pass

    if html:
        try:
            (DEBUG_DIR / f"{base}.html").write_text(html, encoding="utf-8", errors="ignore")
        except Exception:
            pass



# ---------- limpeza de artefatos (links/debug) ----------
def _safe_unlink(p: Path):
    try:
        if p and p.exists() and p.is_file():
            p.unlink()
    except Exception:
        pass


def _safe_rmtree(dir_path: Path, job_name: str, run_date: str):
    """Remove diretórios de debug com segurança.

    Para evitar apagar pastas "raiz" por engano, só removemos se:
      - o nome da pasta contém o job_name e o run_date (ex.: debug_detalhes_JOB_20260207)
        OU
      - o nome da pasta começa com 'debug_' e contém o run_date
    """
    try:
        if not dir_path or not dir_path.exists() or not dir_path.is_dir():
            return
        name = dir_path.name.lower()
        j = (job_name or '').lower()
        d = (run_date or '').lower()
        ok = (j in name and d in name) or (name.startswith('debug_') and d in name)
        if not ok:
            return
        shutil.rmtree(dir_path, ignore_errors=True)
    except Exception:
        pass

# ---------- parsing helpers ----------
_rx_space = re.compile(r"\s+")


def _clean(txt: str | None) -> str:
    if not txt:
        return ""
    return _rx_space.sub(" ", txt).strip()


def _to_number_brl(txt: str) -> float | None:
    """Converte textos BR (ex.: 'R$ 1.259.000', '1.259.000,50') para float.

    Regras:
      - Remove 'R$' e caracteres não-numéricos (mantém ',' e '.')
      - Se tiver ',' e '.', assume '.' milhar e ',' decimal
      - Se tiver só ',', assume ',' decimal
      - Se tiver só '.' e mais de um ponto, assume '.' milhar (remove todos)
    """
    if not txt:
        return None
    t = txt.replace("R$", "").replace("\xa0", " ").strip()
    t = re.sub(r"[^\d,\.]", "", t)

    if not t:
        return None

    if "," in t and "." in t:
        # 1.234.567,89 -> 1234567.89
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        # 1234,56 -> 1234.56
        t = t.replace(",", ".")
    else:
        # só pontos (provável milhar) -> remove
        if t.count(".") >= 1:
            # preço quase sempre vem como 1.259.000 (sem decimais)
            t = t.replace(".", "")

    try:
        return float(t)
    except Exception:
        return None


def parse_links_listagem(html: str) -> list[str]:
    soup = BeautifulSoup(html, PARSER)
    anchors = soup.select(
        "a[href*='/imovel/'][href^='/imovel/'], a[href^='https://www.dfimoveis.com.br/imovel/']"
    )
    uniq: set[str] = set()
    for a in anchors:
        href = a.get("href")
        if not href:
            continue
        if href.startswith("/"):
            href = "https://www.dfimoveis.com.br" + href
        if "/imovel/" in href:
            uniq.add(href)
    return list(uniq)


_rx_filtro = re.compile(r"window\.imovelFiltro\s*=\s*\{([^}]+)\}", re.I)
_rx_lat = re.compile(r"latitude\s*=\s*([\-0-9\.]+)")
_rx_lng = re.compile(r"longitude\s*=\s*([\-0-9\.]+)")
_rx_codigo_url = re.compile(r"-(\d+)(?:$|[/?#])")


def _area_to_float_str(txt: str) -> str:
    t = re.sub(r"[^\d,\.]", "", txt or "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    return t if t else ""


def _extract_quartos(html: str) -> str:
    m = re.search(r"(\d+)\s*quartos?\b", html, re.I)
    if m:
        return m.group(1)
    return ""


def _extract_vagas(soup: BeautifulSoup, html: str) -> str:
    el = soup.select_one("div.info-one.garage span")
    if el:
        m = re.search(r"(\d+)", el.get_text(" ", strip=True))
        if m:
            return m.group(1)
    m = re.search(r"(\d+)\s*(?:vaga|vagas|garagem|garagens)\b", html, re.I)
    if m:
        return m.group(1)
    return ""


def _extract_dados_deste_imovel(soup: BeautifulSoup) -> dict:
    out = {
        "publicado_ha": "",
        "aceita_financiamento": "",
        "posicao_sol": "",
        "posicao_imovel": "",
        "codigo_bloco": "",
        "tipo_bloco": "",
    }

    h = None
    for tag in soup.find_all(["h2", "h3", "h4"]):
        t = tag.get_text(" ", strip=True).lower()
        if t == "dados deste imóvel" or t == "dados deste imovel":
            h = tag
            break
    if not h:
        s = soup.find(string=re.compile(r"Dados\s+deste\s+im[oó]vel", re.I))
        if s:
            h = s.parent

    if not h:
        return out

    ul = h.find_next("ul", class_=re.compile(r"\bdetails-text\b", re.I))
    if not ul:
        return out

    for li in ul.find_all("li"):
        txt = _clean(li.get_text(" ", strip=True))
        if not txt:
            continue

        b = li.find("b")
        if b:
            label = _clean(b.get_text(" ", strip=True)).rstrip(":").lower()
            span = li.find("span", class_=re.compile("grey-color", re.I))
            value = _clean(span.get_text(" ", strip=True)) if span else _clean(txt.replace(b.get_text(), ""))
            value = value.lstrip(":").strip()
        else:
            label = ""
            value = txt

        if not label:
            if not out["tipo_bloco"]:
                out["tipo_bloco"] = value
            continue

        if "publicado" in label:
            out["publicado_ha"] = value
        elif label in ("código", "codigo"):
            out["codigo_bloco"] = value
        elif "aceita financiamento" in label:
            out["aceita_financiamento"] = value
        elif "posição do sol" in label or "posicao do sol" in label:
            out["posicao_sol"] = value
        elif "posição do imóvel" in label or "posicao do imovel" in label:
            out["posicao_imovel"] = value

    return out


def _extract_descricao(soup: BeautifulSoup) -> str:
    div = soup.select_one("div.assined-imv")
    if div:
        return _clean(div.get_text(" ", strip=True))

    h = None
    for tag in soup.find_all(["h2", "h3", "h4"]):
        t = tag.get_text(" ", strip=True).lower()
        if t == "descrição" or t == "descricao":
            h = tag
            break
    if h:
        texts = []
        cur = h
        for _ in range(6):
            cur = cur.find_next(["p", "div"])
            if not cur:
                break
            t = _clean(cur.get_text(" ", strip=True))
            if t and len(t) >= 20:
                texts.append(t)
            if len(" ".join(texts)) >= 350:
                break
        return _clean(" ".join(texts))

    return ""


def parse_detail(html: str, url: str) -> dict:
    import html as _html

    data = {
        "codigo": "", "data_coleta": "",
        "creci": "", "anunciante": "",
        "oferta": "", "tipo": "",
        "area_util": "", "bairro": "", "cidade": "",
        "preco": "", "valor_m2": "",
        "quartos": "", "vagas": "",
        "latitude": "", "longitude": "",
        "quadra": "", "link": url,

        "publicado_ha": "",
        "aceita_financiamento": "",
        "posicao_sol": "",
        "posicao_imovel": "",
        "descricao": "",
    }

    soup = BeautifulSoup(html, PARSER)

    dados = _extract_dados_deste_imovel(soup)
    data["publicado_ha"] = dados["publicado_ha"]
    data["aceita_financiamento"] = dados["aceita_financiamento"]
    data["posicao_sol"] = dados["posicao_sol"]
    data["posicao_imovel"] = dados["posicao_imovel"]

    if dados.get("codigo_bloco"):
        data["codigo"] = dados["codigo_bloco"]

    data["descricao"] = _extract_descricao(soup)

    m_filtro = _rx_filtro.search(html)
    if m_filtro:
        blob = m_filtro.group(1)

        def grab(k: str) -> str:
            m = re.search(rf'"{k}"\s*:\s*"([^"]*)"', blob)
            if m:
                return m.group(1).strip()
            m = re.search(rf'"{k}"\s*:\s*([^,}}]+)', blob)
            return (m.group(1).strip() if m else "")

        data["codigo"] = data["codigo"] or grab("IdExterno") or ""
        data["oferta"] = (grab("Negocio") or "").title() or data["oferta"]

        tipo = (grab("Tipo") or "").title()
        subtipo = (grab("Subtipo") or "").title()
        data["tipo"] = (" ".join(x for x in (tipo, subtipo) if x)) or data["tipo"]

        data["cidade"] = (grab("Cidade") or "").title() or data["cidade"]
        data["bairro"] = (grab("Bairro") or "").title() or data["bairro"]

        if not re.search(r'"Valor"\s*:\s*null', blob):
            preco_raw = re.search(r'"Valor"\s*:\s*([0-9]+(?:\.[0-9]+)?)', blob)
            if preco_raw and not data["preco"]:
                data["preco"] = str(int(float(preco_raw.group(1))))

    if not data["codigo"]:
        m_cod = _rx_codigo_url.search(url)
        if m_cod:
            data["codigo"] = m_cod.group(1)

    box_new = soup.select_one("div.imovel-info.d-flex")
    if box_new:
        h2 = box_new.select_one("h2")
        if h2 and not data["quadra"]:
            data["quadra"] = _clean(h2.get_text())

        price_wrap = box_new.select_one("div.imovel-price")
        if price_wrap:
            for h4 in price_wrap.select("h4"):
                t = _clean(h4.get_text(" ", strip=True))
                low = t.lower()
                span = h4.select_one("span.bold")
                vtxt = _clean(span.get_text()) if span else t

                if "valor m" in low:
                    if not data["valor_m2"]:
                        vm2 = _to_number_brl("R$ " + vtxt) or _to_number_brl(vtxt)
                        if vm2 is not None:
                            data["valor_m2"] = str(int(vm2))
                else:
                    if not data["preco"]:
                        v = _to_number_brl("R$ " + vtxt) or _to_number_brl(vtxt)
                        if v is not None:
                            data["preco"] = str(int(v))

        feat = box_new.select_one("div.imovel-feature")
        if feat:
            pills = [_clean(x.get_text(" ", strip=True)) for x in feat.select("div.rounded-pill")]
            for p in pills:
                if not data["area_util"] and re.search(r"\bm", p, re.I):
                    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m", p, re.I)
                    if m:
                        data["area_util"] = _area_to_float_str(m.group(1))
                if not data["quartos"] and re.search(r"\bquartos?\b", p, re.I):
                    m = re.search(r"(\d+)", p)
                    if m:
                        data["quartos"] = m.group(1)
                if not data["vagas"] and re.search(r"\bvaga", p, re.I):
                    m = re.search(r"(\d+)", p)
                    if m:
                        data["vagas"] = m.group(1)

        if not data["anunciante"]:
            anunc = box_new.select_one("div.imovel-anunciante")
            if anunc:
                img = anunc.select_one("picture img[alt]") or anunc.select_one("img[alt]")
                if img and img.has_attr("alt"):
                    data["anunciante"] = _clean(_html.unescape(img["alt"]))

        if not data["creci"]:
            anunc = box_new.select_one("div.imovel-anunciante")
            if anunc:
                span = anunc.find("span", string=re.compile(r"^\s*Creci\s*:\s*$", re.I))
                if span:
                    p = span.find_next("p")
                    if p:
                        data["creci"] = _clean(p.get_text())

    if not data["quartos"]:
        data["quartos"] = _extract_quartos(html)
    if not data["vagas"]:
        data["vagas"] = _extract_vagas(soup, html)

    if not data["preco"]:
        el = soup.select_one("#ValorImovel")
        if el:
            v = _to_number_brl(el.get_text(" ", strip=True))
            if v is not None:
                data["preco"] = str(int(v))

    if not data["valor_m2"]:
        el = soup.select_one("#valorM2Imovel")
        if el:
            v = _to_number_brl(el.get_text(" ", strip=True))
            if v is not None:
                data["valor_m2"] = str(int(v))

    if not data["area_util"]:
        area_label = soup.find("span", string=re.compile(r"Área\s*Útil", re.I))
        if area_label:
            h4 = area_label.find_next("h4")
            if h4:
                data["area_util"] = _area_to_float_str(h4.get_text())

    if not data["anunciante"]:
        h4_an = soup.select_one("h4.body-medium.bold.ellipse-text")
        if h4_an:
            data["anunciante"] = _clean(_html.unescape(h4_an.get_text(" ", strip=True)))

    if not data["creci"]:
        p_creci = soup.select_one("p.body-small.bold.neutral-text")
        if p_creci:
            m_creci = re.search(r"creci[:\s\-]*([A-Z0-9\-\.\/]+)", p_creci.get_text(strip=True), re.I)
            if m_creci:
                data["creci"] = m_creci.group(1)

    m_lat = _rx_lat.search(html)
    if m_lat:
        data["latitude"] = m_lat.group(1)
    m_lng = _rx_lng.search(html)
    if m_lng:
        data["longitude"] = m_lng.group(1)

    if not data["valor_m2"] and data["preco"] and data["area_util"]:
        try:
            area_num = float(str(data["area_util"]).replace(",", "."))
            if area_num > 0:
                data["valor_m2"] = str(int(round(float(data["preco"]) / area_num)))
        except Exception:
            pass

    data["data_coleta"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return data


# ---------- indicadores (LISTA x DETALHE) ----------
def looks_blank(html: str) -> bool:
    if not html:
        return True
    if len(html) < BLANK_DETECT_MIN_CHARS:
        return True
    low = html.lower()
    if "<body" in low:
        soup = BeautifulSoup(html, PARSER)
        if len(soup.get_text(" ", strip=True)) < 50:
            return True
    return False


def looks_blocked_generic(html: str) -> bool:
    if not html:
        return True
    txt = html.lower()
    # Bloqueios comuns (Cloudflare/403/etc.)
    # Importante: NÃO use '/cdn-cgi/' genérico aqui, pois alguns sites podem incluir assets Cloudflare
    # mesmo quando a página está OK. Mantemos apenas o chk específico.
    sinais = (
        "access denied", "forbidden", "temporarily unavailable",
        "/cdn-cgi/l/chk", "request unsuccessful", "blocked",
        "verificando se você é humano", "verificando se voce e humano",
        "enable javascript and cookies to continue",
        "precisa revisar a segurança da sua conexão",
        "central de ajuda da cloudflare", "ray id:",
    )
    return any(s in txt for s in sinais)


# ==========================================================
# WIMOVEIS (ImovelWeb) - parse de LINKS e DETALHES
# - Mantém o MESMO esquema de saída do DFImoveis.
# - Campos que não existirem no WI ficam vazios.
# ==========================================================
WI_BASE = "https://www.wimoveis.com.br"


def _wi_full_url(href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return WI_BASE.rstrip("/") + href
    return WI_BASE.rstrip("/") + "/" + href


def parse_links_listagem_wimoveis(html: str) -> list[str]:
    """Extrai links de anúncios do HTML de listagem do Wimoveis/ImovelWeb.

    Padrões observados no outerHTML:
      - <a ... href="/propriedades/...-<ID>.html">
      - <a ... data-to-posting="..."> (fallback)
    """
    if not html:
        return []

    soup = BeautifulSoup(html, PARSER)
    links: set[str] = set()

    # 1) href direto (mais confiável)
    for a in soup.select('a[href^="/propriedades/"]'):
        href = (a.get("href") or "").strip()
        if href:
            links.add(_wi_full_url(href))

    # 2) fallback: data-to-posting
    for a in soup.select('a[data-to-posting]'):
        href = (a.get("href") or "").strip()
        if href and "/propriedades/" in href:
            links.add(_wi_full_url(href))
        else:
            dtp = (a.get("data-to-posting") or "").strip()
            if dtp and "/propriedades/" in dtp:
                links.add(_wi_full_url(dtp))

    # 3) fallback bem amplo (quando mudam classes)
    if not links:
        for a in soup.find_all("a"):
            href = (a.get("href") or "").strip()
            if href.startswith("/propriedades/"):
                links.add(_wi_full_url(href))

    out = sorted(links)
    return out


def is_detail_loaded_wimoveis(html: str) -> bool:
    if not html:
        return False
    low = html.lower()

    # Marcadores do outerHTML de detalhe (preferenciais)
    marcadores = (
        "title-container-property",
        "price-container-property",
        "reactpublisherdata",
        "section-icon-features-property",
        "publisherdata-module__publisher-card",
        "price-value",
        "title-type-sup-property",
    )
    if any(m in low for m in marcadores):
        return True

    # Fallbacks (quando classes mudam, mas a página é claramente um anúncio)
    if " - wimoveis</title>" in low and ("id:" in low or " - id:" in low):
        return True
    if "/propriedades/" in low and ("contate o anunciante" in low or "fotos" in low):
        return True

    return False


def looks_blocked_list_wimoveis(html: str) -> bool:
    """Heurística de bloqueio/antibot para LISTA (WI).

    Importante: o WI pode conter palavras como 'captcha'/'turnstile' no HTML mesmo
    quando a listagem está carregada (scripts). Então, se detectarmos marcadores
    claros de listagem/linkagem, consideramos **não bloqueado**.
    """
    if not html:
        return True
    low = html.lower()

    # Se há sinais claros de listagem, não trate como bloqueado
    if ("/propriedades/" in low) or ("postingcard" in low) or ("data-to-posting" in low):
        return False

    # Caso contrário, aí sim aplicamos bloqueio genérico
    if looks_blocked_generic(html):
        return True

    # Sem marcadores mínimos de listagem
    return True


def looks_blocked_detail_wimoveis(html: str) -> bool:
    """Heurística de bloqueio/antibot para DETALHE (WI).

    O WI frequentemente inclui strings como 'captcha'/'turnstile' em scripts
    mesmo com a página do anúncio carregada. Por isso:
    - Se os marcadores do anúncio aparecem (is_detail_loaded_wimoveis), NÃO bloqueia.
    - Só considera bloqueado quando NÃO carregou os marcadores e há sinais genéricos.
    """
    if not html:
        return True

    # Prioridade total: se o anúncio carregou, não bloqueia
    if is_detail_loaded_wimoveis(html):
        return False

    # Se não carregou marcadores, aí sim consideramos bloqueio genérico/erro
    if looks_blocked_generic(html):
        return True

    return True


def _wi_try_accept_cookies(driver):
    """Tenta fechar o banner de cookies quando existir (best-effort)."""
    try:
        # botão com data-qa="cookies-policy-banner" (observado no outerHTML)
        btn = driver.find_elements(By.CSS_SELECTOR, '[data-qa="cookies-policy-banner"]')
        if btn:
            try:
                btn[0].click()
                time.sleep(0.35)
                return
            except Exception:
                pass
        # fallback por texto "Aceito"
        btn2 = driver.find_elements(By.XPATH, "//button[contains(., 'Aceito') or contains(., 'ACEITO')]")
        if btn2:
            try:
                btn2[0].click()
                time.sleep(0.35)
                return
            except Exception:
                pass
    except Exception:
        pass


def selenium_fetch_detail_resilient_wimoveis(driver, href: str, max_wait_s: float = 8.0) -> str:
    # No WI, a página pode passar por verificação (Cloudflare). Precisamos aguardar mais
    # e validar "não-bloqueio" + marcadores do anúncio.
    ok = safe_get(
        driver,
        href,
        wait_css=("body", "main", "section", "article", ".price-container-property", ".title-container-property", ".price-value"),
        tries=NAV_TRIES,
    )
    if not ok:
        return ""

    _wi_try_accept_cookies(driver)

    t0 = time.time()
    best_html = ""
    last_len = -1
    stable_count = 0
    while time.time() - t0 < max_wait_s:
        html = driver.page_source or ""
        if len(html) > len(best_html):
            best_html = html

        # Se ainda estiver em verificação/bloqueio, só aguarda
        if looks_blocked_generic(html):
            time.sleep(0.18 + random.random() * 0.10)
            continue

        if is_detail_loaded_wimoveis(html):
            return html

        stabilized, last_len, stable_count = page_source_stabilized(len(html), last_len, stable_count)
        if stabilized and ("price-container-property" in best_html or "price-value" in best_html) and "R$" in best_html:
            return best_html

        # ajuda a disparar lazy-load e hidratação
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.35);")
        except Exception:
            pass
        time.sleep(0.18 + random.random() * 0.10)
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.80);")
        except Exception:
            pass
        time.sleep(0.18 + random.random() * 0.10)

    return best_html



def _wi_parse_icon_features(soup: BeautifulSoup) -> dict:
    """Lê a seção de ícones (área / quartos / vagas) do Wimoveis/ImovelWeb.

    O WI mudou markup algumas vezes:
      - Versão 1: <span class="icon-features-property__value"> / __title
      - Versão 2: <ul id="section-icon-features-property"><li>131 m² útil</li> ...
    Esta função tenta cobrir as variações.
    """
    vals = {"area_util": "", "quartos": "", "vagas": ""}

    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "")).strip().lower()

    # --------
    # Versão 1 (com spans value/title)
    # --------
    for li in soup.select("#section-icon-features-property li"):
        v_el = (
            li.select_one("span.icon-features-property__value")
            or li.select_one("span[class*='icon-features-property__value']")
        )
        t_el = (
            li.select_one("span.icon-features-property__title")
            or li.select_one("span[class*='icon-features-property__title']")
        )

        v = norm(v_el.get_text(" ", strip=True)) if v_el else ""
        t = norm(t_el.get_text(" ", strip=True)) if t_el else ""

        if v and t:
            if (("m²" in t) or ("m2" in t) or ("área" in t) or ("area" in t)) and not vals["area_util"]:
                vals["area_util"] = (v_el.get_text(" ", strip=True) if v_el else "").strip()
                continue

            if (("dorm" in t) or ("quarto" in t) or ("suíte" in t) or ("suite" in t)) and not vals["quartos"]:
                vals["quartos"] = (v_el.get_text(" ", strip=True) if v_el else "").strip()
                continue

            if (("vaga" in t) or ("garag" in t) or ("cochera" in t)) and not vals["vagas"]:
                vals["vagas"] = (v_el.get_text(" ", strip=True) if v_el else "").strip()
                continue

    # --------
    # Versão 2 (texto "131 m² útil", "2 quartos", "1 vaga" dentro do <li>)
    # --------
    if not any(vals.values()):
        for li in soup.select("#section-icon-features-property li, ul.section-icon-features-property li, ul#section-icon-features-property li"):
            txt = norm(li.get_text(" ", strip=True))
            if not txt:
                continue

            # tenta capturar o primeiro número
            m = re.match(r"^(\d+[\d\.,]*)\s+(.*)$", txt)
            if not m:
                continue
            num_raw = m.group(1)
            label = m.group(2)

            # normaliza número
            num = re.sub(r"[^0-9,\.]", "", num_raw).replace(".", "").replace(",", ".")
            if not num:
                continue

            if (("m²" in label) or ("m2" in label) or ("útil" in label) or ("util" in label) or ("área" in label) or ("area" in label)) and not vals["area_util"]:
                vals["area_util"] = num
                continue

            if (("quarto" in label) or ("dorm" in label) or ("suite" in label) or ("suíte" in label)) and not vals["quartos"]:
                # quartos: mantém inteiro
                vals["quartos"] = str(int(float(num))) if num.replace(".", "", 1).isdigit() else num
                continue

            if (("vaga" in label) or ("garag" in label) or ("cochera" in label)) and not vals["vagas"]:
                vals["vagas"] = str(int(float(num))) if num.replace(".", "", 1).isdigit() else num
                continue

    return vals


def _wi_extract_jsonld_description(soup: BeautifulSoup) -> str:
    for sc in soup.find_all("script", attrs={"type": "application/ld+json"}):
        txt = (sc.string or sc.get_text() or "").strip()
        if not txt:
            continue
        try:
            import json
            data = json.loads(txt)
        except Exception:
            continue

        # pode ser dict ou list
        if isinstance(data, dict):
            desc = data.get("description")
            if isinstance(desc, str) and desc.strip():
                return desc.strip()
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    desc = item.get("description")
                    if isinstance(desc, str) and desc.strip():
                        return desc.strip()
    return ""


def _wi_extract_first(pattern: str, text: str) -> str:
    m = re.search(pattern, text, flags=re.I | re.S)
    return m.group(1).strip() if m else ""


def _wi_parse_jsonld_fields(soup: BeautifulSoup) -> dict:
    """Extrai campos úteis do JSON-LD do Wimoveis/ImovelWeb (quando existir)."""
    out: dict = {}
    for sc in soup.find_all("script", attrs={"type": "application/ld+json"}):
        txt = (sc.string or sc.get_text() or "").strip()
        if not txt:
            continue
        try:
            import json
            data = json.loads(txt)
        except Exception:
            continue

        items = data if isinstance(data, list) else [data]
        for it in items:
            if not isinstance(it, dict):
                continue

            obj = it.get("object") if isinstance(it.get("object"), dict) else it

            addr = obj.get("address") if isinstance(obj, dict) else None
            if isinstance(addr, dict):
                if not out.get("bairro") and isinstance(addr.get("addressLocality"), str):
                    out["bairro"] = addr.get("addressLocality").strip()
                if not out.get("street") and isinstance(addr.get("streetAddress"), str):
                    out["street"] = addr.get("streetAddress").strip()

            geo = obj.get("geo") if isinstance(obj, dict) else None
            if isinstance(geo, dict):
                lat = geo.get("latitude")
                lon = geo.get("longitude")
                if lat and not out.get("latitude"):
                    out["latitude"] = str(lat).strip()
                if lon and not out.get("longitude"):
                    out["longitude"] = str(lon).strip()

    return out


def parse_detail_wimoveis(html: str, url: str) -> dict:
    """Extrai detalhes do anúncio do Wimoveis/ImovelWeb e retorna no mesmo schema do DFImoveis."""
    soup = BeautifulSoup(html, PARSER)

    # defaults
    reg = {
        "codigo": "",
        "data_coleta": datetime.now().strftime("%Y-%m-%d"),
        "creci": "",
        "anunciante": "",
        "oferta": "",
        "tipo": "",
        "area_util": "",
        "bairro": "",
        "cidade": "",
        "preco": "",
        "valor_m2": "",
        "quartos": "",
        "vagas": "",
        "latitude": "",
        "longitude": "",
        "quadra": "",
        "link": url,
        "publicado_ha": "",
        "aceita_financiamento": "",
        "posicao_sol": "",
        "posicao_imovel": "",
        "descricao": "",
    }

    # codigo (tenta pelo final da URL)
    m_id = re.search(r"-(\d{6,})\.html", url)
    if not m_id:
        m_id = re.search(r"(\d{6,})", url)
    reg["codigo"] = m_id.group(1) if m_id else ""

    # preço + oferta (no WI geralmente vem juntos no bloco .price-value)
    # Ex.: "venda R$ 1.600.000"
    pv_el = soup.select_one(".price-container-property .price-value") or soup.select_one(".price-value")
    if pv_el:
        pv_txt = pv_el.get_text(" ", strip=True)
        # oferta
        m_of = re.search(r"\b(venda|aluguel|temporada)\b", pv_txt, flags=re.I)
        if m_of:
            reg["oferta"] = m_of.group(1).strip().lower()
        # preço
        preco_num = _to_number_brl(pv_txt)
        if preco_num is not None:
            reg["preco"] = str(int(round(preco_num)))

    # fallback: oferta separada (quando existir)
    if not reg.get("oferta"):
        oferta_el = soup.select_one(".offer-type-sup-property") or soup.select_one(".title-type-sup")
        if oferta_el:
            txt = oferta_el.get_text(" ", strip=True)
            m_of = re.search(r"\b(venda|aluguel|temporada)\b", txt, flags=re.I)
            if m_of:
                reg["oferta"] = m_of.group(1).strip().lower()

    # tipo + dados rápidos (a própria linha costuma ter m²/quartos/vagas)
    tipo_el = soup.select_one("h2.title-type-sup-property")
    if tipo_el:
        raw = tipo_el.get_text(" ", strip=True)
        reg["tipo"] = raw.split("·")[0].strip()

        if not reg["area_util"]:
            ma = re.search(r"(\d+)\s*m²", raw, flags=re.I)
            if ma:
                reg["area_util"] = f'{ma.group(1)}m²'
        if not reg["quartos"]:
            mq = re.search(r"(\d+)\s*quarto", raw, flags=re.I)
            if mq:
                reg["quartos"] = mq.group(1)
        if not reg["vagas"]:
            mv = re.search(r"(\d+)\s*vaga", raw, flags=re.I)
            if mv:
                reg["vagas"] = mv.group(1)

    # anunciante
    anunc_el = soup.select_one('[data-qa="linkMicrositioAnunciante"]')
    if anunc_el:
        reg["anunciante"] = anunc_el.get_text(" ", strip=True)
    else:
        img = soup.select_one("section#reactPublisherData img[alt]")
        if img:
            reg["anunciante"] = (img.get("alt") or "").strip()

    # publicado
    pub_el = soup.select_one("p.userViews-module__post-antiquity-views___8Zfch")
    if pub_el:
        reg["publicado_ha"] = pub_el.get_text(" ", strip=True)


    # CRECI (quando existir)
    try:
        codes_sec = soup.select_one("section#reactPublisherCodes")
        if codes_sec:
            for li in codes_sec.select("li"):
                txt = li.get_text(" ", strip=True)
                if re.search(r"\bCRECI\b", txt, flags=re.I):
                    m = re.search(r"CRECI:\s*([^\s]+)", txt, flags=re.I)
                    if m:
                        reg["creci"] = m.group(1).strip()
                    else:
                        # fallback: tudo após o ':'
                        if ":" in txt:
                            reg["creci"] = txt.split(":", 1)[1].strip()
                    break
    except Exception:
        pass

    # bairro / cidade / quadra (bloco de localização do mapa)
    loc_el = (
        soup.select_one("#map-section .section-location-property h4")
        or soup.select_one(".section-location-property.section-location-property-classified h4")
        or soup.select_one(".section-location-property h4")
    )
    if loc_el:
        loc_txt = re.sub(r"\s+", " ", loc_el.get_text(" ", strip=True)).strip()
        # Ex.: "Asa Norte SQN 112, Asa Norte, Brasília"
        parts = [p.strip() for p in loc_txt.split(",") if p.strip()]
        if len(parts) >= 1 and not reg["cidade"]:
            reg["cidade"] = parts[-1]
        if len(parts) >= 2 and not reg["bairro"]:
            reg["bairro"] = parts[-2]

        # quadra - tenta do texto inteiro
        mq = re.search(r"\bSQ(?:N|S)\s*\d{3}\b", loc_txt, flags=re.I)
        if mq and not reg["quadra"]:
            reg["quadra"] = mq.group(0).upper().replace("  ", " ").strip()

    # JSON-LD costuma trazer bairro + lat/long + streetAddress (muito confiável)
    j = _wi_parse_jsonld_fields(soup)
    if j.get("bairro") and not reg["bairro"]:
        reg["bairro"] = j["bairro"]
    if j.get("latitude") and not reg["latitude"]:
        reg["latitude"] = j["latitude"]
    if j.get("longitude") and not reg["longitude"]:
        reg["longitude"] = j["longitude"]


    # fallback coordenadas (quando JSON-LD não trouxer)
    if (not reg.get("latitude")) or (not reg.get("longitude")):
        lat2, lng2 = _wi_decode_map_coords_from_html(html or "")
        if lat2 and not reg.get("latitude"):
            reg["latitude"] = lat2
        if lng2 and not reg.get("longitude"):
            reg["longitude"] = lng2

    
    # ==========================================================
    # ENDEREÇO COMPLETO (coluna "quadra")
    # - A pedido: sempre gravar o endereço mais completo possível
    #   (mantendo o nome da coluna como "quadra").
    # ==========================================================
    address_parts: list[str] = []

    # 1) Texto do bloco de localização (mapa)
    #    Ex.: "Noroeste, Brasília" ou "Asa Norte, Brasília"
    if "loc_txt" in locals():
        try:
            if loc_txt:
                address_parts.append(str(loc_txt).strip())
        except Exception:
            pass

    # 2) streetAddress do JSON-LD (quando existir)
    street = (j.get("street") or "").strip()
    if street:
        address_parts.append(street)

    # 3) Se houver código de quadra/endereço típico de BSB no texto geral do anúncio,
    #    colocamos no começo do endereço (sem substituir o resto).
    try:
        txt_all = soup.get_text(" ", strip=True)
        mcode = re.search(
            r"\b(?:SQ(?:N|S|NW|SW)\s*\d{3}|QI\s*\d+|QS\s*\d+|QNL\s*\d+|QNA\s*\d+|QND\s*\d+|CLN\s*\d{3}|CLS\s*\d{3}|SCRN\s*\d{3}|SCRS\s*\d{3}|SCS\s*\d+|SCN\s*\d+|EQN\s*\d{3}|EQS\s*\d{3})\b",
            txt_all,
            flags=re.I,
        )
        if mcode:
            code_addr = re.sub(r"\s+", " ", mcode.group(0)).upper().strip()
            # evita duplicar
            if all(code_addr.lower() not in (p or "").lower() for p in address_parts):
                address_parts.insert(0, code_addr)
    except Exception:
        pass

    # 4) Bairro e cidade já normalizados no reg (se vierem)
    b = (reg.get("bairro") or "").strip()
    c = (reg.get("cidade") or "").strip()
    if b and all(b.lower() not in (p or "").lower() for p in address_parts):
        address_parts.append(b)
    if c and all(c.lower() not in (p or "").lower() for p in address_parts):
        address_parts.append(c)

    # 5) UF / CEP (quando vierem do JSON-LD)
    st = (j.get("state") or "").strip()
    pc = (j.get("postal") or "").strip()
    if st and all(st.lower() not in (p or "").lower() for p in address_parts):
        address_parts.append(st)
    if pc and all(pc.lower() not in (p or "").lower() for p in address_parts):
        address_parts.append(pc)

    # normaliza e deduplica mantendo ordem
    addr_norm = []
    seen = set()
    for p in address_parts:
        p2 = re.sub(r"\s+", " ", (p or "").strip())
        if not p2:
            continue
        key = p2.lower()
        if key in seen:
            continue
        seen.add(key)
        addr_norm.append(p2)

    reg["quadra"] = ", ".join(addr_norm).strip()
# ícones (área/quartos/vagas) - mantém como estava, mas agora é complementar
    feats = _wi_parse_icon_features(soup)
    for k, v in feats.items():
        if v is None:
            continue
        if not reg.get(k):
            reg[k] = v

    # valor_m2 (quando temos preço e área)
    try:
        preco = float(reg["preco"]) if reg["preco"] else None
        area = None
        if reg["area_util"]:
            area = float(re.sub(r"[^0-9,\.]", "", reg["area_util"]).replace(".", "").replace(",", "."))
        if preco and area and area > 0:
            reg["valor_m2"] = f"{preco/area:.2f}"
    except Exception:
        pass

    # descrição (JSON-LD é o mais limpo)
    desc = _wi_extract_jsonld_description(soup)
    if not desc:
        # fallback: tenta por regex (em alguns casos vem em JSON grande)
        desc = _wi_extract_first(r'"description"\s*:\s*"([^"]{20,}?)"', html or "")

    if desc:
        desc = re.sub(r"\s+", " ", desc).strip()
        reg["descricao"] = desc

        if re.search(r"aceita\s+financiamento", desc, flags=re.I):
            reg["aceita_financiamento"] = "Sim"

        # quadra (heurística simples)
        mq = re.search(r"\bSQ(?:N|S)\s*\d{3}\b", desc, flags=re.I)
        if mq and not reg["quadra"]:
            reg["quadra"] = mq.group(0).upper().replace("  ", " ").strip()

    return reg

def _wi_extract_jsonld_primary_item(soup: BeautifulSoup) -> dict | None:
    """Retorna o primeiro item JSON-LD que pareça ser o imóvel (ex.: Apartment).

    Ignora blocos genéricos como WebSite/Organization.
    """
    import json

    for sc in soup.find_all("script", attrs={"type": "application/ld+json"}):
        txt = (sc.string or sc.get_text() or "").strip()
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue

        candidates = []
        if isinstance(data, dict):
            candidates = [data]
        elif isinstance(data, list):
            candidates = [x for x in data if isinstance(x, dict)]

        for item in candidates:
            t = item.get("@type")
            if not t:
                continue
            if isinstance(t, list):
                t0 = (t[0] if t else "")
            else:
                t0 = t
            t0 = str(t0).lower()

            if t0 in {"website", "organization", "breadcrumbs", "breadcrumb", "webpage"}:
                continue

            # frequentemente é "Apartment"
            return item

    return None


def _wi_decode_map_coords_from_html(html: str) -> tuple[str, str]:
    """Algumas páginas trazem coordenadas em variáveis JS base64:
        const mapLatOf =  "LTE1Ljc1MDYzOTQwMDAwMDAwMA==";
        const mapLngOf =  "LTQ3Ljg5MDI5MzcwMDAwMDAwMA==";
    """
    if not html:
        return "", ""
    mlat = re.search(r"\bmapLatOf\b\s*=\s*\"([^\"]+)\"", html)
    mlng = re.search(r"\bmapLngOf\b\s*=\s*\"([^\"]+)\"", html)
    if not (mlat and mlng):
        return "", ""

    import base64

    def dec(s: str) -> str:
        try:
            return base64.b64decode(s).decode("utf-8", errors="ignore").strip()
        except Exception:
            return ""

    lat = dec(mlat.group(1))
    lng = dec(mlng.group(1))

    # sanity
    if lat and not re.match(r"^-?\d+(?:\.\d+)?$", lat):
        lat = ""
    if lng and not re.match(r"^-?\d+(?:\.\d+)?$", lng):
        lng = ""

    return lat, lng


def _wi_guess_city_and_bairro_from_jsonld(item: dict) -> tuple[str, str, str]:
    """Retorna (cidade, bairro, quadra) a partir do JSON-LD, com heurísticas."""
    cidade = ""
    bairro = ""
    quadra = ""

    addr = item.get("address") or {}
    if isinstance(addr, dict):
        bairro = str(addr.get("addressRegion") or "").strip()
        loc = str(addr.get("addressLocality") or "").strip()
        street = str(addr.get("streetAddress") or "").strip()

        # cidade (geralmente "Brasília, Distrito Federal, Brasil, ")
        if loc:
            if "brasil" in loc.lower() and "brasilia" in loc.lower():
                cidade = "Brasília"
            else:
                # pega a primeira parte antes de vírgula
                cidade = loc.split(",")[0].strip()

        # quadra / SQN / SQS / etc
        base = f"{street} {loc} {bairro}"
        mq = re.search(r"\b(SQ[N|S]|SQS|SQN|Q\w{0,3}[NS])\s*\d{1,4}\b", base, flags=re.I)
        if mq:
            quadra = re.sub(r"\s+", " ", mq.group(0).upper()).strip()

    return cidade, bairro, quadra




def etapa1_coletar_links_wimoveis(driver, base_lista: str, arq_links: Path) -> tuple[list[str], webdriver.Firefox]:
    """
    ETAPA 1 (WI): coleta links da LISTAGEM.

    Observação importante:
      - O Wimoveis/ImovelWeb nem sempre expõe (ou permite clicar) um botão de "próxima" via Selenium.
      - A paginação funciona de forma robusta montando as URLs com parâmetro `page=N`, preservando
        o restante da query string, por exemplo:
          .../desde-2-ate-4-quartos?page=2&price=1000000,1750000
    """
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode as _urlencode

    def _with_page(url: str, page: int) -> str:
        sp = urlsplit(url)
        q = dict(parse_qsl(sp.query, keep_blank_values=True))
        # page=1 -> remove para manter URL "limpa" (como você forneceu)
        if page <= 1:
            q.pop("page", None)
        else:
            q["page"] = str(page)
        new_q = _urlencode(q, doseq=True)
        return urlunsplit((sp.scheme, sp.netloc, sp.path, new_q, sp.fragment))

    links_all: list[str] = []
    vistos: set[str] = set()

    primeira_links = not arq_links.exists()
    f_links = open(arq_links, "a", newline="", encoding="utf-8", buffering=1024 * 1024)
    w_links = csv.writer(f_links)
    if primeira_links:
        w_links.writerow(["link"])
        f_links.flush()

    empty_pages = 0
    no_new_pages = 0

    try:
        for page in range(1, FIM_PAG + 1):
            url_page = _with_page(base_lista, page)
            print(f"\n[ETAPA 1 - WI] Página {page}: {url_page}")

            ok = safe_get(driver, url_page, wait_css=("body", "main", "section", "article"))
            if not ok:
                print("  [x] Falha de navegação no WI. Tentando reciclar browser...")
                driver = recover_browser(driver)
                ok = safe_get(driver, url_page, wait_css=("body", "main", "section", "article"))
                if not ok:
                    print("  [x] Ainda falhou. Encerrando ETAPA 1 (WI).")
                    break

            _wi_try_accept_cookies(driver)
            scroll_until_stable(driver)
            html_list = driver.page_source

            if looks_blank(html_list):
                empty_pages += 1
                print(f"  [!] Página em branco. empty_pages={empty_pages}")
                if empty_pages >= AUTO_STOP_EMPTY_PAGES and page > 1:
                    print("  [✓] Listagem terminou (páginas vazias). Encerrando ETAPA 1 (WI).")
                    break
                continue

            if looks_blocked_list_wimoveis(html_list):
                print("  [!] Antibot/captcha na LISTA (WI). Backoff + recicla...")
                # recuperação agressiva: 1s -> refresh | +1s -> fecha/reabre
                driver, ok2 = captcha_fast_recover(
                    driver,
                    url_page,
                    wait_css=("body", "main", "section", "article"),
                    accept_cookies_fn=_wi_try_accept_cookies,
                    do_scroll=False,
                )
                if not ok2:
                    print("  [x] Ainda falhou após reciclar. Encerrando ETAPA 1 (WI).")
                    break
                _wi_try_accept_cookies(driver)
                scroll_until_stable(driver)
                html_list = driver.page_source

            links = parse_links_listagem_wimoveis(html_list)

            if not links:
                empty_pages += 1
                print(f"  [!] Sem links. empty_pages={empty_pages}")
                if empty_pages >= AUTO_STOP_EMPTY_PAGES and page > 1:
                    print("  [✓] Listagem terminou (páginas vazias). Encerrando ETAPA 1 (WI).")
                    break
            else:
                empty_pages = 0

            work = [h for h in links if h not in vistos]

            # Heurística WI: perto do fim, o site começa a repetir links.
            # Se a página trouxer 5 links novos ou menos, consideramos que chegou ao final.
            if page > 1 and len(work) <= 5:
                print(f"  [✓] Apenas {len(work)} links novos (≤5). Encerrando ETAPA 1 (WI) para evitar repetição.")
                break

            if page > 1 and not work:
                no_new_pages += 1
                print(f"  [!] Sem links novos. no_new_pages={no_new_pages}")
                if no_new_pages >= AUTO_STOP_NO_NEW_PAGES:
                    print("  [✓] Não há mais links novos. Encerrando ETAPA 1 (WI).")
                    break
            else:
                no_new_pages = 0

            for h in work:
                vistos.add(h)
                links_all.append(h)
                w_links.writerow([h])
            if work:
                f_links.flush()

            print(f"  [+] Coletados {len(work)} links novos | total acumulado: {len(links_all)}")

        return links_all, driver

    finally:
        try:
            f_links.close()
        except Exception:
            pass


# =========================
# ETAPA 2 (WI): extrair detalhes
# =========================
def etapa2_extrair_detalhes_wimoveis(driver, links: list[str], writer: csv.DictWriter, fcsv, base_lista: str):
    total_ok = 0
    sess = driver_to_session(driver, default_domain="www.wimoveis.com.br")

    for idx, href in enumerate(links, start=1):
        ok_reg = False

        # ---- 1) Tenta HTTP
        last_http_html = ""
        last_http_err = ""
        for _t in range(DETAIL_HTTP_TRIES):
            try:
                html = http_get(sess, href, base_lista)
                last_http_html = html or ""

                if is_detail_loaded_wimoveis(html):
                    reg = parse_detail_wimoveis(html, href)
                    writer.writerow(reg)
                    fcsv.flush()
                    total_ok += 1
                    ok_reg = True
                    break

                last_http_err = "HTTP retornou HTML sem marcadores do imóvel (WI)"
                time.sleep(0.25 + random.random() * 0.45)

            except Exception as e:
                last_http_err = f"HTTP exception (WI): {repr(e)}"
                time.sleep(0.25 + random.random() * 0.45)

        if ok_reg:
            if idx % 20 == 0:
                print(f"[ETAPA 2 - WI] Progresso: {idx}/{len(links)} | gravados={total_ok}")
            time.sleep(0.02 + random.random() * 0.06)
            continue

        # debug do HTTP
        if last_http_html:
            debug_save("wi_detail_fail_http", idx, href, last_http_err or "HTTP sem motivo", last_http_html)
        else:
            debug_save("wi_detail_fail_http", idx, href, last_http_err or "HTTP sem HTML", None)

        # ---- 2) Selenium
        for _st in range(DETAIL_SELENIUM_TRIES):
            try:
                detail_html = selenium_fetch_detail_resilient_wimoveis(driver, href)

                if looks_blank(detail_html):
                    debug_save("wi_detail_blank", idx, href, "Detalhe branco/não carregou (selenium)", detail_html)
                    print("  [!] (ETAPA 2 - WI) Detalhe branco/não carregou. Reabrindo browser e tentando novamente...")
                    time.sleep(BLANK_BACKOFF_BASE + random.random())
                    driver = recover_browser(driver)
                    sess = driver_to_session(driver, default_domain="www.wimoveis.com.br")
                    continue

                if looks_blocked_detail_wimoveis(detail_html):
                    debug_save("wi_detail_fail_selenium", idx, href, "Sem marcadores/bloqueio real no detalhe (selenium)", detail_html)
                    print("  [!] (ETAPA 2 - WI) Detalhe sem marcadores/erro real. Backoff + recicla...")
                    # recuperação agressiva: 1s -> refresh | +1s -> fecha/reabre
                    driver, _ok = captcha_fast_recover(
                        driver,
                        href,
                        wait_css=("body", "main", "section", "article", ".price-container-property", ".title-container-property", ".price-value"),
                        accept_cookies_fn=_wi_try_accept_cookies,
                        do_scroll=False,
                    )
                    sess = driver_to_session(driver, default_domain="www.wimoveis.com.br")
                    continue

                reg = parse_detail_wimoveis(detail_html, href)
                writer.writerow(reg)
                fcsv.flush()
                total_ok += 1
                ok_reg = True
                break

            except Exception as e:
                debug_save("wi_detail_exception", idx, href, f"Selenium exception (WI): {repr(e)}", None)
                print(f"  [x] (ETAPA 2 - WI) Selenium falhou ({idx}/{len(links)}): {href} -> {repr(e)}")
                time.sleep(DETAIL_BACKOFF_BASE + random.random() * 2)
                driver = recover_browser(driver)
                sess = driver_to_session(driver, default_domain="www.wimoveis.com.br")

        if idx % 20 == 0:
            print(f"[ETAPA 2 - WI] Progresso: {idx}/{len(links)} | gravados={total_ok}")

        time.sleep(0.02 + random.random() * 0.06)

        if idx > 0 and idx % RECICLE_CADA == 0:
            sess = driver_to_session(driver, default_domain="www.wimoveis.com.br")

    return total_ok, driver


def is_detail_loaded(html: str) -> bool:
    if not html:
        return False
    low = html.lower()
    if "dados deste im" in low:
        return True
    if "details-text" in low:
        return True
    if "assined-imv" in low:
        return True
    if "imovel-info" in low:
        return True
    if "window.imovelfiltro" in low:
        return True
    if 'id="id-imovel"' in low:
        return True
    return False


def looks_blocked_list(html: str) -> bool:
    if not html:
        return True
    if looks_blocked_generic(html):
        return True
    if "/imovel/" not in html:
        return True
    return False


def looks_blocked_detail(html: str) -> bool:
    if not html:
        return True
    # Se o detalhe está carregado (marcadores presentes), NÃO é bloqueio
    # mesmo que existam strings genéricas (ex.: assets/proteções).
    if is_detail_loaded(html):
        return False
    # Caso não tenha marcadores, aí sim checamos sinais de bloqueio.
    if looks_blocked_generic(html):
        return True
    return True


# ---------- HTTP helpers ----------
BROWSER_HEADERS_BASE = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.8,en-US;q=0.5,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}


def build_pooled_session(user_agent: str) -> requests.Session:
    sess = requests.Session()
    sess.headers.update({"User-Agent": user_agent, **BROWSER_HEADERS_BASE})
    retry = Retry(
        total=RETRIES_HTTP,
        backoff_factor=0.25,
        status_forcelist=(403, 408, 413, 429, 500, 502, 503, 504),
        allowed_methods=["HEAD", "GET"],
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(pool_connections=64, pool_maxsize=64, max_retries=retry)
    sess.mount("http://", adapter)
    sess.mount("https://", adapter)
    return sess


def driver_to_session(driver, default_domain: str = "www.dfimoveis.com.br") -> requests.Session:
    """Cria uma requests.Session reaproveitando User-Agent e cookies do Selenium.
    default_domain é usado quando o cookie não informa domínio.
    """
    ua = driver.execute_script("return navigator.userAgent;")
    sess = build_pooled_session(ua)
    for c in driver.get_cookies():
        dom = (c.get("domain") or "").lstrip(".")
        sess.cookies.set(
            c["name"], c["value"],
            domain=dom or default_domain,
            path=c.get("path", "/"),
        )
    return sess


def http_get(sess: requests.Session, url: str, referer: str) -> str:
    r = sess.get(url, headers={"Referer": referer}, timeout=(HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT))
    if r.status_code == 200 and r.text:
        return r.text
    raise RuntimeError(f"HTTP {r.status_code} em {url}")


# =========================
# navegação resiliente
# =========================
def safe_get(driver, url: str, wait_css=("main", ".container", "section", "article"), tries: int = NAV_TRIES) -> bool:
    """
    Navegação resiliente, mas mais rápida:
    - tenta um "gatilho curto" primeiro (páginas que hidratam rápido)
    - cai para o timeout padrão apenas se necessário
    """
    FAST_NAV_WAIT = 0.8  # gatilho rápido (ms/segundos) sem alterar lógica
    FULL_NAV_WAIT = max(TEMPO_ESPERA, 3.0)

    for i in range(tries):
        try:
            driver.get(url)

            # 1) gatilho rápido
            if wait_any(driver, list(wait_css), timeout=FAST_NAV_WAIT):
                return True

            # 2) fallback padrão
            if wait_any(driver, list(wait_css), timeout=FULL_NAV_WAIT):
                return True

            # 3) micro-pausa e tenta de novo
            time.sleep(0.18 + random.random() * 0.10)
            if wait_any(driver, list(wait_css), timeout=FULL_NAV_WAIT):
                return True

        except TimeoutException:
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass

            # tenta o gatilho curto e o padrão após stop
            if wait_any(driver, list(wait_css), timeout=FAST_NAV_WAIT):
                return True
            if wait_any(driver, list(wait_css), timeout=FULL_NAV_WAIT):
                return True

        except WebDriverException:
            pass

        # backoff entre tentativas (mantido)
        time.sleep(1.2 + i * 1.3 + random.random())
    return False


def recover_browser(driver):
    try:
        driver.quit()
    except Exception:
        pass
    kill_firefox()
    time.sleep(0.35 + random.random() * 0.35)

    tmp_profile_new = copy_profile_to_temp(ORIG_PROFILE)
    driver_new = launch_firefox_with_profile(tmp_profile_new)
    return driver_new


# =========================
# Anti-bot/Captcha: recuperação mais agressiva (sem mudar a lógica do fluxo)
# - Ao detectar bloqueio/captcha:
#   1) espera no máx. 1s e dá refresh
#   2) se persistir, espera +1s e fecha/reabre o browser (perfil limpo)
# =========================
CAPTCHA_REFRESH_WAIT_1 = 1.0
CAPTCHA_REFRESH_WAIT_2 = 1.0

def captcha_fast_recover(driver, url: str, wait_css=("body", "main", "section", "article"), tries_after_reopen: int = 1,
                         accept_cookies_fn=None, do_scroll: bool = False):
    # 1) aguarda curto e recarrega a mesma página
    time.sleep(CAPTCHA_REFRESH_WAIT_1)
    try:
        driver.refresh()
    except Exception:
        try:
            driver.get(url)
        except Exception:
            pass

    # aguardo curtíssimo só para destravar/hidratar
    try:
        wait_any(driver, list(wait_css), timeout=1.0)
    except Exception:
        pass

    # ações best-effort pós-refresh
    try:
        if accept_cookies_fn:
            accept_cookies_fn(driver)
    except Exception:
        pass
    try:
        if do_scroll:
            scroll_until_stable(driver)
    except Exception:
        pass

    # checa se saiu do "modo verificação"
    try:
        html = driver.page_source or ""
    except Exception:
        html = ""
    if html and (not looks_blank(html)) and (not looks_blocked_generic(html)):
        return driver, True

    # 2) persistiu -> aguarda curto e reabre browser
    time.sleep(CAPTCHA_REFRESH_WAIT_2)
    driver = recover_browser(driver)
    ok = safe_get(driver, url, wait_css=wait_css, tries=tries_after_reopen)

    # pós-reabertura
    try:
        if ok and accept_cookies_fn:
            accept_cookies_fn(driver)
    except Exception:
        pass
    try:
        if ok and do_scroll:
            scroll_until_stable(driver)
    except Exception:
        pass

    return driver, ok


def selenium_fetch_detail_resilient(driver, href: str, max_wait_s: float = 7.5) -> str:
    ok = safe_get(driver, href, wait_css=("body", "main", "section", "article"), tries=NAV_TRIES)
    if not ok:
        return ""

    t0 = time.time()
    best_html = ""
    last_len = -1
    stable_count = 0
    while time.time() - t0 < max_wait_s:
        html = driver.page_source or ""
        if len(html) > len(best_html):
            best_html = html

        if is_detail_loaded(html):
            return html

        stabilized, last_len, stable_count = page_source_stabilized(len(html), last_len, stable_count)
        if stabilized and len(best_html) > 8000 and ("R$" in best_html or "preço" in best_html or "valor" in best_html):
            return best_html

        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.35);")
        except Exception:
            pass
        time.sleep(0.18 + random.random() * 0.10)
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.75);")
        except Exception:
            pass
        time.sleep(0.18 + random.random() * 0.10)

    return best_html


# =========================
# ETAPA 1: coletar links (e gravar incremental)
# =========================
def etapa1_coletar_links(driver, base_lista: str, arq_links: Path) -> tuple[list[str], webdriver.Firefox]:
    links_all: list[str] = []
    vistos: set[str] = set()

    primeira_links = not arq_links.exists()
    f_links = open(arq_links, "a", newline="", encoding="utf-8", buffering=1024 * 1024)
    w_links = csv.writer(f_links)
    if primeira_links:
        w_links.writerow(["link"])
        f_links.flush()

    empty_pages = 0
    no_new_pages = 0

    try:
        for page in range(INICIO_PAG, FIM_PAG + 1):
            url = montar_url_pagina(base_lista, page)
            print(f"\n[ETAPA 1] Página {page}: {url}")

            html_list = ""
            loaded = False

            for br in range(BLANK_MAX_RETRIES + 1):
                ok = safe_get(driver, url)
                if not ok:
                    print("  [!] Falha de navegação. Reabrindo browser...")
                    driver = recover_browser(driver)
                    continue

                scroll_until_stable(driver)
                html_list = driver.page_source

                if looks_blank(html_list):
                    if br < BLANK_MAX_RETRIES:
                        print("  [!] Página em branco. Reabrindo e tentando novamente...")
                        time.sleep(BLANK_BACKOFF_BASE + random.random())
                        driver = recover_browser(driver)
                        continue
                    else:
                        print("  [x] Página branca persistiu. Pulando.")
                        html_list = ""

                if html_list and looks_blocked_list(html_list):
                    print("  [!] Antibot/captcha na LISTA. Backoff + recicla (fluxo original)...")
                    # recuperação agressiva: 1s -> refresh | +1s -> fecha/reabre
                    driver, ok2 = captcha_fast_recover(driver, url, wait_css=("main", ".container", "section", "article"))
                    if not ok2:
                        print("  [x] Ainda falhou após reciclar. Pulando.")
                        html_list = ""
                    else:
                        scroll_until_stable(driver)
                        html_list = driver.page_source

                if html_list:
                    loaded = True
                    break

            if not loaded:
                continue

            links = parse_links_listagem(html_list)

            if not links:
                empty_pages += 1
                print(f"  [!] Sem links. empty_pages={empty_pages}")
                if empty_pages >= AUTO_STOP_EMPTY_PAGES and page > 1:
                    print("  [✓] Listagem terminou (páginas vazias). Encerrando ETAPA 1.")
                    break
                time.sleep(0.6 + random.random() * 0.3)
                continue
            else:
                empty_pages = 0

            work = [h for h in links if h not in vistos]
            if page > 1 and not work:
                no_new_pages += 1
                print(f"  [!] Sem links novos. no_new_pages={no_new_pages}")
                if no_new_pages >= AUTO_STOP_NO_NEW_PAGES:
                    print("  [✓] Não há mais links novos. Encerrando ETAPA 1.")
                    break
            else:
                no_new_pages = 0

            for h in work:
                vistos.add(h)
                links_all.append(h)
                w_links.writerow([h])
            if work:
                f_links.flush()

            print(f"  [+] Coletados {len(work)} links novos | total acumulado: {len(links_all)}")
            time.sleep(0.05 + random.random() * 0.15)

        return links_all, driver

    finally:
        try:
            f_links.close()
        except Exception:
            pass


# =========================
# ETAPA 2: extrair detalhes (com debug)
# =========================
def etapa2_extrair_detalhes(driver, links: list[str], writer: csv.DictWriter, fcsv, base_lista: str):
    total_ok = 0
    sess = driver_to_session(driver)

    for idx, href in enumerate(links, start=1):
        ok_reg = False

        # ---- 1) Tenta HTTP
        last_http_html = ""
        last_http_err = ""
        for _t in range(DETAIL_HTTP_TRIES):
            try:
                html = http_get(sess, href, base_lista)
                last_http_html = html or ""

                if is_detail_loaded(html):
                    reg = parse_detail(html, href)
                    writer.writerow(reg)
                    fcsv.flush()
                    total_ok += 1
                    ok_reg = True
                    break

                last_http_err = "HTTP retornou HTML sem marcadores do imóvel"
                time.sleep(0.25 + random.random() * 0.45)

            except Exception as e:
                last_http_err = f"HTTP exception: {repr(e)}"
                time.sleep(0.25 + random.random() * 0.45)

        if ok_reg:
            if idx % 20 == 0:
                print(f"[ETAPA 2] Progresso: {idx}/{len(links)} | gravados={total_ok}")
            time.sleep(0.02 + random.random() * 0.06)
            continue

        # debug do HTTP
        if last_http_html:
            debug_save("detail_fail_http", idx, href, last_http_err or "HTTP sem motivo", last_http_html)
        else:
            debug_save("detail_fail_http", idx, href, last_http_err or "HTTP sem HTML", None)

        # ---- 2) Selenium
        for _st in range(DETAIL_SELENIUM_TRIES):
            try:
                detail_html = selenium_fetch_detail_resilient(driver, href)

                if looks_blank(detail_html):
                    debug_save("detail_blank", idx, href, "Detalhe branco/não carregou (selenium)", detail_html)
                    print("  [!] (ETAPA 2) Detalhe branco/não carregou. Reabrindo browser e tentando novamente...")
                    time.sleep(BLANK_BACKOFF_BASE + random.random())
                    driver = recover_browser(driver)
                    sess = driver_to_session(driver)
                    continue

                if looks_blocked_detail(detail_html):
                    debug_save("detail_fail_selenium", idx, href, "Sem marcadores/bloqueio real no detalhe (selenium)", detail_html)
                    print("  [!] (ETAPA 2) Detalhe sem marcadores/erro real. Backoff + recicla (fluxo original)...")
                    # recuperação agressiva: 1s -> refresh | +1s -> fecha/reabre
                    driver, _ok = captcha_fast_recover(driver, href, wait_css=("body", "main", "section", "article"))
                    sess = driver_to_session(driver)
                    continue

                reg = parse_detail(detail_html, href)
                writer.writerow(reg)
                fcsv.flush()
                total_ok += 1
                ok_reg = True
                break

            except Exception as e:
                debug_save("detail_exception", idx, href, f"Selenium exception: {repr(e)}", None)
                print(f"  [x] (ETAPA 2) Selenium falhou ({idx}/{len(links)}): {href} -> {repr(e)}")
                time.sleep(DETAIL_BACKOFF_BASE + random.random() * 2)
                driver = recover_browser(driver)
                sess = driver_to_session(driver)

        if idx % 20 == 0:
            print(f"[ETAPA 2] Progresso: {idx}/{len(links)} | gravados={total_ok}")

        time.sleep(0.02 + random.random() * 0.06)

        if idx > 0 and idx % RECICLE_CADA == 0:
            sess = driver_to_session(driver)

    return total_ok, driver


def sanitize_name(name: str) -> str:
    # mantém simples e seguro pra nome de arquivo
    name = name.strip().replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9_\-]+", "", name)
    return name or "job"


# =========================
# main
# =========================
def main():
    # =========================
    # CLI (mac-friendly)
    # =========================
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--headless', action='store_true', help='Rodar Firefox em modo headless')
    ap.add_argument('--max-pages', type=int, default=None, help='Sobrescreve FIM_PAG (limite de páginas)')
    ap.add_argument('--jobs', type=str, default=None, help='(Opcional) Caminho para um arquivo .py com JOBS=...')
    args, _ = ap.parse_known_args()
    # =========================
    # Timer total de execução
    # =========================
    t_start = time.perf_counter()


    global HEADLESS, FIM_PAG, JOBS
    if args.headless:
        HEADLESS = True
    if args.max_pages is not None:
        FIM_PAG = int(args.max_pages)
    if args.jobs:
        jobs_path = Path(args.jobs).expanduser()
        ns = {}
        ns['__file__'] = str(jobs_path)
        exec(jobs_path.read_text(encoding='utf-8'), ns, ns)
        if 'JOBS' in ns and isinstance(ns['JOBS'], list) and ns['JOBS']:
            JOBS = ns['JOBS']
        else:
            raise RuntimeError('Arquivo --jobs não definiu JOBS como list não-vazia')

    if not JOBS:
        print("[x] Nenhum JOB configurado. Descomente pelo menos um item em JOBS.")
        return

    run_date = datetime.now().strftime("%Y%m%d")

    print("Matando instâncias do Firefox...")
    kill_firefox()

    print("Parser BS4:", PARSER)
    print("Perfil base detectado automaticamente:")
    print("  ORIG_PROFILE =", ORIG_PROFILE)

    print("Copiando perfil para pasta temporária...")
    tmp_profile = copy_profile_to_temp(ORIG_PROFILE)

    print("Subindo Firefox...")
    driver = launch_firefox_with_profile(tmp_profile)

    campos = [
        "codigo", "data_coleta", "creci", "anunciante", "oferta", "tipo",
        "area_util", "bairro", "cidade", "preco", "valor_m2", "quartos",
        "vagas", "latitude", "longitude", "quadra", "link",
        "publicado_ha", "aceita_financiamento", "posicao_sol", "posicao_imovel", "descricao",
    ]

    try:
        for job_i, job in enumerate(JOBS, start=1):
            job_name = sanitize_name(job.get("name", f"job_{job_i}"))
            base_lista = job.get("url", "")

            # ----------------------------------------------------------
            # "Pular job comentado"
            # Um JOB só é considerado "ativo" se tiver um bloco completo:
            #  - DF: url + output_dir + diff_output_dir + (debug_root_dir ou debug_dir)
            #  - WI: wi_url/url_wi + wi_output_dir + wi_diff_output_dir + (wi_debug_root_dir ou wi_debug_dir)
            # Se você comentar/chavear campos e deixar o dict vazio/incompleto, ele será ignorado.
            # ----------------------------------------------------------
            wi_base_lista = (job.get("wi_url", "") or job.get("url_wi", "") or "").strip()

            df_ok = bool((base_lista or "").strip()) and bool((job.get("output_dir") or "").strip()) and bool((job.get("diff_output_dir") or "").strip()) and bool((job.get("debug_root_dir") or job.get("debug_dir") or "").strip())
            wi_ok = bool(wi_base_lista) and bool((job.get("wi_output_dir") or "").strip()) and bool((job.get("wi_diff_output_dir") or "").strip()) and bool((job.get("wi_debug_root_dir") or job.get("wi_debug_dir") or "").strip())

            if not df_ok and not wi_ok:
                print(f"[JOB {job_i}/{len(JOBS)}] {job_name} -> ignorado (job incompleto/comentado: sem DF e sem WI).")
                continue

            # =========================
            # Caminhos manuais por JOB
            # =========================
            if df_ok:
                output_dir = ensure_dir(as_path(job["output_dir"]))
                diff_output_dir = ensure_dir(as_path(job["diff_output_dir"]))

                # Arquivos de LINKS/RESULTADO (aceita override com caminho completo)
                arq_links = as_path(job.get("links_csv", str(output_dir / f"dfimoveis_links_{job_name}_{run_date}.csv")))
                arq_saida = as_path(job.get("output_csv", str(output_dir / f"dfimoveis_resultado_{job_name}_{run_date}.csv")))
            else:
                output_dir = None
                diff_output_dir = None
                arq_links = None
                arq_saida = None

            

            wi_base_lista = wi_base_lista
            # WI: o usuário define manualmente as saídas por JOB (mesma filosofia do DF)
            if wi_ok:
                # obrigatórios do WI: wi_output_dir e wi_diff_output_dir (os CSVs são gerados dentro de wi_output_dir)
                if not job.get("wi_output_dir"):
                    raise ValueError(f"[{job_name}] Falta 'wi_output_dir' (pasta de saída do WImoveis) no JOB.")
                if not job.get("wi_diff_output_dir"):
                    raise ValueError(f"[{job_name}] Falta 'wi_diff_output_dir' (pasta de deltas do WImoveis) no JOB.")

                # CSVs do WI: se o usuário não passar caminhos de arquivo, geramos nomes padrão dentro de wi_output_dir
                # (mantendo a sua filosofia: cada JOB tem suas próprias saídas, só que controladas pela pasta).
                wi_output_dir = as_path(job["wi_output_dir"])
                wi_links_csv = as_path(job.get("wi_links_csv", str(wi_output_dir / f"wimoveis_links_{job_name}_{run_date}.csv")))
                wi_output_csv = as_path(job.get("wi_output_csv", str(wi_output_dir / f"wimoveis_resultado_{job_name}_{run_date}.csv")))


                # debug do WI (um dos dois é obrigatório)
                if not job.get("wi_debug_dir") and not job.get("wi_debug_root_dir"):
                    raise ValueError(
                        f"[{job_name}] Falta 'wi_debug_root_dir' (pasta raiz de debug do WI) ou 'wi_debug_dir' (pasta completa de debug do WI) no JOB."
                    )
                wi_output_dir = ensure_dir(as_path(job["wi_output_dir"]))
                wi_diff_output_dir = ensure_dir(as_path(job["wi_diff_output_dir"]))
                arq_links_wi = wi_links_csv
                arq_saida_wi = wi_output_csv
            else:
                wi_output_dir = None
                wi_diff_output_dir = None
                arq_links_wi = None
                arq_saida_wi = None

            # DEBUG_DIR (aceita override com caminho completo)
            global DEBUG_DIR
            df_debug_dir = None
            wi_debug_dir = None
            if df_ok:
                if job.get("debug_dir"):
                    DEBUG_DIR = ensure_dir(as_path(job["debug_dir"]))
                else:
                    debug_root_dir = ensure_dir(as_path(job["debug_root_dir"]))
                    DEBUG_DIR = ensure_dir(debug_root_dir / f"debug_detalhes_{job_name}_{run_date}")
                df_debug_dir = DEBUG_DIR
            else:
                # Se DF estiver desligado, usa um debug "neutro" só para evitar crash.
                # O WI define seu próprio DEBUG_DIR mais abaixo quando wi_ok=True.
                DEBUG_DIR = ensure_dir(as_path(job.get("wi_debug_root_dir") or job.get("wi_debug_dir") or str(BASE_DIR)))

            print("\n" + "=" * 78)
            print(f"[JOB {job_i}/{len(JOBS)}] {job_name} | {base_lista}")
            print(f"  LINKS: {arq_links.name if arq_links else '-'}")
            print(f"  SAIDA: {arq_saida.name if arq_saida else '-'}")
            print(f"  DEBUG: {DEBUG_DIR.name}")
            print("=" * 78)

            # (opcional mas recomendado) reciclar o browser no início de cada job
            # para reduzir “contaminação” de sessão / bloqueios acumulados:
            driver = recover_browser(driver)

            if df_ok:
                # Abre CSV de saída (cada job tem o seu)
                primeira_saida = not arq_saida.exists()
                fcsv = open(arq_saida, "a", newline="", encoding="utf-8", buffering=1024 * 1024)
                writer = csv.DictWriter(fcsv, fieldnames=campos)
                if primeira_saida:
                    writer.writeheader()
                    fcsv.flush()

                try:
                    links, driver = etapa1_coletar_links(driver, base_lista, arq_links)
                    print(f"\n[ETAPA 1] Total de links coletados: {len(links)}")

                    if not links:
                        print("[x] Nenhum link coletado neste JOB. Pulando para o próximo.")
                        # Fecha o CSV e pula para WI/Próximo
                        continue

                    print("\n[ETAPA 2] Extraindo detalhes (com debug automático)...")
                    total, driver = etapa2_extrair_detalhes(driver, links, writer, fcsv, base_lista)

                    print(f"\n[✓] DF concluído: {job_name}")
                    print(f"    Total de anúncios gravados: {total}")
                    print(f"    CSV:   {arq_saida.name}")
                    print(f"    LINKS: {arq_links.name}")
                    print(f"    DEBUG: {DEBUG_DIR.name}")

                finally:
                    try:
                        fcsv.close()
                    except Exception:
                        pass
            else:
                print("[DF] Bloco DF comentado/incompleto -> pulando DFImoveis neste JOB.")

            # =========================
            # WIMOVEIS (ImovelWeb)
            # Executa APÓS concluir DFImoveis neste mesmo JOB.
            # =========================
            wi_total = None
            if wi_ok:
                print("\n" + "-" * 78)
                print(f"[WIMOVEIS] {job_name} | {wi_base_lista}")
                print(f"  LINKS: {arq_links_wi.name}")
                print(f"  SAIDA: {arq_saida_wi.name}")
                print("-" * 78)

                # recicla o browser no início do WI para reduzir bloqueios
                driver = recover_browser(driver)

                # DEBUG_DIR separado (WI)
                if job.get("wi_debug_dir"):
                    DEBUG_DIR = ensure_dir(as_path(job["wi_debug_dir"]))
                else:
                    debug_root_dir = ensure_dir(as_path(job["wi_debug_root_dir"]))
                    DEBUG_DIR = ensure_dir(debug_root_dir / f"debug_wimoveis_{job_name}_{run_date}")
                wi_debug_dir = DEBUG_DIR

                primeira_saida_wi = not arq_saida_wi.exists()
                fcsv_wi = open(arq_saida_wi, "a", newline="", encoding="utf-8", buffering=1024 * 1024)
                writer_wi = csv.DictWriter(fcsv_wi, fieldnames=campos)
                if primeira_saida_wi:
                    writer_wi.writeheader()
                    fcsv_wi.flush()

                try:
                    links_wi, driver = etapa1_coletar_links_wimoveis(driver, wi_base_lista, arq_links_wi)
                    print(f"\n[ETAPA 1 - WI] Total de links coletados: {len(links_wi)}")

                    if not links_wi:
                        print("[x] Nenhum link coletado no WI neste JOB. Pulando WI.")
                    else:
                        print("\n[ETAPA 2 - WI] Extraindo detalhes (com debug automático)...")
                        wi_total, driver = etapa2_extrair_detalhes_wimoveis(driver, links_wi, writer_wi, fcsv_wi, wi_base_lista)

                        print(f"\n[✓] WIMOVEIS concluído: {job_name}")
                        print(f"    Total de anúncios gravados: {wi_total}")
                        print(f"    CSV:   {arq_saida_wi.name}")
                        print(f"    LINKS: {arq_links_wi.name}")
                        print(f"    DEBUG: {DEBUG_DIR.name}")

                finally:
                    try:
                        fcsv_wi.close()
                    except Exception:
                        pass

            # =========================
            # COMPARAÇÃO com coleta anterior
            # (gera CSVs de entradas/saídas em diff_output_dir)
            # =========================
            try:
                gerar_deltas_entradas_saidas(
                    prefix="dfimoveis",
                    job_name=job_name,
                    arq_saida_atual=arq_saida,
                    diff_output_dir=diff_output_dir,
                    codigo_col="codigo",
                )
            except Exception as e:
                print(f"[!] Falha ao gerar comparação (entradas/saídas) para {job_name}: {e}")
            # (WI) comparação
            if wi_base_lista and arq_saida_wi:
                try:
                    gerar_deltas_entradas_saidas(
                        prefix="wimoveis",
                        job_name=job_name,
                        arq_saida_atual=arq_saida_wi,
                        diff_output_dir=wi_diff_output_dir,
                        codigo_col="codigo",
                    )
                except Exception as e:
                    print(f"[!] Falha ao gerar comparação (WI) para {job_name}: {e}")

            # =========================
            # LIMPEZA: remove artefatos temporários (debug + CSV de links)
            # Mantém apenas: coletas (resultado_*.csv) e comparações (entradas/saídas)
            # =========================
            try:
                if arq_links:
                    _safe_unlink(as_path(arq_links))
                if arq_links_wi:
                    _safe_unlink(as_path(arq_links_wi))
                if df_debug_dir:
                    _safe_rmtree(as_path(df_debug_dir), job_name, run_date)
                if wi_debug_dir:
                    _safe_rmtree(as_path(wi_debug_dir), job_name, run_date)
            except Exception:
                pass

        print("\nTodos os JOBS finalizados.")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

        # Tempo total
        try:
            t_total = time.perf_counter() - t_start
            hh = int(t_total // 3600)
            mm = int((t_total % 3600) // 60)
            ss = int(t_total % 60)
            print(f"\n[TIMER] Tempo total: {hh:02d}:{mm:02d}:{ss:02d} (hh:mm:ss)")
        except Exception:
            pass




# ==========================================================
# COMPARAÇÃO: coleta atual vs coleta anterior (por JOB)
# Gera dois CSVs:
#   - dfimoveis_resultado_saidas_{job}_{data_atual}.csv  (linhas do arquivo anterior)
#   - dfimoveis_resultado_entradas_{job}_{data_atual}.csv (linhas do arquivo atual)
# A comparação é feita pela coluna "codigo".
# ==========================================================
def _extract_run_date_from_result_filename(*args) -> str | None:
    """Extrai YYYYMMDD do nome do CSV de resultado.

    Compatível com as duas assinaturas (para não quebrar chamadas antigas):
      - (job_name, filename)                -> assume prefix='dfimoveis'
      - (prefix, job_name, filename)        -> usa o prefix informado ('dfimoveis' ou 'wimoveis')
    """
    if len(args) == 2:
        prefix_site = "dfimoveis"
        job_name, filename = args
    elif len(args) == 3:
        prefix_site, job_name, filename = args
    else:
        raise TypeError(f"_extract_run_date_from_result_filename() esperado 2 ou 3 args, recebeu {len(args)}")

    prefix_site = str(prefix_site).strip()
    job_name = str(job_name).strip()

    expected_prefix = f"{prefix_site}_resultado_{job_name}_"
    filename = str(filename)

    if not (filename.startswith(expected_prefix) and filename.endswith(".csv")):
        return None

    tail = filename[len(expected_prefix):-4].strip()  # remove prefix e ".csv"
    if len(tail) >= 8 and tail[:8].isdigit():
        return tail[:8]
    return None


def _find_previous_result_file(*args) -> Path | None:
    """Encontra o arquivo de resultado imediatamente anterior (por data no nome).

    Compatível com duas assinaturas:
      - (job_name, current_date_yyyymmdd, search_dir)              -> assume prefix='dfimoveis'
      - (prefix, job_name, current_date_yyyymmdd, search_dir)      -> usa prefix informado
    """
    if len(args) == 3:
        prefix_site = "dfimoveis"
        job_name, current_date_yyyymmdd, search_dir = args
    elif len(args) == 4:
        prefix_site, job_name, current_date_yyyymmdd, search_dir = args
    else:
        raise TypeError(f"_find_previous_result_file() esperado 3 ou 4 args, recebeu {len(args)}")

    prefix_site = str(prefix_site).strip()
    job_name = str(job_name).strip()
    current_date_yyyymmdd = str(current_date_yyyymmdd).strip()
    search_dir = Path(search_dir)

    prefix = f"{prefix_site}_resultado_{job_name}_"
    best: tuple[str, Path] | None = None  # (date_str, path)

    for p in search_dir.glob(f"{prefix}*.csv"):
        date_str = _extract_run_date_from_result_filename(prefix_site, job_name, p.name)
        if not date_str:
            continue
        if date_str >= current_date_yyyymmdd:
            continue
        if best is None or date_str > best[0]:
            best = (date_str, p)

    return best[1] if best else None


def _read_codes(csv_path: Path, codigo_col: str) -> set[str]:
    codes: set[str] = set()
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return codes
        if codigo_col not in reader.fieldnames:
            raise RuntimeError(f"Coluna '{codigo_col}' não encontrada em {csv_path.name}. Colunas: {reader.fieldnames}")
        for row in reader:
            c = (row.get(codigo_col) or "").strip()
            if c:
                codes.add(c)
    return codes


def _write_rows_by_code(source_csv: Path, dest_csv: Path, codigo_col: str, codes_to_keep: set[str]) -> int:
    wrote = 0
    with open(source_csv, "r", newline="", encoding="utf-8") as fin:
        reader = csv.DictReader(fin)
        fieldnames = reader.fieldnames or []
        if not fieldnames:
            # cria arquivo vazio
            dest_csv.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_csv, "w", newline="", encoding="utf-8") as fout:
                fout.write("")
            return 0

        if codigo_col not in fieldnames:
            raise RuntimeError(f"Coluna '{codigo_col}' não encontrada em {source_csv.name}. Colunas: {fieldnames}")

        dest_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_csv, "w", newline="", encoding="utf-8") as fout:
            writer = csv.DictWriter(fout, fieldnames=fieldnames)
            writer.writeheader()
            for row in reader:
                c = (row.get(codigo_col) or "").strip()
                if c and c in codes_to_keep:
                    writer.writerow(row)
                    wrote += 1
    return wrote


def gerar_deltas_entradas_saidas(
    prefix: str,
    job_name: str,
    arq_saida_atual: str | Path,
    diff_output_dir: str | Path,
    codigo_col: str = "codigo",
) -> None:
    """Compara a coleta atual com a imediatamente anterior e gera CSVs de entradas/saídas.

    prefix: "dfimoveis" ou "wimoveis" (usado para padronizar nomes).
    """
    arq_saida_atual = as_path(arq_saida_atual)
    diff_output_dir = ensure_dir(diff_output_dir)

    if not arq_saida_atual.exists():
        print(f"  [Δ] (skip) CSV atual não encontrado: {arq_saida_atual}")
        return

    run_date = _extract_run_date_from_result_filename(prefix, job_name, arq_saida_atual.name)
    if not run_date:
        # fallback: tenta usar a data atual do sistema
        run_date = datetime.now().strftime("%Y%m%d")

    prev = _find_previous_result_file(prefix, job_name, run_date, arq_saida_atual.parent)
    if not prev:
        print("  [Δ] (skip) Nenhuma coleta anterior encontrada para comparação.")
        return

    # 1) listas de códigos
    prev_codes = _read_codes(prev, codigo_col)
    curr_codes = _read_codes(arq_saida_atual, codigo_col)

    saidas = prev_codes - curr_codes
    entradas = curr_codes - prev_codes

    # 2) nomes dos arquivos de saída
    out_saidas = diff_output_dir / f"{prefix}_resultado_saidas_{job_name}_{run_date}.csv"
    out_entradas = diff_output_dir / f"{prefix}_resultado_entradas_{job_name}_{run_date}.csv"

    # 3) escreve linhas correspondentes
    wrote_saidas = _write_rows_by_code(prev, out_saidas, codigo_col, saidas) if saidas else _write_rows_by_code(prev, out_saidas, codigo_col, set())
    wrote_entradas = _write_rows_by_code(arq_saida_atual, out_entradas, codigo_col, entradas) if entradas else _write_rows_by_code(arq_saida_atual, out_entradas, codigo_col, set())

    print(f"  [Δ] ({prefix}) Comparação por '{codigo_col}': anterior={prev.name} | atual={arq_saida_atual.name}")
    print(f"      Saídas   (ontem→hoje): {len(saidas)} | linhas gravadas: {wrote_saidas}")
    print(f"      Entradas (hoje→ontem): {len(entradas)} | linhas gravadas: {wrote_entradas}")
    print(f"      CSV saídas:   {out_saidas}")
    print(f"      CSV entradas: {out_entradas}")


if __name__ == "__main__":
    main()
