import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

import requests


logger = logging.getLogger("evidencia_web")

STORAGE_BASE = Path("storage") / "evidencias"
SCREENSHOT_BASE = Path("storage") / "screenshots"


def _slug(valor):
    digest = hashlib.sha1(str(valor or "").encode("utf-8")).hexdigest()[:12]
    return f"item_{digest}"


def _dominio_amplo(fonte, url):
    texto = f"{fonte or ''} {url or ''}".lower()
    if not url:
        return False
    oficiais = ["pncp.gov.br", "tce.rs.gov.br", "compras.gov.br", "licitacon"]
    return not any(oficial in texto for oficial in oficiais)


def _extrair_titulo(html):
    inicio = html.lower().find("<title")
    if inicio < 0:
        return ""
    inicio = html.find(">", inicio)
    fim = html.lower().find("</title>", inicio)
    if inicio < 0 or fim < 0:
        return ""
    return html[inicio + 1:fim].strip()[:240]


def _salvar_screenshot_playwright(url, destino):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False, "playwright_indisponivel"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1366, "height": 900})
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.screenshot(path=str(destino), full_page=True)
            browser.close()
        return True, ""
    except Exception as erro:
        return False, str(erro)


def capturar_evidencia_web(*, url, fonte="", titulo="", preco="", item_uid=""):
    if not _dominio_amplo(fonte, url):
        return None

    pasta = STORAGE_BASE / (item_uid or _slug(url))
    pasta.mkdir(parents=True, exist_ok=True)
    screenshot_dir = SCREENSHOT_BASE / (item_uid or _slug(url))
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = pasta / "metadata.json"
    html_path = pasta / "html.html"
    screenshot_path = screenshot_dir / "screenshot.png"
    capturado_em = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = ""
    erro = ""

    try:
        resposta = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 PesquisaPrecos/1.0"})
        resposta.raise_for_status()
        html = resposta.text[:800000]
        html_path.write_text(html, encoding="utf-8", errors="ignore")
    except Exception as exc:
        erro = str(exc)
        html_path.write_text("", encoding="utf-8")

    screenshot_ok, screenshot_erro = _salvar_screenshot_playwright(url, screenshot_path)
    if not screenshot_ok:
        erro = " | ".join(parte for parte in [erro, screenshot_erro] if parte)

    metadata = {
        "url": url,
        "titulo": titulo or _extrair_titulo(html),
        "preco": preco,
        "data_captura": capturado_em,
        "fonte": fonte,
        "html": str(html_path),
        "screenshot": str(screenshot_path) if screenshot_ok else "",
        "screenshot_status": "ok" if screenshot_ok else "indisponivel",
        "erro": erro,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "[evidencia_web] url=%s fonte=%s pasta=%s screenshot=%s erro=%s",
        url,
        fonte,
        pasta,
        metadata["screenshot_status"],
        erro,
    )
    return {
        "pasta": str(pasta),
        "metadata": str(metadata_path),
        "html": str(html_path),
        "screenshot": metadata["screenshot"],
        "dados": metadata,
    }
