"""Testes dos endpoints de inteligência: leem o JSON publicado, não recalculam nada.

O arquivo é escrito em diretório temporário — nenhum teste toca o artefato real.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from combustivelbr import config, servidor

CONTEUDO = {
    "gerado_em": "2026-10-12T22:16:00-03:00",
    "periodos": {"correlacao_desde": "2023-01", "janela_ipf_meses": 12},
    "cobertura": {"acoes_revenda": 469991, "postos_ativos_api": 45762},
    "parametros": {"desde": "2023-01", "metodo": "pearson"},
    "limitacoes": ["amostra de 461 municípios", "statusSIGAF vazio"],
    "score_evidencia": {"score": 0.0579, "evidencias": 9, "detalhes": []},
    "ufs": [
        {"uf": "MA", "ipf": 290.57, "zona_cega": True},
        {"uf": "SP", "ipf": 54.4, "zona_cega": False},
    ],
    "correlacoes": [
        {"nome": "fiscalizacao_x_preco_pooled", "r": -0.1872, "p": 0.0, "n": 1090},
        {"nome": "ipf_x_dispersao_uf", "r": -0.1675, "p": 0.4038, "n": 27},
    ],
    "anomalias": [
        {"uf": "MS", "municipio": "CORUMBA", "meses_colados": 46, "meses": 46},
        {"uf": "AM", "municipio": "TEFE", "meses_colados": 15, "meses": 15},
    ],
    "alvos": [{"uf": "SP", "municipio": "BARUERI", "score": 0.7218}],
    "interditos": [
        {"uf": "CE", "municipio": "PINDORETAMA", "cnpj": "44695202000170", "interdicoes": 2},
        {"uf": "SP", "municipio": "BARUERI", "cnpj": "11111111000111", "interdicoes": 1},
    ],
    "interdicao_preco": {"n": 187, "efeito": -0.0001, "p": 0.7728,
                         "leitura": "sem diferença detectável contra o controle"},
}


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    caminho = tmp_path / "inteligencia.json"
    caminho.write_text(json.dumps(CONTEUDO, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "ARQUIVO_INTELIGENCIA", caminho)
    return TestClient(servidor.app)


def test_sem_analise_publicada_explica_o_proximo_passo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARQUIVO_INTELIGENCIA", tmp_path / "nao-existe.json")
    resposta = TestClient(servidor.app).get("/inteligencia")

    assert resposta.status_code == 404
    assert "scripts/inteligencia.py" in resposta.json()["detail"]


def test_indice_traz_score_cobertura_e_limitacoes(cliente):
    corpo = cliente.get("/inteligencia").json()

    assert corpo["score_evidencia"]["score"] == 0.0579
    assert corpo["cobertura"]["postos_ativos_api"] == 45762
    assert len(corpo["limitacoes"]) == 2
    assert corpo["parametros"]["metodo"] == "pearson"
    # o índice não repete as listas longas
    assert "ufs" not in corpo and "correlacoes" not in corpo


def test_correlacoes_saem_com_r_e_p(cliente):
    corpo = cliente.get("/inteligencia/correlacoes").json()

    assert len(corpo) == 2
    assert corpo[0]["r"] == -0.1872 and corpo[0]["p"] == 0.0


def test_ufs_sem_filtro_traz_todas(cliente):
    assert len(cliente.get("/inteligencia/ufs").json()) == 2


def test_ufs_filtra_por_uf(cliente):
    corpo = cliente.get("/inteligencia/ufs", params={"uf": "ma"}).json()
    assert [item["uf"] for item in corpo] == ["MA"]


def test_ufs_filtra_zona_cega(cliente):
    cegas = cliente.get("/inteligencia/ufs", params={"zona_cega": True}).json()
    fiscalizadas = cliente.get("/inteligencia/ufs", params={"zona_cega": False}).json()

    assert [item["uf"] for item in cegas] == ["MA"]
    assert [item["uf"] for item in fiscalizadas] == ["SP"]


def test_anomalias_filtram_por_uf(cliente):
    assert len(cliente.get("/inteligencia/anomalias").json()) == 2
    corpo = cliente.get("/inteligencia/anomalias", params={"uf": "MS"}).json()
    assert [item["municipio"] for item in corpo] == ["CORUMBA"]


def test_alvos_respeitam_o_limite(cliente):
    assert len(cliente.get("/inteligencia/alvos", params={"limite": 1}).json()) == 1
    assert len(cliente.get("/inteligencia/alvos").json()) == 1  # só há um no fixture


def test_alvos_com_limite_zero_ainda_devolve_um(cliente):
    assert len(cliente.get("/inteligencia/alvos", params={"limite": 0}).json()) == 1


def test_interditos_filtram_por_uf(cliente):
    corpo = cliente.get("/inteligencia/interditos", params={"uf": "SP"}).json()
    assert [item["municipio"] for item in corpo] == ["BARUERI"]


def test_interdicao_preco_devolve_o_teste_e_a_leitura(cliente):
    corpo = cliente.get("/inteligencia/interdicao-preco").json()

    assert corpo["n"] == 187
    assert corpo["efeito"] == -0.0001
    assert "sem diferença" in corpo["leitura"]


def test_endpoints_de_inteligencia_nao_engolem_o_site(cliente):
    """As rotas são declaradas antes do mount estático; a raiz continua servindo o site."""
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    assert "Combustíveis BR" in resposta.text


def test_site_publicado_tem_o_json_de_inteligencia_ao_lado_do_de_precos():
    """O contrato diz que a aba lê ``site/data/inteligencia.json``: confira o caminho publicado."""
    assert Path(config.ARQUIVO_INTELIGENCIA).name == "inteligencia.json"
    assert Path(config.ARQUIVO_INTELIGENCIA).parent == Path(config.ARQUIVO_DO_SITE).parent
