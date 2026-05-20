import hashlib
import json
import logging
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from config.runtime_settings import (
    DEBUG_PNCP,
    PNCP_BACKOFF_MAX_SECONDS,
    PNCP_DEBUG_FOLDER,
    PNCP_DEBUG_PAYLOADS,
    PNCP_MAX_WORKERS,
)

logger = logging.getLogger("pncp")


class PNCPClientError(RuntimeError):
    pass


class PNCPClient:
    BASE_CONSULTA = "https://pncp.gov.br/api/consulta"
    BASE_PNCP = "https://pncp.gov.br/api/pncp"
    USER_AGENT = "pesquisa-precos-publicos/1.0"
    _semaphore = threading.BoundedSemaphore(max(1, PNCP_MAX_WORKERS))
    _cooldown_lock = threading.Lock()
    _desabilitado_ate = 0

    def __init__(
        self,
        *,
        timeout=15,
        retries=2,
        cache_path="storage/cache/pncp_cache.sqlite",
        cache_ttl_seconds=86400,
        session=None,
    ):
        self.timeout = timeout
        self.retries = retries
        self.cache_path = Path(cache_path)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.session = session or requests.Session()

    def _endpoint_label(self, url):
        if "contratacoes" in url:
            return "contratacoes"
        if url.endswith("/itens") or "/itens" in url:
            return "itens"
        return "pncp"

    def _salvar_payload_debug(self, url, params, status_code, payload):
        if not PNCP_DEBUG_PAYLOADS:
            return
        try:
            pasta = Path(PNCP_DEBUG_FOLDER)
            pasta.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            label = self._endpoint_label(url)
            caminho = pasta / f"{timestamp}_{label}.json"
            conteudo = {
                "endpoint": url,
                "params": params or {},
                "status_code": int(status_code),
                "response": payload,
            }
            caminho.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as erro:
            logger.warning("Falha ao salvar debug PNCP url=%s erro=%s", url, erro)

    @classmethod
    def pncp_temporariamente_desativado(cls):
        return time.time() < cls._desabilitado_ate

    @classmethod
    def status_pncp_local(cls):
        return "rate_limited" if cls.pncp_temporariamente_desativado() else "ok"

    @classmethod
    def _pausar_por_rate_limit(cls, segundos=60):
        with cls._cooldown_lock:
            cls._desabilitado_ate = max(cls._desabilitado_ate, time.time() + segundos)
        logger.warning("PNCP pausa automatica por rate limit segundos=%s", segundos)

    def _backoff(self, tentativa):
        return min(PNCP_BACKOFF_MAX_SECONDS, 0.75 * (2 ** max(0, tentativa - 1)))

    def _cache_enabled(self):
        return self.cache_ttl_seconds and self.cache_ttl_seconds > 0

    def _cache_key(self, method, url, params):
        payload = json.dumps(
            {"method": method, "url": url, "params": params or {}},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _connect_cache(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.cache_path)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_pncp (
                cache_key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                params_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        con.commit()
        return con

    def _get_cache(self, key):
        if not self._cache_enabled():
            return None
        try:
            with self._connect_cache() as con:
                row = con.execute(
                    "SELECT response_json, created_at FROM cache_pncp WHERE cache_key = ?",
                    (key,),
                ).fetchone()
            if not row:
                return None
            response_json, created_at = row
            if time.time() - float(created_at) > self.cache_ttl_seconds:
                return None
            return json.loads(response_json)
        except Exception as erro:
            logger.warning("Falha ao ler cache PNCP: %s", erro)
            return None

    def _set_cache(self, key, url, params, status_code, payload):
        if not self._cache_enabled():
            return
        try:
            with self._connect_cache() as con:
                con.execute(
                    """
                    INSERT OR REPLACE INTO cache_pncp
                    (cache_key, url, params_json, response_json, status_code, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        key,
                        url,
                        json.dumps(params or {}, sort_keys=True, ensure_ascii=False),
                        json.dumps(payload, ensure_ascii=False),
                        int(status_code),
                        time.time(),
                    ),
                )
                con.commit()
        except Exception as erro:
            logger.warning("Falha ao gravar cache PNCP: %s", erro)

    def _request_json(self, url, params=None):
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        cache_key = self._cache_key("GET", url, params)
        cached = self._get_cache(cache_key)
        if cached is not None:
            logger.debug("PNCP cache_hit url=%s params=%s", url, params)
            return cached
        if self.pncp_temporariamente_desativado():
            raise PNCPClientError("PNCP temporariamente pausado por rate limit")

        headers = {
            "Accept": "application/json",
            "User-Agent": self.USER_AGENT,
        }
        ultimo_erro = None
        inicio = time.perf_counter()

        with self._semaphore:
            for tentativa in range(1, self.retries + 2):
                try:
                    resposta = self.session.get(
                        url,
                        params=params,
                        headers=headers,
                        timeout=(5, self.timeout),
                    )
                    if resposta.status_code == 429:
                        self._pausar_por_rate_limit()
                    if resposta.status_code in {429, 500, 502, 503, 504} and tentativa <= self.retries:
                        pausa = self._backoff(tentativa)
                        logger.warning(
                            "PNCP retry url=%s params=%s status=%s tentativa=%s pausa_s=%s",
                            url,
                            params,
                            resposta.status_code,
                            tentativa,
                            pausa,
                        )
                        time.sleep(pausa)
                        continue
                    resposta.raise_for_status()
                    if resposta.status_code == 204 or not resposta.text.strip():
                        payload = []
                    else:
                        payload = resposta.json()
                    self._salvar_payload_debug(resposta.url, params, resposta.status_code, payload)
                    self._set_cache(cache_key, resposta.url, params, resposta.status_code, payload)
                    quantidade = len(payload.get("data", [])) if isinstance(payload, dict) else len(payload or [])
                    logger.debug(
                        "PNCP GET url=%s endpoint=%s params=%s status=%s quantidade=%s tempo_ms=%s retries=%s",
                        resposta.url,
                        url,
                        params,
                        resposta.status_code,
                        quantidade,
                        round((time.perf_counter() - inicio) * 1000, 2),
                        tentativa - 1,
                    )
                    if DEBUG_PNCP:
                        logger.debug("PNCP payload_tipo=%s url=%s", type(payload).__name__, resposta.url)
                    return payload
                except (requests.Timeout, requests.ConnectionError) as erro:
                    ultimo_erro = erro
                    logger.warning("PNCP timeout/conexao url=%s params=%s tentativa=%s erro=%s", url, params, tentativa, erro)
                    if tentativa <= self.retries:
                        time.sleep(self._backoff(tentativa))
                except requests.RequestException as erro:
                    ultimo_erro = erro
                    status = getattr(getattr(erro, "response", None), "status_code", 0) or 0
                    payload_erro = {}
                    resposta_erro = getattr(erro, "response", None)
                    if resposta_erro is not None:
                        try:
                            payload_erro = resposta_erro.json()
                        except ValueError:
                            payload_erro = {"text": resposta_erro.text[:2000]}
                    self._salvar_payload_debug(url, params, status, payload_erro)
                    logger.warning("PNCP erro_http url=%s params=%s tentativa=%s erro=%s", url, params, tentativa, erro)
                    if tentativa <= self.retries:
                        time.sleep(self._backoff(tentativa))

        logger.warning("PNCP indisponivel url=%s params=%s erro=%s", url, params, ultimo_erro)
        raise PNCPClientError(str(ultimo_erro))

    @staticmethod
    def _yyyymmdd(valor):
        if isinstance(valor, date):
            return valor.strftime("%Y%m%d")
        return str(valor).replace("-", "")

    def consultar_contratacoes_proposta(
        self,
        *,
        data_final=None,
        data_inicial=None,
        codigo_modalidade=8,
        pagina=1,
        uf=None,
        codigo_municipio_ibge=None,
        cnpj=None,
        tamanho_pagina=None,
    ):
        params = {
            "dataFinal": self._yyyymmdd(data_final or date.today()),
            "dataInicial": self._yyyymmdd(data_inicial) if data_inicial else None,
            "codigoModalidadeContratacao": codigo_modalidade,
            "pagina": pagina,
            "uf": uf,
            "codigoMunicipioIbge": codigo_municipio_ibge,
            "cnpj": cnpj,
            "tamanhoPagina": tamanho_pagina,
        }
        return self._request_json(
            f"{self.BASE_CONSULTA}/v1/contratacoes/proposta",
            params=params,
        )

    def consultar_contratacoes_publicacao(
        self,
        *,
        data_inicial,
        data_final,
        codigo_modalidade=8,
        pagina=1,
        uf=None,
        codigo_municipio_ibge=None,
        cnpj=None,
        tamanho_pagina=None,
    ):
        params = {
            "dataInicial": self._yyyymmdd(data_inicial),
            "dataFinal": self._yyyymmdd(data_final),
            "codigoModalidadeContratacao": codigo_modalidade,
            "pagina": pagina,
            "uf": uf,
            "codigoMunicipioIbge": codigo_municipio_ibge,
            "cnpj": cnpj,
            "tamanhoPagina": tamanho_pagina,
        }
        return self._request_json(
            f"{self.BASE_CONSULTA}/v1/contratacoes/publicacao",
            params=params,
        )

    def listar_itens_compra(self, cnpj, ano_compra, sequencial_compra):
        return self._request_json(
            f"{self.BASE_PNCP}/v1/orgaos/{cnpj}/compras/{ano_compra}/{sequencial_compra}/itens"
        )

    def listar_resultados_item(self, cnpj, ano_compra, sequencial_compra, numero_item):
        return self._request_json(
            f"{self.BASE_PNCP}/v1/orgaos/{cnpj}/compras/{ano_compra}/{sequencial_compra}/itens/{numero_item}/resultados"
        )

    def buscar_contratacoes(
        self,
        *,
        dias=180,
        modalidades=(8, 6, 7, 9, 5),
        max_paginas=1,
        tipo_consulta="proposta",
        uf=None,
        codigo_municipio_ibge=None,
        cnpj=None,
        tamanho_pagina=None,
    ):
        data_final = date.today()
        data_inicial = data_final - timedelta(days=int(dias))
        resultados = []

        for modalidade in modalidades:
            for pagina in range(1, int(max_paginas) + 1):
                if tipo_consulta == "publicacao":
                    payload = self.consultar_contratacoes_publicacao(
                        data_inicial=data_inicial,
                        data_final=data_final,
                        codigo_modalidade=modalidade,
                        pagina=pagina,
                        uf=uf,
                        codigo_municipio_ibge=codigo_municipio_ibge,
                        cnpj=cnpj,
                        tamanho_pagina=tamanho_pagina,
                    )
                else:
                    payload = self.consultar_contratacoes_proposta(
                        data_inicial=data_inicial,
                        data_final=data_final,
                        codigo_modalidade=modalidade,
                        pagina=pagina,
                        uf=uf,
                        codigo_municipio_ibge=codigo_municipio_ibge,
                        cnpj=cnpj,
                        tamanho_pagina=tamanho_pagina,
                    )
                dados = payload.get("data", []) if isinstance(payload, dict) else []
                resultados.extend(dados)
                if not dados:
                    break

        return resultados
