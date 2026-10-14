"""Testes do layout real da ANP: uma linha por revenda, preço com vírgula decimal.

Rodam sem rede: usam ``tests/fixtures/amostra_anp.csv`` (mesmas colunas e mesmo
separador do arquivo público) e diretórios temporários.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from combustivelbr import config, transformacao

AMOSTRA = Path(__file__).parent / "fixtures" / "amostra_anp.csv"
AMOSTRA_INTERNA = Path(__file__).parent / "fixtures" / "amostra_precos.csv"

CABECALHO = (
    "Estado - Sigla;Municipio;Produto;Data da Coleta;Valor de Venda;"
    "Revenda;CNPJ da Revenda;Unidade de Medida\n"
)


def achar(registros: list[dict], **campos) -> dict:
    """Registro que casa com todos os campos informados."""
    for registro in registros:
        if all(registro[chave] == valor for chave, valor in campos.items()):
            return registro
    raise AssertionError(f"nenhum registro com {campos}")


def achar_linha(df: pd.DataFrame, **campos) -> dict:
    """Linha do quadro que casa com todos os campos informados."""
    for _, linha in df.iterrows():
        if all(linha[chave] == valor for chave, valor in campos.items()):
            return linha.to_dict()
    raise AssertionError(f"nenhuma linha com {campos}")


@pytest.fixture()
def preparado():
    return transformacao.preparar(AMOSTRA)


@pytest.fixture()
def linhas(preparado):
    return preparado[0]


@pytest.fixture()
def contagens(preparado):
    return preparado[1]


# ---------------------------------------------------------------- leitura e cortes
def test_mapeia_as_colunas_do_arquivo_publico(linhas):
    assert list(linhas.columns) == list(transformacao.COLUNAS_OBRIGATORIAS)


def test_declara_quantas_linhas_leu(contagens):
    assert contagens["linhas_no_bruto"] == 9
    assert contagens["coletas_resumidas"] == 6


def test_descarta_unidade_diferente_do_litro(linhas, contagens):
    """GNV sai em R$/m³: somado ao litro, produziria uma média falsa."""
    assert "GNV" not in set(linhas["produto"])
    assert contagens["fora_da_unidade"] == 1


def test_padrao_usa_todos_os_estados(linhas, contagens):
    """O recorte padrão é o país inteiro: nenhuma UF é cortada."""
    assert config.UF_PADRAO == "BR"
    assert "PR" in set(linhas["estado"])
    assert "fora_da_uf" not in contagens


def test_recorte_por_uf_corta_os_outros_estados():
    linhas, contagens = transformacao.preparar(AMOSTRA, uf="SC")

    assert "PR" not in set(linhas["estado"])
    assert contagens["fora_da_uf"] == 1


def test_descarta_produto_fora_da_lista(tmp_path):
    arquivo = tmp_path / "produto-novo.csv"
    arquivo.write_text(
        CABECALHO + "SC;JOINVILLE;QUEROSENE AVIACAO;16/09/2026;6,20;POSTO C;33.333.333/0001-33;R$ / litro\n",
        encoding="utf-8",
    )

    linhas, contagens = transformacao.preparar(arquivo)

    assert contagens["produto_desconhecido"] == 1
    assert linhas.empty
    assert list(linhas.columns) == list(transformacao.COLUNAS_OBRIGATORIAS)


def test_bruto_sem_nada_aproveitavel_gera_payload_vazio(tmp_path, monkeypatch):
    """Produto novo no arquivo público não pode estourar: sai um JSON vazio e explicável."""
    arquivo = tmp_path / "produto-novo.csv"
    arquivo.write_text(
        CABECALHO + "SC;JOINVILLE;QUEROSENE AVIACAO;16/09/2026;6,20;POSTO C;33.333.333/0001-33;R$ / litro\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ARQUIVO_PROCESSADO", tmp_path / "dados.json")
    monkeypatch.setattr(config, "ARQUIVO_DO_SITE", tmp_path / "site" / "dados.json")

    payload, _, _ = transformacao.processar(arquivos=[arquivo])

    assert payload["registros"] == []
    assert payload["produtos"] == []
    assert payload["periodos"] == []


def test_produtos_do_mapa_sao_os_do_recorte():
    assert set(transformacao.PRODUTOS_ANP.values()) <= set(config.PRODUTOS)


# ---------------------------------------------------------------- normalização
def test_normaliza_municipio_sem_acento_e_sem_espaco():
    assert transformacao.normalizar_municipio("  Florianópolis ") == "FLORIANOPOLIS"
    assert transformacao.normalizar_municipio("SÃO PAULO") == "SAO PAULO"


def test_junta_o_mesmo_municipio_escrito_de_duas_formas(linhas):
    """Sem normalizar, "FLORIANOPOLIS" e "FLORIANÓPOLIS" contariam como dois municípios."""
    florianopolis = achar_linha(
        linhas, produto="Gasolina", municipio="FLORIANOPOLIS", data_coleta="2026-09-16"
    )

    assert florianopolis["postos_pesquisados"] == 2


def test_converte_preco_com_virgula_e_data_brasileira(linhas):
    etanol = achar_linha(linhas, produto="Etanol")

    assert etanol["data_coleta"] == "2026-09-16"
    assert etanol["preco_medio"] == 4.0


def test_aceita_data_em_iso_sem_trocar_dia_por_mes(tmp_path):
    """Se a fonte passar a mandar ISO, a base não pode esvaziar nem inverter dia e mês."""
    arquivo = tmp_path / "iso.csv"
    arquivo.write_text(
        CABECALHO
        + "SC;Florianopolis;GASOLINA;2026-09-05;5,890;POSTO A;11111111000111;R$ / litro\n"
        + "SC;Florianopolis;GASOLINA;05/09/2026;5,950;POSTO B;22222222000122;R$ / litro\n",
        encoding="utf-8",
    )

    quadro, contagens = transformacao.preparar(arquivo)

    assert contagens["sem_data"] == 0
    municipio = achar_linha(quadro, produto="Gasolina")
    assert municipio["data_coleta"] == "2026-09-05"
    assert municipio["postos_pesquisados"] == 2


def test_guarda_a_minima_e_a_maxima_do_municipio(linhas):
    joinville = achar_linha(
        linhas, produto="Gasolina", municipio="JOINVILLE", data_coleta="2026-09-16"
    )

    assert joinville["preco_minimo"] == 6.2
    assert joinville["preco_medio"] == 6.5
    assert joinville["preco_maximo"] == 6.8


def test_usa_o_nome_da_revenda_quando_o_cnpj_vem_vazio(linhas):
    blumenau = achar_linha(linhas, municipio="BLUMENAU")

    assert blumenau["postos_pesquisados"] == 1


def test_conta_cada_posto_uma_vez_no_mes(tmp_path):
    """A mesma revenda pesquisada em dois dias do mês é um posto, não dois."""
    arquivo = tmp_path / "duas-coletas.csv"
    arquivo.write_text(
        CABECALHO
        + "SC;JOINVILLE;GASOLINA;16/09/2026;6,00;POSTO C;33.333.333/0001-33;R$ / litro\n"
        + "SC;JOINVILLE;GASOLINA;23/09/2026;7,00;POSTO C;33.333.333/0001-33;R$ / litro\n",
        encoding="utf-8",
    )

    linhas, _ = transformacao.preparar(arquivo)
    joinville = achar_linha(linhas, produto="Gasolina", municipio="JOINVILLE")

    assert joinville["postos_pesquisados"] == 1
    assert joinville["preco_medio"] == 6.5  # média das duas coletas da revenda
    assert joinville["preco_minimo"] == 6.0
    assert joinville["preco_maximo"] == 7.0
    assert joinville["data_coleta"] == "2026-09-23"  # coleta mais recente do mês


def test_le_arquivo_com_bom(tmp_path):
    """O arquivo público vem com BOM: a primeira coluna não pode virar "BOM + Regiao"."""
    arquivo = tmp_path / "com-bom.csv"
    arquivo.write_bytes(AMOSTRA.read_bytes().replace(b"Regiao", b"\xef\xbb\xbfRegiao", 1))

    linhas, contagens = transformacao.preparar(arquivo)

    assert contagens["linhas_no_bruto"] == 9
    assert "estado" in linhas.columns


def test_le_arquivo_em_latin1(tmp_path):
    """Arquivo antigo em latin-1: tem de ser lido, não estourar decodificação."""
    arquivo = tmp_path / "latin1.csv"
    arquivo.write_bytes(
        (CABECALHO + "SC;Florianópolis;GASOLINA;16/09/2026;6,20;POSTO B;22.222.222/0001-22;R$ / litro\n")
        .encode("latin-1")
    )

    linhas, _ = transformacao.preparar(arquivo)

    assert list(linhas["municipio"]) == ["FLORIANOPOLIS"]


# ---------------------------------------------------------------- junção de brutos
def test_junta_dois_arquivos_sem_contar_a_mesma_coleta_duas_vezes(tmp_path):
    """O arquivo de 4 semanas se sobrepõe ao do dia anterior: a coleta conta uma vez."""
    repetido = tmp_path / "repetido.csv"
    repetido.write_bytes(AMOSTRA.read_bytes())

    linhas, contagens = transformacao.ler_brutos([AMOSTRA, repetido])

    assert len(linhas) == 6
    assert contagens["coletas_repetidas"] == 8  # uma por revenda/produto/dia do arquivo


def test_a_coleta_mais_nova_vence_na_juncao(tmp_path):
    atualizado = tmp_path / "atualizado.csv"
    atualizado.write_bytes(
        AMOSTRA.read_bytes().replace(b"16/09/2026;6,00;", b"16/09/2026;6,10;")
    )

    linhas, _ = transformacao.ler_brutos([AMOSTRA, atualizado])
    florianopolis = achar_linha(
        linhas, produto="Gasolina", municipio="FLORIANOPOLIS", data_coleta="2026-09-16"
    )

    assert florianopolis["preco_medio"] == 6.55


def test_processar_sem_arquivo_nao_mistura_a_amostra(tmp_path, monkeypatch):
    """A amostra local é semente de teste: ficar na pasta do bruto não a torna dado real."""
    bruto = tmp_path / "raw"
    bruto.mkdir()
    (bruto / "2026-10-12-amostra.csv").write_bytes(AMOSTRA_INTERNA.read_bytes())
    (bruto / "2026-10-12-gasolina-etanol.csv").write_bytes(AMOSTRA.read_bytes())
    monkeypatch.setattr(config, "DATA_RAW", bruto)
    monkeypatch.setattr(config, "ARQUIVO_PROCESSADO", tmp_path / "dados.json")
    monkeypatch.setattr(config, "ARQUIVO_DO_SITE", tmp_path / "site" / "dados.json")

    payload, _, _ = transformacao.processar()

    assert payload["fonte"]["arquivo_bruto"] == "2026-10-12-gasolina-etanol.csv"
    assert payload["produtos"] == ["Etanol", "Gasolina"]


# ---------------------------------------------------------------- resumo e publicação
def test_resumo_pondera_pelo_numero_de_postos(linhas):
    registros = transformacao.resumir(linhas)
    gasolina = achar(registros, produto="Gasolina", estado="SC", periodo="2026-09")

    # 2 postos a 6,50 em Florianópolis, 2 a 6,50 em Joinville e 1 a 6,40 em Blumenau
    assert gasolina == {
        "produto": "Gasolina",
        "estado": "SC",
        "periodo": "2026-09",
        "municipios": 3,
        "postos_pesquisados": 5,
        "preco_minimo": 6.0,
        "preco_medio": 6.48,
        "preco_maximo": 7.0,
    }
    # a média simples dos municípios daria 6,467: o peso dos postos muda a resposta
    assert gasolina["preco_medio"] != round((6.5 + 6.5 + 6.4) / 3, 3)


def test_publica_o_json_no_layout_da_anp(tmp_path, monkeypatch):
    processado = tmp_path / "processed" / "dados.json"
    do_site = tmp_path / "site" / "dados.json"
    monkeypatch.setattr(config, "ARQUIVO_PROCESSADO", processado)
    monkeypatch.setattr(config, "ARQUIVO_DO_SITE", do_site)

    payload, gravados, contagens = transformacao.processar(arquivos=[AMOSTRA])

    assert gravados == [processado, do_site]
    assert payload["fonte"]["arquivo_bruto"] == AMOSTRA.name
    assert payload["uf"] == config.UF_PADRAO
    assert payload["produtos"] == ["Etanol", "Gasolina"]
    assert payload["periodos"] == ["2026-09", "2026-10"]
    assert contagens["fora_da_unidade"] == 1
    assert json.loads(do_site.read_text(encoding="utf-8")) == payload
    assert json.dumps(payload, allow_nan=False)
