"""Testes do pipeline: leitura do bruto, resumo, contrato do JSON, coleta e API.

Rodam sem rede e sem tocar nos dados reais: usam ``tests/fixtures/amostra_precos.csv``
e diretórios temporários.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from combustivelbr import cli, coleta, config, servidor, transformacao

AMOSTRA = Path(__file__).parent / "fixtures" / "amostra_precos.csv"


def achar(registros: list[dict], **campos) -> dict:
    """Registro do resumo que casa com todos os campos informados."""
    for registro in registros:
        if all(registro[chave] == valor for chave, valor in campos.items()):
            return registro
    raise AssertionError(f"nenhum registro com {campos}")


@pytest.fixture()
def bruto():
    return transformacao.ler_bruto(AMOSTRA)


@pytest.fixture()
def em_temporario(tmp_path, monkeypatch):
    """Redireciona todas as pastas de trabalho para um diretório temporário."""
    for atributo in ("DATA_RAW", "DATA_PROCESSED", "SITE_DATA"):
        monkeypatch.setattr(config, atributo, tmp_path / atributo.lower())
    monkeypatch.setattr(config, "ARQUIVO_PROCESSADO", tmp_path / "processed" / "dados.json")
    monkeypatch.setattr(config, "ARQUIVO_DO_SITE", tmp_path / "site" / "dados.json")
    return tmp_path


# ---------------------------------------------------------------- leitura do bruto
def test_le_a_amostra_com_as_colunas_esperadas(bruto):
    assert list(bruto.columns) == list(transformacao.COLUNAS_OBRIGATORIAS)
    assert len(bruto) == 13


def test_recusa_layout_diferente(tmp_path):
    arquivo = tmp_path / "outro_layout.csv"
    arquivo.write_text("produto,valor\nGasolina,6.12\n", encoding="utf-8")

    with pytest.raises(transformacao.BrutoInvalido, match="sem as colunas"):
        transformacao.ler_bruto(arquivo)


# ---------------------------------------------------------------- resumo
def test_resume_por_produto_estado_e_mes(bruto):
    registros = transformacao.resumir(bruto)

    assert len(registros) == 8
    assert achar(registros, produto="Gasolina", estado="SC", periodo="2026-09") == {
        "produto": "Gasolina",
        "estado": "SC",
        "periodo": "2026-09",
        "municipios": 3,
        "postos_pesquisados": 412,
        "preco_minimo": 5.89,
        "preco_medio": 6.181,
        "preco_maximo": 6.58,
    }


def test_preco_medio_e_ponderado_pelo_numero_de_postos(bruto):
    """Confere a ponderação por um caminho independente do código do pipeline."""
    registros = transformacao.resumir(bruto)
    gasolina_sc = achar(registros, produto="Gasolina", estado="SC", periodo="2026-09")

    soma = 6.120 * 158 + 6.210 * 142 + 6.230 * 112
    postos = 158 + 142 + 112
    assert gasolina_sc["preco_medio"] == round(soma / postos, 3)

    # a média simples (errada) daria outro número: (6.120 + 6.210 + 6.230) / 3
    media_simples = round((6.120 + 6.210 + 6.230) / 3, 3)
    assert gasolina_sc["preco_medio"] != media_simples


def test_aceita_virgula_como_separador_decimal(bruto):
    registros = transformacao.resumir(bruto)
    gnv = achar(registros, produto="GNV", estado="SC", periodo="2026-09")

    assert gnv["preco_medio"] == 4.35


def test_registro_sem_atributo_nao_quebra_o_json(bruto):
    """NaN não é JSON válido: o payload tem de sair serializável."""
    registros = transformacao.resumir(bruto)
    json.dumps(registros, allow_nan=False)


# ---------------------------------------------------------------- contrato do JSON
def test_payload_tem_o_contrato_do_site(bruto):
    payload = transformacao.montar_payload(bruto, arquivo_bruto=AMOSTRA)

    assert set(payload) == {
        "gerado_em",
        "fonte",
        "uf",
        "produtos",
        "periodos",
        "registros",
        "municipios",
        "noticias",
    }
    assert set(payload["noticias"]) == {"coletado_em", "itens"}
    assert set(payload["fonte"]) == {"nome", "url", "arquivo_bruto", "coletado_em"}
    assert payload["fonte"]["arquivo_bruto"] == AMOSTRA.name
    assert payload["uf"] == config.UF_PADRAO
    assert payload["produtos"] == ["Diesel S10", "Etanol", "GNV", "Gasolina"]
    assert payload["periodos"] == ["2026-08", "2026-09"]
    assert json.dumps(payload, allow_nan=False)


def test_publica_o_recorte_por_municipio(bruto):
    """O município é o degrau que o resumo por estado agrega: vai publicado, não recalculado."""
    payload = transformacao.montar_payload(bruto)

    assert payload["municipios"]
    municipio = achar(
        payload["municipios"],
        produto="Gasolina", estado="SC", municipio="Florianopolis", periodo="2026-09",
    )
    assert set(municipio) == set(transformacao.COLUNAS_MUNICIPIO)
    assert municipio["postos_pesquisados"] == 158
    assert municipio["preco_minimo"] <= municipio["preco_medio"] <= municipio["preco_maximo"]


def test_municipio_bate_com_o_resumo_do_estado(bruto):
    """Contagem, média e extremos do estado têm de fechar com as cidades que ele agrega."""
    payload = transformacao.montar_payload(bruto)
    estado = achar(payload["registros"], produto="Gasolina", estado="SC", periodo="2026-09")
    cidades = [
        linha for linha in payload["municipios"]
        if linha["produto"] == "Gasolina" and linha["estado"] == "SC" and linha["periodo"] == "2026-09"
    ]

    assert len(cidades) == estado["municipios"] == 3
    assert sum(linha["postos_pesquisados"] for linha in cidades) == estado["postos_pesquisados"]
    ponderado = sum(linha["preco_medio"] * linha["postos_pesquisados"] for linha in cidades)
    assert ponderado / estado["postos_pesquisados"] == pytest.approx(estado["preco_medio"], abs=0.001)
    assert min(linha["preco_minimo"] for linha in cidades) == estado["preco_minimo"]
    assert max(linha["preco_maximo"] for linha in cidades) == estado["preco_maximo"]


def test_grava_nos_dois_destinos(bruto, em_temporario):
    primeiro = em_temporario / "a" / "dados.json"
    segundo = em_temporario / "b" / "dados.json"

    gravados = transformacao.gravar(transformacao.montar_payload(bruto), destinos=(primeiro, segundo))

    assert gravados == [primeiro, segundo]
    assert json.loads(primeiro.read_text(encoding="utf-8")) == json.loads(
        segundo.read_text(encoding="utf-8")
    )


def test_json_sai_em_utf8_sem_bom_e_com_quebras_lf(bruto, em_temporario):
    destino = em_temporario / "dados.json"
    transformacao.gravar(transformacao.montar_payload(bruto), destinos=(destino,))
    bytes_gravados = destino.read_bytes()

    assert not bytes_gravados.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in bytes_gravados
    assert bytes_gravados.endswith(b"\n")
    assert "Combustíveis".encode("utf-8") in bytes_gravados


# ---------------------------------------------------------------- coleta
def test_amostra_vai_intacta_para_data_raw(em_temporario):
    destino = coleta.usar_amostra(AMOSTRA)

    assert destino.parent == config.DATA_RAW
    assert destino.read_bytes() == AMOSTRA.read_bytes()


def test_brutos_da_fonte_deixa_a_amostra_de_fora(em_temporario):
    """A amostra local é semente de teste: não entra no recorte do dado real."""
    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    (config.DATA_RAW / "2026-10-12-amostra.csv").write_text("a\n", encoding="utf-8")
    (config.DATA_RAW / "2026-10-12-gasolina-etanol.csv").write_text("b\n", encoding="utf-8")

    assert [arquivo.name for arquivo in coleta.brutos_da_fonte()] == [
        "2026-10-12-gasolina-etanol.csv"
    ]


def test_brutos_da_fonte_deixa_a_serie_mensal_de_fora(em_temporario):
    """A série mensal da fase 2 alimenta o histórico: no resumo do site ela viraria 46 meses."""
    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    (config.DATA_RAW / "2026-09-precos-gasolina-etanol.csv").write_text("a\n", encoding="utf-8")
    (config.DATA_RAW / "2026-10-12-diesel-gnv.csv").write_text("b\n", encoding="utf-8")

    assert [arquivo.name for arquivo in coleta.brutos_da_fonte()] == [
        "2026-10-12-diesel-gnv.csv"
    ]


def test_ultimo_bruto_escolhe_o_mais_recente(em_temporario):
    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    (config.DATA_RAW / "2026-08-05-precos.csv").write_text("a\n", encoding="utf-8")
    (config.DATA_RAW / "2026-09-05-precos.csv").write_text("b\n", encoding="utf-8")

    assert coleta.ultimo_bruto().name == "2026-09-05-precos.csv"


def test_coleta_sem_amostra_avisa_quando_o_arquivo_falta(em_temporario):
    with pytest.raises(coleta.FalhaDeColeta, match="amostra não encontrada"):
        coleta.usar_amostra(Path("nao-existe.csv"))


# ---------------------------------------------------------------- API
@pytest.fixture()
def cliente():
    return TestClient(servidor.app)


def test_api_saude(cliente):
    resposta = cliente.get("/saude")

    assert resposta.status_code == 200
    assert resposta.json()["ok"] is True


def test_api_serve_o_site_na_raiz(cliente):
    """O site está montado na raiz do servidor: / entrega o index.html."""
    resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert "Combustíveis BR" in resposta.text
    assert 'lang="pt-BR"' in resposta.text


def test_api_devolve_o_mesmo_json_do_site(bruto, em_temporario, cliente):
    transformacao.gravar(transformacao.montar_payload(bruto))

    resposta = cliente.get("/dados")

    assert resposta.status_code == 200
    assert len(resposta.json()["registros"]) == 8


def test_api_sem_dados_explica_o_proximo_passo(em_temporario, cliente):
    resposta = cliente.get("/dados")

    assert resposta.status_code == 404
    assert "rode o pipeline" in resposta.json()["detail"]


# ---------------------------------------------------------------- ponta a ponta
def test_pipeline_completo_com_a_amostra(em_temporario, capsys):
    codigo = cli.main(["pipeline", "--amostra"])

    assert codigo == 0
    assert "8 registros processados" in capsys.readouterr().out
    assert config.ARQUIVO_PROCESSADO.exists()
    assert config.ARQUIVO_DO_SITE.exists()
    assert json.loads(config.ARQUIVO_DO_SITE.read_text(encoding="utf-8"))["registros"] != []
