"""Ações de fiscalização do abastecimento (XLSX do painel dinâmico da ANP).

Duas planilhas públicas, mesmo esquema, 645.283 linhas juntas (1998 a 2026):
uma linha por documento de fiscalização, com UF, município, CNPJ, segmento,
data, procedimento e resultado.

O que interessa ao indicador: quantas ações cada UF/município recebeu, quantas
foram **auto de infração** e quantas **auto de interdição** (a interdição é o
remédio mais forte e é o que se cruza com preço).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from . import config

COLUNAS = (
    "uf",
    "municipio",
    "cnpj",
    "agente",
    "segmento",
    "data",
    "documento",
    "procedimento",
    "resultado",
)

# Nome na planilha -> nome interno (a planilha vem com acento e caixa alta).
MAPA_COLUNAS = {
    "UF": "uf",
    "Município": "municipio",
    "CNPJ/CPF": "cnpj",
    "Agente Econômico": "agente",
    "Segmento Fiscalizado": "segmento",
    "DATA DO DF": "data",
    "Número do Documento": "documento",
    "Procedimento de Fiscalização": "procedimento",
    "Resultado": "resultado",
}

SEGMENTO_REVENDA = "Revenda de Combustíveis"
PROCEDIMENTO_INFRACAO = "Auto de Infração"
PROCEDIMENTO_INTERDICAO = "Auto de Interdição"


class FiscalizacaoInvalida(RuntimeError):
    """A planilha não tem o esquema esperado (o layout da fonte mudou?)."""


def _datas(serie: pd.Series) -> pd.Series:
    """Datas da planilha: formato detectado pela cara do texto, nunca adivinhado.

    Hoje o painel manda ISO (``2018-12-31 00:00:00``, ou célula de data de verdade), mas
    ``03/04/2024`` é 3 de abril no Brasil e 4 de março nos EUA — e as duas leituras
    devolvem data válida, então o erro passa calado. Pior: ``dayfirst=True`` junto de
    ``format="mixed"`` *inverte* ISO ambíguo (``2024-04-03`` vira 4 de março). Aqui o
    ISO é lido como ISO e o ``dd/mm/aaaa`` como ``dd/mm/aaaa``; o resto vira nulo.
    """
    texto = serie.astype(str).str.strip()
    iso = texto.str.extract(r"^(\d{4}-\d{2}-\d{2})", expand=False)
    brasileira = texto.str.extract(r"^(\d{1,2}/\d{1,2}/\d{4})$", expand=False)

    datas = pd.to_datetime(iso, format="%Y-%m-%d", errors="coerce")
    return datas.fillna(pd.to_datetime(brasileira, format="%d/%m/%Y", errors="coerce"))


def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Deixa a planilha no formato interno, sem inventar dado faltante."""
    faltando = [coluna for coluna in MAPA_COLUNAS if coluna not in df.columns]
    if faltando:
        raise FiscalizacaoInvalida(
            f"planilha sem as colunas {', '.join(faltando)} "
            f"(encontradas: {', '.join(map(str, df.columns))})"
        )

    acoes = df.rename(columns=MAPA_COLUNAS)[list(COLUNAS)].copy()
    acoes["uf"] = acoes["uf"].astype(str).str.strip().str.upper()
    acoes["municipio"] = acoes["municipio"].map(config.normalizar_texto)
    acoes["cnpj"] = acoes["cnpj"].astype(str).str.replace(r"\D", "", regex=True)
    acoes["segmento"] = acoes["segmento"].fillna("").astype(str).str.strip()
    acoes["procedimento"] = acoes["procedimento"].fillna("").astype(str).str.strip()
    acoes["resultado"] = acoes["resultado"].fillna("").astype(str).str.strip()
    acoes["data"] = _datas(acoes["data"])
    acoes["periodo"] = acoes["data"].dt.strftime("%Y-%m")

    acoes["infracao"] = acoes["procedimento"] == PROCEDIMENTO_INFRACAO
    acoes["interdicao"] = acoes["procedimento"] == PROCEDIMENTO_INTERDICAO
    acoes["revenda"] = acoes["segmento"] == SEGMENTO_REVENDA

    return acoes.dropna(subset=["data"]).reset_index(drop=True)


def ler_planilha(caminho: Path, *, aba: str | int = 0) -> pd.DataFrame:
    """Lê um XLSX do painel e devolve o quadro normalizado."""
    bruto = pd.read_excel(caminho, sheet_name=aba, engine="openpyxl", dtype=str)
    return normalizar(bruto)


def ler_planilhas(caminhos: Iterable[Path]) -> pd.DataFrame:
    """Junta várias planilhas (as duas do painel têm o mesmo esquema)."""
    quadros = [ler_planilha(caminho) for caminho in caminhos]
    if not quadros:
        raise FiscalizacaoInvalida("nenhuma planilha informada")
    return pd.concat(quadros, ignore_index=True)


def arquivos_baixados() -> list[Path]:
    """Planilhas de fiscalização já baixadas (prova em ``config.DATA_RAW``)."""
    return sorted(config.DATA_RAW.glob("*-fiscalizacao-*.xlsx"))


def por_uf(acoes: pd.DataFrame, *, revenda_apenas: bool = True) -> pd.DataFrame:
    """Uma linha por UF: ações, autos de infração e interdições."""
    recorte = acoes[acoes["revenda"]] if revenda_apenas else acoes
    resumo = recorte.groupby("uf", as_index=False).agg(
        acoes=("documento", "size"),
        infracoes=("infracao", "sum"),
        interdicoes=("interdicao", "sum"),
        municipios=("municipio", "nunique"),
    )
    resumo["taxa_interdicao"] = (resumo["interdicoes"] / resumo["acoes"] * 100).round(3)
    resumo["taxa_infracao"] = (resumo["infracoes"] / resumo["acoes"] * 100).round(3)
    return resumo.sort_values("acoes", ascending=False).reset_index(drop=True)


def por_uf_mes(acoes: pd.DataFrame, *, revenda_apenas: bool = True) -> pd.DataFrame:
    """Série mensal por UF (base da correlação fiscalização × preço)."""
    recorte = acoes[acoes["revenda"]] if revenda_apenas else acoes
    serie = recorte.groupby(["uf", "periodo"], as_index=False).agg(
        acoes=("documento", "size"),
        infracoes=("infracao", "sum"),
        interdicoes=("interdicao", "sum"),
    )
    return serie.sort_values(["uf", "periodo"]).reset_index(drop=True)


def por_municipio(acoes: pd.DataFrame, *, periodo_minimo: str | None = None) -> pd.DataFrame:
    """Uma linha por UF/município (base do score de fiscalização)."""
    recorte = acoes[acoes["revenda"]]
    if periodo_minimo:
        recorte = recorte[recorte["periodo"] >= periodo_minimo]

    return (
        recorte.groupby(["uf", "municipio"], as_index=False)
        .agg(
            acoes=("documento", "size"),
            infracoes=("infracao", "sum"),
            interdicoes=("interdicao", "sum"),
            ultima_acao=("data", "max"),
        )
        .sort_values("acoes", ascending=False)
        .reset_index(drop=True)
    )


def interditos(acoes: pd.DataFrame) -> pd.DataFrame:
    """Quem já sofreu auto de interdição e quando (base do cruzamento com preço)."""
    recorte = acoes[acoes["interdicao"] & acoes["revenda"]]
    return (
        recorte.groupby(["uf", "municipio", "cnpj"], as_index=False)
        .agg(interdicoes=("interdicao", "size"), primeira=("data", "min"), ultima=("data", "max"))
        .sort_values("ultima", ascending=False)
        .reset_index(drop=True)
    )
