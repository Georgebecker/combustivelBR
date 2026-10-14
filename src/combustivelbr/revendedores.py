"""Autorizações de revenda (API pública da ANP): quantos postos existem em cada UF.

É o denominador dos indicadores de fiscalização — "ações por posto ativo" só faz
sentido com o número de postos ativos. A API não autentica, mas limita a taxa de
requisição: daí a espera progressiva e a retomada por UF já baixada.

O campo ``statusSIGAF`` existe no contrato e vem **vazio** em todas as linhas
(verificado em 45.762 postos, 12/10/2026): não serve para dizer quem está
interditado. Interdição de verdade sai do arquivo de fiscalização.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from pathlib import Path

import requests

from . import config

COLUNAS = (
    "uf",
    "municipio",
    "cnpj",
    "razao_social",
    "autorizacao",
    "distribuidora",
    "situacao",
    "latitude",
    "longitude",
)


class FalhaDeRevendedores(RuntimeError):
    """A API de revendedores não respondeu como esperado."""


def _get(url: str, parametros: dict, tentativas: int | None = None) -> dict:
    """GET com espera progressiva: a API responde 429 quando chamada em sequência."""
    tentativas = tentativas or config.REVENDEDORES_TENTATIVAS
    espera = config.REVENDEDORES_ESPERA_SEGUNDOS
    ultimo_erro = ""

    for _ in range(tentativas):
        try:
            resposta = requests.get(
                url,
                params=parametros,
                timeout=config.REVENDEDORES_TIMEOUT_SEGUNDOS,
                headers={"User-Agent": config.USER_AGENT},
            )
            if resposta.status_code in config.REVENDEDORES_ESPERA_CODIGOS:
                ultimo_erro = f"HTTP {resposta.status_code}"
                time.sleep(espera)
                espera *= 2
                continue
            resposta.raise_for_status()
            return resposta.json()
        except (requests.RequestException, ValueError) as erro:
            ultimo_erro = f"{type(erro).__name__}: {erro}"
            time.sleep(espera)
            espera *= 2

    raise FalhaDeRevendedores(f"{url} ({parametros}): desisti após {tentativas} tentativas — {ultimo_erro}")


def baixar(uf: str, destino: Path | None = None) -> Path:
    """Baixa todas as páginas de uma UF e grava o bruto como veio (prova)."""
    registros: list[dict] = []
    pagina = 1
    while True:
        corpo = _get(config.REVENDEDORES_URL, {"uf": uf, "numeropagina": pagina})
        lote = corpo.get("data") or []
        registros.extend(lote)
        filtro = corpo.get("searchPageFilter") or {}
        if pagina >= (filtro.get("totalPagina") or 1) or not lote:
            break
        pagina += 1

    destino = destino or config.DATA_RAW / f"{config.carimbo()}-revendedores-{uf}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(registros, ensure_ascii=False), encoding="utf-8")
    return destino


def ler(uf: str) -> list[dict]:
    """Bruto já baixado de uma UF (a prova guardada em ``config.DATA_RAW``).

    Procura o arquivo **mais recente** da UF, não o de hoje: rodar a análise no dia seguinte
    à coleta é o caso normal, e montar o nome com a data corrente devolveria lista vazia.
    """
    caminho = _mais_recente(uf)
    if caminho is None:
        return []
    return json.loads(caminho.read_text(encoding="utf-8"))


def _mais_recente(uf: str) -> Path | None:
    """Arquivo de revendedores mais recente da UF (``None`` se não houver nenhum).

    O nome começa pela data de coleta, então a ordem alfabética é a ordem cronológica.
    """
    arquivos = sorted(config.DATA_RAW.glob(f"*-revendedores-{uf}.json"))
    return arquivos[-1] if arquivos else None


def ler_ufs(ufs: Iterable[str] | None = None) -> list[dict]:
    """Registros de todas as UFs baixadas (ou das UFs pedidas)."""
    registros: list[dict] = []
    for uf in ufs or config.UFS:
        registros.extend(ler(uf))
    return registros


def normalizar(registros: Iterable[dict]) -> list[dict]:
    """Só o que o indicador usa, com CNPJ sempre em dígitos."""
    limpos = []
    for registro in registros:
        limpos.append(
            {
                "uf": str(registro.get("uf") or "").strip().upper(),
                # Mesma chave de junção das outras bases (sem acento, maiúscula): sem isso
                # "São Paulo" aqui e "SAO PAULO" na fiscalização seriam dois municípios.
                "municipio": config.normalizar_texto(registro.get("municipio") or ""),
                "cnpj": "".join(ch for ch in str(registro.get("cnpj") or "") if ch.isdigit()),
                "razao_social": str(registro.get("razaoSocial") or "").strip(),
                "autorizacao": str(registro.get("autorizacao") or "").strip(),
                "distribuidora": str(registro.get("distribuidora") or "").strip(),
                "situacao": str(registro.get("situacaoConstatada") or "").strip(),
                "latitude": registro.get("latitude") or registro.get("latitude_ANP4C"),
                "longitude": registro.get("longitude") or registro.get("longitude_ANP4C"),
            }
        )
    return limpos


def postos_por_uf(registros: Iterable[dict]) -> dict[str, int]:
    """Quantos postos ativos cada UF tem (denominador do IPF)."""
    contagem: dict[str, int] = {}
    for registro in registros:
        uf = str(registro.get("uf") or "").strip().upper()
        if uf:
            contagem[uf] = contagem.get(uf, 0) + 1
    return contagem
