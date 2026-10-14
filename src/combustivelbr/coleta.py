"""Coleta do dado bruto: baixa da fonte pública e guarda intacto em ``data/raw/``.

Regra do projeto: o que está em ``data/raw/`` é prova — nunca é editado, limpo ou corrigido.
Qualquer ajuste de formato/valor acontece em :mod:`combustivelbr.transformacao`.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import requests

from . import config

# Como o arquivo de amostra termina: ele fica fora do recorte real.
SUFIXO_AMOSTRA = "-amostra.csv"

# Nome dos arquivos da fonte principal: começa pela data completa (``AAAA-MM-DD``). A série
# mensal da fase 2 começa pelo mês (``AAAA-MM-``) e é lida por ``historico.py`` — sem separar
# as duas famílias, o resumo do site publicaria a série inteira no ``dados.json``.
PADRAO_DA_FONTE = re.compile(r"^\d{4}-\d{2}-\d{2}-")


class FalhaDeColeta(RuntimeError):
    """Falha previsível de coleta: rede, status inesperado ou resposta vazia."""


def carimbo(agora: datetime | None = None) -> str:
    """Data local (America/Sao_Paulo) no formato usado nos nomes de arquivo."""
    return config.carimbo(agora)


def baixar(url: str | None = None, destino: Path | None = None) -> Path:
    """Baixa o arquivo público da fonte e grava os bytes como vieram.

    O que já está guardado não é baixado de novo: o bruto é a prova do que a fonte publicou, e
    duas execuções no mesmo dia não podem reescrevê-la. Para forçar a coleta, apague o arquivo.
    """
    url = url or config.FONTE_URL
    config.garantir_diretorios()
    destino = destino or config.DATA_RAW / f"{carimbo()}-precos.csv"

    if destino.exists() and destino.stat().st_size > 0:
        return destino

    try:
        resposta = requests.get(
            url,
            timeout=config.TIMEOUT_SEGUNDOS,
            headers={"User-Agent": config.USER_AGENT, "Accept": "text/csv,*/*"},
        )
    except requests.RequestException as erro:
        raise FalhaDeColeta(f"falha de conexão com {url}: {erro}") from erro

    if resposta.status_code != 200:
        raise FalhaDeColeta(f"{url} respondeu HTTP {resposta.status_code}")
    if not resposta.content.strip():
        raise FalhaDeColeta(f"{url} respondeu vazio")

    destino.write_bytes(resposta.content)
    return destino


def baixar_fontes(
    fontes: Sequence[tuple[str, str]] | None = None, destino_dir: Path | None = None
) -> list[Path]:
    """Baixa cada arquivo público de ``config.FONTES_DADOS`` para a pasta do bruto.

    Um arquivo por grupo de produto; o mesmo carimbo de data os mantém juntos.
    """
    destino_dir = destino_dir or config.DATA_RAW
    arquivos = []
    for nome, url in fontes or config.FONTES_DADOS:
        arquivos.append(baixar(url, destino_dir / f"{carimbo()}-{nome}.csv"))
    return arquivos


def usar_amostra(origem: Path | None = None, destino: Path | None = None) -> Path:
    """Copia uma amostra local para ``data/raw/`` (testes e trabalho offline)."""
    origem = origem or config.RAIZ / "tests" / "fixtures" / "amostra_precos.csv"
    if not origem.exists():
        raise FalhaDeColeta(f"amostra não encontrada: {origem}")

    config.garantir_diretorios()
    destino = destino or config.DATA_RAW / f"{carimbo()}-amostra.csv"
    shutil.copyfile(origem, destino)
    return destino


def brutos() -> list[Path]:
    """Todos os brutos da pasta, em ordem crescente de nome (o nome começa pela data)."""
    return sorted(config.DATA_RAW.glob("*.csv"))


def brutos_da_fonte() -> list[Path]:
    """Brutos da fonte principal, sem a amostra local e sem a série mensal da fase 2.

    A amostra é semente de teste, não dado; e a série mensal (``AAAA-MM-precos-*.csv``) é
    insumo de :mod:`combustivelbr.historico`, não do resumo do site.
    """
    return [
        arquivo
        for arquivo in brutos()
        if not arquivo.name.endswith(SUFIXO_AMOSTRA) and PADRAO_DA_FONTE.match(arquivo.name)
    ]


def ultimo_bruto() -> Path | None:
    """Arquivo mais recente em ``data/raw/`` (``None`` quando a pasta está vazia)."""
    arquivos = brutos()
    return arquivos[-1] if arquivos else None
