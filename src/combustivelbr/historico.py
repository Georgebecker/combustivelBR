"""Série mensal de preços (arquivos por revenda de 2023 em diante).

A correlação fiscalização × preço precisa de série mensal; o arquivo de "últimas 4
semanas" só tem dois meses. Os arquivos mensais existem, mas o nome deles **não segue
padrão** (em 2026 há mês com nome torto e um sem extensão), então o endereço é
descoberto lendo a página da fonte — nunca montando o endereço na mão.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import requests

from . import config, transformacao

# Nomes já vistos: "precos-gasolina-etanol-03.csv" (2023-2025) e
# "03-dados-abertos-precos-gasolina-etanol.csv" / "06-dados-abertos-precos-2026-06-...csv" (2026).
PADROES = (
    re.compile(r"precos-gasolina-etanol-(\d{2})\.csv$"),
    # 2026 tem nome irregular: "03-dados-abertos-precos-gasolina-etanol.csv",
    # "02-cados-abertos-preco-gasolina-etanol.csv" (erro de digitação da fonte) e
    # "04-dados-abertos-precos-gasolina-etanol" (sem extensão).
    re.compile(r"(\d{2})-.*abertos.*gasolina-etanol[^/]*$"),
)

PRODUTO_PADRAO = "Gasolina"


class HistoricoIndisponivel(RuntimeError):
    """A página da fonte não devolveu a lista de arquivos mensais."""


def _mes_do_nome(nome: str) -> str | None:
    for padrao in PADROES:
        achado = padrao.search(nome)
        if achado:
            return achado.group(1)
    return None


def descobrir(*, anos: Sequence[int] | None = None) -> dict[tuple[int, str], str]:
    """Endereços dos arquivos mensais de gasolina/etanol, por (ano, mês).

    Lê a página da fonte porque o nome do arquivo muda de mês para mês.
    """
    try:
        resposta = requests.get(
            config.FONTE_URL, timeout=config.TIMEOUT_SEGUNDOS,
            headers={"User-Agent": config.USER_AGENT},
        )
        resposta.raise_for_status()
    except requests.RequestException as erro:
        raise HistoricoIndisponivel(f"não deu para ler {config.FONTE_URL}: {erro}") from erro

    anos = anos or range(config.ANO_INICIO_SERIE, config.ANO_FIM_SERIE + 1)
    achados: dict[tuple[int, str], str] = {}
    for endereco in re.findall(r'href="(https://www\.gov\.br/anp/[^"]+gasolina-etanol[^"]*)"', resposta.text):
        partes = endereco.split("/")
        try:
            ano = int(partes[-2])
        except ValueError:
            continue
        if ano not in anos or "/dsan/" not in endereco:
            continue
        mes = _mes_do_nome(partes[-1])
        if mes and (ano, mes) not in achados:
            achados[(ano, mes)] = endereco
    return achados


def baixar_mensais(*, anos: Sequence[int] | None = None, espera: float = 0.0) -> list[Path]:
    """Baixa cada mês para ``config.DATA_RAW`` (pula o que já está baixado)."""
    import time

    config.garantir_diretorios()
    baixados = []
    falhas = []
    for (ano, mes), endereco in sorted(descobrir(anos=anos).items()):
        destino = config.DATA_RAW / f"{ano}-{mes}-precos-gasolina-etanol.csv"
        if destino.exists() and destino.stat().st_size > 0:
            baixados.append(destino)
            continue
        try:
            resposta = requests.get(
                endereco, timeout=config.TIMEOUT_SEGUNDOS,
                headers={"User-Agent": config.USER_AGENT},
            )
            resposta.raise_for_status()
        except requests.RequestException as erro:
            falhas.append(f"{ano}-{mes} ({erro.__class__.__name__})")
            continue
        if not resposta.content.strip():
            falhas.append(f"{ano}-{mes} (resposta vazia)")
            continue
        destino.write_bytes(resposta.content)
        baixados.append(destino)
        if espera:
            time.sleep(espera)
    if falhas:
        # Série com buraco produz correlação errada em silêncio: melhor parar e dizer quais
        # meses faltaram. O que já baixou fica: a próxima execução só completa o que falta.
        raise HistoricoIndisponivel(
            "meses sem baixar: " + ", ".join(falhas) + ". Rode de novo para completar a série."
        )
    return baixados


def arquivos_mensais(anos: Sequence[int] | None = None) -> list[Path]:
    """Meses já baixados, em ordem (o nome começa com ``AAAA-MM``)."""
    arquivos = []
    for caminho in sorted(config.DATA_RAW.glob("*-precos-gasolina-etanol.csv")):
        try:
            ano, mes = int(caminho.name[:4]), caminho.name[5:7]
        except ValueError:
            continue
        if anos and ano not in anos:
            continue
        if not mes.isdigit():
            continue
        arquivos.append(caminho)
    return arquivos


def _periodo(caminho: Path) -> str:
    return f"{caminho.name[:4]}-{caminho.name[5:7]}"


def agregar_arquivo(caminho: Path, *, produto: str = PRODUTO_PADRAO) -> pd.DataFrame:
    """Uma linha por UF no mês: postos, preço médio, extremos e dispersão.

    Preço médio é a média das revendas (cada revenda pesa uma vez, com a média das
    coletas dela no mês) — a mesma definição usada no site.
    """
    estacoes, _ = transformacao.estacoes_do_bruto(caminho)
    recorte = estacoes[estacoes["produto"] == produto]
    if recorte.empty:
        return pd.DataFrame(columns=[
            "uf", "periodo", "produto", "postos", "preco_medio", "preco_minimo",
            "preco_maximo", "desvio", "coeficiente_variacao",
        ])

    por_revenda = recorte.groupby(["estado", "municipio", "revenda_id"], as_index=False).agg(
        preco=("preco_medio", "mean")
    )
    resumo = por_revenda.groupby("estado", as_index=False).agg(
        postos=("revenda_id", "size"),
        municipios=("municipio", "nunique"),
        preco_medio=("preco", "mean"),
        preco_minimo=("preco", "min"),
        preco_maximo=("preco", "max"),
        desvio=("preco", "std"),
    )
    resumo = resumo.rename(columns={"estado": "uf"})
    resumo["periodo"] = _periodo(caminho)
    resumo["produto"] = produto
    resumo["coeficiente_variacao"] = (resumo["desvio"] / resumo["preco_medio"]).round(5)
    resumo["preco_medio"] = resumo["preco_medio"].round(4)
    resumo["desvio"] = resumo["desvio"].round(4)
    return resumo[[
        "uf", "periodo", "produto", "postos", "preco_medio", "preco_minimo",
        "preco_maximo", "desvio", "coeficiente_variacao",
    ]]


def agregar_municipios(
    caminho: Path, *, produto: str = PRODUTO_PADRAO, periodo: str | None = None
) -> pd.DataFrame:
    """Uma linha por município no mês — base da anomalia "mínimo colado na média".

    Dispersão sai das revendas do município (desvio padrão dos preços medios por
    revenda), não da média dos municípios.
    """
    estacoes, _ = transformacao.estacoes_do_bruto(caminho)
    recorte = estacoes[estacoes["produto"] == produto]
    if recorte.empty:
        return pd.DataFrame(columns=[
            "uf", "municipio", "periodo", "produto", "postos", "preco_medio",
            "preco_minimo", "preco_maximo", "desvio", "coeficiente_variacao",
        ])

    por_revenda = recorte.groupby(["estado", "municipio", "revenda_id"], as_index=False).agg(
        preco=("preco_medio", "mean")
    )
    resumo = por_revenda.groupby(["estado", "municipio"], as_index=False).agg(
        postos=("revenda_id", "size"),
        preco_medio=("preco", "mean"),
        preco_minimo=("preco", "min"),
        preco_maximo=("preco", "max"),
        desvio=("preco", "std"),
    ).rename(columns={"estado": "uf"})
    resumo["periodo"] = periodo or _periodo(caminho)
    resumo["produto"] = produto
    resumo["coeficiente_variacao"] = (resumo["desvio"] / resumo["preco_medio"]).round(5)
    resumo["preco_medio"] = resumo["preco_medio"].round(4)
    resumo["desvio"] = resumo["desvio"].round(4)
    return resumo[[
        "uf", "municipio", "periodo", "produto", "postos", "preco_medio",
        "preco_minimo", "preco_maximo", "desvio", "coeficiente_variacao",
    ]].sort_values(["uf", "municipio"]).reset_index(drop=True)


def serie_uf_mes(anos: Sequence[int] | None = None, *, produto: str = PRODUTO_PADRAO) -> pd.DataFrame:
    """Série mensal por UF, lida dos arquivos já baixados."""
    quadros = [agregar_arquivo(caminho, produto=produto) for caminho in arquivos_mensais(anos)]
    quadros = [quadro for quadro in quadros if not quadro.empty]
    if not quadros:
        return pd.DataFrame(columns=[
            "uf", "periodo", "produto", "postos", "preco_medio", "preco_minimo",
            "preco_maximo", "desvio", "coeficiente_variacao",
        ])
    return pd.concat(quadros, ignore_index=True).sort_values(["uf", "periodo"]).reset_index(drop=True)
