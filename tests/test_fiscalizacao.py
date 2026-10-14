"""Testes da fiscalização: planilha -> quadro normalizado -> indicadores por UF.

Sem rede: a planilha é construída no diretório temporário com ``openpyxl``, no mesmo
esquema do painel da ANP (só as colunas que o código usa).
"""

from __future__ import annotations

import pandas as pd
import pytest
from openpyxl import Workbook

from combustivelbr import fiscalizacao

COLUNAS_PLANILHA = [
    "UF",
    "Município",
    "Bairro",
    "ENDEREÇO",
    "CNPJ/CPF",
    "Agente Econômico",
    "Segmento Fiscalizado",
    "DATA DO DF",
    "Número do Documento",
    "Procedimento de Fiscalização",
    "Resultado",
]

# (uf, município, cnpj, segmento, data, documento, procedimento)
LINHAS = [
    ("SP", "São Paulo", "12.345.678/0001-99", "Revenda de Combustíveis", "2024-03-15", "DF-001", "Auto de Infração"),
    ("SP", "São Paulo", "12.345.678/0001-99", "Revenda de Combustíveis", "2024-04-03", "DF-002", "Auto de Interdição"),    ("SP", "são paulo", "98765432000188", "Revenda de Combustíveis", "2024-04-20", "DF-003", "Notificação"),
    ("SC", "Florianópolis", "11122233000144", "Revenda de Combustíveis", "2024-04-05", "DF-004", "Auto de Infração"),
    ("SC", "Florianópolis", "11122233000144", "Revenda de GLP", "2024-04-06", "DF-005", "Auto de Interdição"),
    ("SC", "Florianópolis", "11122233000144", "Revenda de Combustíveis", "lixo", "DF-006", "Auto de Infração"),
]


def escrever_planilha(caminho, linhas=LINHAS):
    """Grava um XLSX com o esquema do painel (o resto das colunas fica vazio)."""
    pasta = Workbook()
    aba = pasta.active
    aba.title = "Ações de Fiscalização"
    aba.append(COLUNAS_PLANILHA)
    for uf, municipio, cnpj, segmento, data, documento, procedimento in linhas:
        linha = dict.fromkeys(COLUNAS_PLANILHA, "")
        linha.update(
            {
                "UF": uf,
                "Município": municipio,
                "CNPJ/CPF": cnpj,
                "Segmento Fiscalizado": segmento,
                "DATA DO DF": data,
                "Número do Documento": documento,
                "Procedimento de Fiscalização": procedimento,
            }
        )
        aba.append([linha[coluna] for coluna in COLUNAS_PLANILHA])
    pasta.save(caminho)
    return caminho


@pytest.fixture()
def acoes(tmp_path):
    return fiscalizacao.ler_planilha(escrever_planilha(tmp_path / "fiscalizacao.xlsx"))


# ---------------------------------------------------------------- leitura e limpeza
def test_le_a_planilha_no_esquema_esperado(acoes):
    assert list(acoes.columns[: len(fiscalizacao.COLUNAS)]) == list(fiscalizacao.COLUNAS)


def test_data_invalida_sai_da_base_sem_quebrar(acoes):
    # a linha com "lixo" na data não entra: 6 na planilha, 5 no quadro
    assert len(acoes) == 5
    assert acoes["data"].notna().all()


def test_municipio_e_uf_ficam_normalizados(acoes):
    assert set(acoes["uf"]) == {"SP", "SC"}
    assert set(acoes["municipio"]) == {"SAO PAULO", "FLORIANOPOLIS"}


def test_cnpj_fica_so_com_digitos(acoes):
    assert set(acoes["cnpj"]) == {"12345678000199", "98765432000188", "11122233000144"}


def test_marcadores_de_procedimento_e_segmento(acoes):
    sao_paulo = acoes[acoes["municipio"] == "SAO PAULO"]
    assert sao_paulo["infracao"].sum() == 1
    assert sao_paulo["interdicao"].sum() == 1
    assert acoes["revenda"].sum() == 4  # a linha de GLP não é revenda de combustíveis


def test_data_brasileira_nao_vira_mes_errado():
    """``03/04/2024`` é 3 de abril (dd/mm) e ``2024-04-03`` é 3 de abril (ISO)."""
    serie = pd.Series(["03/04/2024", "15/03/2024", "2024-04-03", "2024-04-20", "lixo", "", None])
    datas = fiscalizacao._datas(serie)

    assert datas.iloc[0] == pd.Timestamp("2024-04-03")
    assert datas.iloc[1] == pd.Timestamp("2024-03-15")
    assert datas.iloc[2] == pd.Timestamp("2024-04-03")
    assert datas.iloc[3] == pd.Timestamp("2024-04-20")
    assert datas.iloc[4:].isna().all()


def test_data_em_celula_de_data_do_excel(tmp_path):
    """Célula de data de verdade (o painel usa assim) continua sendo lida."""
    serie = pd.Series(pd.to_datetime(["2024-03-15 00:00:00", "2024-04-03 00:00:00"]))
    datas = fiscalizacao._datas(serie)
    assert datas.tolist() == [pd.Timestamp("2024-03-15"), pd.Timestamp("2024-04-03")]


def test_mes_da_data_brasileira_chega_no_periodo(tmp_path):
    linhas = [
        ("SP", "Campinas", "1", "Revenda de Combustíveis", "03/04/2024", "DF-1", "Notificação"),
        ("SP", "Campinas", "1", "Revenda de Combustíveis", "15/03/2024", "DF-2", "Notificação"),
    ]
    acoes = fiscalizacao.ler_planilha(escrever_planilha(tmp_path / "datas.xlsx", linhas))
    assert sorted(acoes["periodo"]) == ["2024-03", "2024-04"]
    assert acoes["data"].min() == pd.Timestamp("2024-03-15")


def test_planilha_fora_do_esquema_avisa(tmp_path):
    caminho = tmp_path / "outro.xlsx"
    pasta = Workbook()
    aba = pasta.active
    aba.append(["UF", "Município", "Preço"])
    aba.append(["SP", "São Paulo", 5.99])
    pasta.save(caminho)

    with pytest.raises(fiscalizacao.FiscalizacaoInvalida, match="colunas"):
        fiscalizacao.ler_planilha(caminho)


def test_juntar_planilhas(tmp_path):
    primeira = escrever_planilha(tmp_path / "a.xlsx")
    segunda = escrever_planilha(tmp_path / "b.xlsx", LINHAS[:2])
    assert len(fiscalizacao.ler_planilhas([primeira, segunda])) == 7


def test_sem_planilha_nenhuma_avisa():
    with pytest.raises(fiscalizacao.FiscalizacaoInvalida):
        fiscalizacao.ler_planilhas([])


# ---------------------------------------------------------------- resumos
def test_resumo_por_uf_conta_infracao_e_interdicao(acoes):
    resumo = fiscalizacao.por_uf(acoes)
    por_uf = resumo.set_index("uf")

    assert por_uf.loc["SP", "acoes"] == 3
    assert por_uf.loc["SP", "infracoes"] == 1
    assert por_uf.loc["SP", "interdicoes"] == 1
    assert por_uf.loc["SC", "interdicoes"] == 0
    assert por_uf.loc["SP", "municipios"] == 1
    # SC tem três linhas na planilha: a de GLP não é revenda e a de data inválida sai da base
    assert por_uf.loc["SC", "acoes"] == 1
    assert por_uf.loc["SC", "infracoes"] == 1


def test_taxa_de_interdicao_e_percentual(acoes):
    por_uf = fiscalizacao.por_uf(acoes).set_index("uf")
    assert por_uf.loc["SP", "taxa_interdicao"] == pytest.approx(1 / 3 * 100, abs=0.001)
    assert por_uf.loc["SC", "taxa_interdicao"] == 0.0


def test_serie_mensal_por_uf(acoes):
    serie = fiscalizacao.por_uf_mes(acoes).set_index(["uf", "periodo"])
    assert serie.loc[("SP", "2024-03"), "acoes"] == 1
    assert serie.loc[("SP", "2024-04"), "acoes"] == 2


def test_resumo_por_municipio_respeita_periodo_minimo(acoes):
    todos = fiscalizacao.por_municipio(acoes)
    recortado = fiscalizacao.por_municipio(acoes, periodo_minimo="2024-04")

    assert todos.set_index(["uf", "municipio"]).loc[("SP", "SAO PAULO"), "acoes"] == 3
    assert recortado.set_index(["uf", "municipio"]).loc[("SP", "SAO PAULO"), "acoes"] == 2


def test_interditos_lista_quem_foi_interditado(acoes):
    lista = fiscalizacao.interditos(acoes)
    assert list(zip(lista["uf"], lista["municipio"], lista["interdicoes"])) == [("SP", "SAO PAULO", 1)]
    assert lista["primeira"].iloc[0] == pd.Timestamp("2024-04-03")


def test_arquivos_baixados_usa_a_pasta_bruta(tmp_path, monkeypatch):
    monkeypatch.setattr(fiscalizacao.config, "DATA_RAW", tmp_path)
    (tmp_path / "2026-10-12-fiscalizacao-1998-2018.xlsx").write_bytes(b"x")
    (tmp_path / "outro.txt").write_text("nada", encoding="utf-8")
    assert [caminho.name for caminho in fiscalizacao.arquivos_baixados()] == [
        "2026-10-12-fiscalizacao-1998-2018.xlsx"
    ]
