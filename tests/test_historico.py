"""Testes da série mensal: nome irregular da fonte, arquivos baixados e agregação.

Sem rede: usa o CSV de amostra de ``tests/fixtures`` copiado para o diretório temporário
com o nome que o painel usa (``AAAA-MM-precos-gasolina-etanol.csv``).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from combustivelbr import config, historico

AMOSTRA = Path(__file__).parent / "fixtures" / "amostra_anp.csv"


def amostra_do_mes(destino: Path, mes: str = "2024-05") -> Path:
    caminho = destino / f"{mes}-precos-gasolina-etanol.csv"
    shutil.copyfile(AMOSTRA, caminho)
    return caminho


# ---------------------------------------------------------------- nome do arquivo
@pytest.mark.parametrize(
    "nome, esperado",
    [
        ("precos-gasolina-etanol-03.csv", "03"),
        ("03-dados-abertos-precos-gasolina-etanol.csv", "03"),
        # erro de digitação da própria fonte, em 2026
        ("02-cados-abertos-preco-gasolina-etanol.csv", "02"),
        ("06-dados-abertos-precos-2026-06-gasolina-etanol.csv", "06"),
        ("precos-diesel-gnv-03.csv", None),
    ],
)
def test_mes_sai_do_nome_irregular(nome, esperado):
    assert historico._mes_do_nome(nome) == esperado


def test_arquivos_mensais_so_pega_o_padrao_e_ordena(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_RAW", tmp_path)
    for nome in (
        "2024-03-precos-gasolina-etanol.csv",
        "2024-01-precos-gasolina-etanol.csv",
        "2024-02-precos-gasolina-etanol.csv",
        "2024-02-precos-diesel-gnv.csv",
    ):
        (tmp_path / nome).write_text("x", encoding="utf-8")

    assert [caminho.name[:7] for caminho in historico.arquivos_mensais()] == [
        "2024-01", "2024-02", "2024-03",
    ]


def test_arquivos_mensais_filtram_por_ano(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_RAW", tmp_path)
    for nome in ("2023-12-precos-gasolina-etanol.csv", "2024-01-precos-gasolina-etanol.csv"):
        (tmp_path / nome).write_text("x", encoding="utf-8")

    encontrados = historico.arquivos_mensais(anos=[2024])
    assert [caminho.name[:7] for caminho in encontrados] == ["2024-01"]


# ---------------------------------------------------------------- agregação
@pytest.fixture()
def arquivo_do_mes(tmp_path):
    return amostra_do_mes(tmp_path)


def test_periodo_vem_do_nome_do_arquivo(arquivo_do_mes):
    resumo = historico.agregar_arquivo(arquivo_do_mes)
    assert set(resumo["periodo"]) == {"2024-05"}


def test_agrega_uma_linha_por_uf(arquivo_do_mes):
    resumo = historico.agregar_arquivo(arquivo_do_mes)
    estacoes, _ = historico.transformacao.estacoes_do_bruto(arquivo_do_mes)
    gasolina = estacoes[estacoes["produto"] == historico.PRODUTO_PADRAO]

    assert len(resumo) == gasolina["estado"].nunique()
    assert resumo["uf"].is_unique


def test_postos_conta_revenda_e_nao_coleta(arquivo_do_mes):
    """Mesma regra do site: cada revenda pesa uma vez, mesmo com várias coletas no mês."""
    resumo = historico.agregar_arquivo(arquivo_do_mes)
    estacoes, _ = historico.transformacao.estacoes_do_bruto(arquivo_do_mes)
    gasolina = estacoes[estacoes["produto"] == historico.PRODUTO_PADRAO]
    revendas = gasolina.groupby("estado")["revenda_id"].nunique()

    assert resumo.set_index("uf")["postos"].to_dict() == revendas.to_dict()
    assert resumo["postos"].sum() <= len(gasolina)


def test_media_e_extremos_saem_das_revendas(arquivo_do_mes):
    resumo = historico.agregar_arquivo(arquivo_do_mes)
    estacoes, _ = historico.transformacao.estacoes_do_bruto(arquivo_do_mes)
    gasolina = estacoes[estacoes["produto"] == historico.PRODUTO_PADRAO]
    por_revenda = gasolina.groupby(["estado", "revenda_id"])["preco_medio"].mean()
    da_uf = por_revenda.groupby("estado")

    for linha in resumo.itertuples():
        precos = da_uf.get_group(linha.uf)
        assert linha.preco_medio == pytest.approx(precos.mean().round(4), abs=1e-4)
        assert linha.preco_minimo == pytest.approx(round(precos.min(), 4), abs=1e-4)
        assert linha.preco_maximo == pytest.approx(round(precos.max(), 4), abs=1e-4)


def test_produto_sem_dado_devolve_quadro_vazio(arquivo_do_mes):
    resumo = historico.agregar_arquivo(arquivo_do_mes, produto="Querosene")
    assert resumo.empty
    assert "coeficiente_variacao" in resumo.columns


def test_agrega_municipios_uma_linha_por_municipio(arquivo_do_mes):
    resumo = historico.agregar_municipios(arquivo_do_mes)

    assert {"uf", "municipio", "postos", "preco_medio", "preco_minimo", "preco_maximo"} <= set(resumo.columns)
    assert not resumo.duplicated(subset=["uf", "municipio"]).any()
    assert resumo["periodo"].eq("2024-05").all()


def test_agrega_municipios_desvio_e_das_revendas_do_municipio(arquivo_do_mes):
    resumo = historico.agregar_municipios(arquivo_do_mes)
    estacoes, _ = historico.transformacao.estacoes_do_bruto(arquivo_do_mes)
    gasolina = estacoes[estacoes["produto"] == historico.PRODUTO_PADRAO]
    por_revenda = gasolina.groupby(["estado", "municipio", "revenda_id"])["preco_medio"].mean()

    for linha in resumo.head(5).itertuples():
        precos = por_revenda.loc[(linha.uf, linha.municipio)]
        if len(precos) > 1:
            assert linha.desvio == pytest.approx(round(precos.std(), 4), abs=1e-4)


def test_serie_uf_mes_junta_os_meses(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_RAW", tmp_path)
    amostra_do_mes(tmp_path, "2024-04")
    amostra_do_mes(tmp_path, "2024-05")

    serie = historico.serie_uf_mes()
    assert sorted(serie["periodo"].unique()) == ["2024-04", "2024-05"]
    assert serie.groupby("uf")["periodo"].nunique().eq(2).all()


def test_serie_sem_arquivo_nenhum_devolve_vazio_com_as_colunas(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_RAW", tmp_path)
    serie = historico.serie_uf_mes()
    assert serie.empty and "preco_medio" in serie.columns


def test_serie_nao_mistura_produto(arquivo_do_mes, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_RAW", tmp_path)
    amostra_do_mes(tmp_path, "2024-05")
    serie = historico.serie_uf_mes(produto=historico.PRODUTO_PADRAO)
    assert serie["produto"].eq(historico.PRODUTO_PADRAO).all()


def test_planilha_de_preco_nao_e_lida_como_excel(tmp_path):
    """Guarda-corpo: ``agregar_arquivo`` só aceita o CSV de preço."""
    caminho = tmp_path / "2024-05-precos-gasolina-etanol.csv"
    caminho.write_text("nada a ver\n", encoding="utf-8")
    with pytest.raises(Exception):
        historico.agregar_arquivo(caminho)


def test_dados_do_mes_nao_vazam_entre_arquivos(tmp_path, monkeypatch):
    """A série de dois meses não pode repetir o mesmo preço por acidente de cache."""
    monkeypatch.setattr(config, "DATA_RAW", tmp_path)
    primeiro = amostra_do_mes(tmp_path, "2024-04")
    segundo = tmp_path / "2024-05-precos-gasolina-etanol.csv"
    segundo.write_text(
        primeiro.read_text(encoding="utf-8").replace(";6,00;", ";7,00;"), encoding="utf-8"
    )

    serie = historico.serie_uf_mes().sort_values("periodo")
    medias = serie.groupby("periodo")["preco_medio"].mean()
    assert pd.api.types.is_float_dtype(serie["preco_medio"])
    assert medias.nunique() == 2
    assert medias["2024-05"] > medias["2024-04"]
