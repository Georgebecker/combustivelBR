"""Testes do cliente da API de revendedores: normalização e espera progressiva no 429.

Sem rede: ``requests.get`` é substituído por uma resposta falsa.
"""

from __future__ import annotations

import json

import pytest
import requests

from combustivelbr import config, revendedores


class RespostaFalsa:
    def __init__(self, corpo, status=200):
        self.corpo = corpo
        self.status_code = status

    def json(self):
        if isinstance(self.corpo, Exception):
            raise self.corpo
        return self.corpo

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture()
def sem_espera(monkeypatch):
    """Registra as esperas em vez de dormir de verdade."""
    esperas = []
    monkeypatch.setattr(revendedores.time, "sleep", esperas.append)
    return esperas


REGISTRO_BRUTO = {
    "uf": " sc ",
    "municipio": "florianopolis",
    "cnpj": "11.111.111/0001-11",
    "razaoSocial": "  POSTO A LTDA ",
    "autorizacao": "AUT-1",
    "distribuidora": "PETROBRAS",
    "situacaoConstatada": "200",
    "latitude": None,
    "longitude": None,
    "latitude_ANP4C": -27.6,
    "longitude_ANP4C": -48.5,
}


# ---------------------------------------------------------------- normalização
def test_normalizar_limpa_campos():
    limpo = revendedores.normalizar([REGISTRO_BRUTO])[0]

    assert limpo["uf"] == "SC"
    assert limpo["cnpj"] == "11111111000111"
    assert limpo["razao_social"] == "POSTO A LTDA"
    assert limpo["situacao"] == "200"


def test_normalizar_usa_coordenada_alternativa():
    limpo = revendedores.normalizar([REGISTRO_BRUTO])[0]
    assert (limpo["latitude"], limpo["longitude"]) == (-27.6, -48.5)


def test_normalizar_com_campo_ausente_nao_quebra():
    limpo = revendedores.normalizar([{}])[0]
    assert limpo["uf"] == "" and limpo["cnpj"] == "" and limpo["razao_social"] == ""


def test_postos_por_uf_conta_e_ignora_uf_vazia():
    assert revendedores.postos_por_uf([REGISTRO_BRUTO, REGISTRO_BRUTO, {}]) == {"SC": 2}


# ---------------------------------------------------------------- espera progressiva
def test_429_espera_e_tenta_de_novo(monkeypatch, sem_espera):
    respostas = [RespostaFalsa({}, 429), RespostaFalsa({}, 429), RespostaFalsa({"data": [1]})]
    monkeypatch.setattr(revendedores.requests, "get", lambda *a, **k: respostas.pop(0))

    assert revendedores._get("https://exemplo", {"uf": "SC"}) == {"data": [1]}
    assert sem_espera == [8, 16]  # dobra a cada tentativa


def test_erro_de_rede_tambem_espera(monkeypatch, sem_espera):
    respostas = [requests.ConnectionError("caiu"), RespostaFalsa({"ok": True})]

    def fake_get(*args, **kwargs):
        resposta = respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    monkeypatch.setattr(revendedores.requests, "get", fake_get)

    assert revendedores._get("https://exemplo", {}) == {"ok": True}
    assert sem_espera == [8]


def test_desiste_depois_das_tentativas(monkeypatch, sem_espera):
    monkeypatch.setattr(revendedores.requests, "get", lambda *a, **k: RespostaFalsa({}, 503))

    with pytest.raises(revendedores.FalhaDeRevendedores, match="desisti após 4 tentativas"):
        revendedores._get("https://exemplo", {})
    assert len(sem_espera) == 4


def test_resposta_sem_json_valido_conta_como_falha(monkeypatch, sem_espera):
    monkeypatch.setattr(
        revendedores.requests, "get", lambda *a, **k: RespostaFalsa(ValueError("json inválido"))
    )
    with pytest.raises(revendedores.FalhaDeRevendedores):
        revendedores._get("https://exemplo", {})


# ---------------------------------------------------------------- download por UF
def test_baixar_percorre_todas_as_paginas(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_RAW", tmp_path)
    paginas = {
        1: {"data": [{"cnpj": "1"}], "searchPageFilter": {"totalPagina": 2}},
        2: {"data": [{"cnpj": "2"}], "searchPageFilter": {"totalPagina": 2}},
    }
    pedidas = []

    def fake_get(url, params, **kwargs):
        pedidas.append(params["numeropagina"])
        return RespostaFalsa(paginas[params["numeropagina"]])

    monkeypatch.setattr(revendedores.requests, "get", fake_get)

    destino = revendedores.baixar("SC", tmp_path / "revendedores-SC.json")
    assert pedidas == [1, 2]
    assert json.loads(destino.read_text(encoding="utf-8")) == [{"cnpj": "1"}, {"cnpj": "2"}]


def test_baixar_para_quando_a_pagina_vem_vazia(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_RAW", tmp_path)
    paginas = iter([
        {"data": [{"cnpj": "1"}], "searchPageFilter": {"totalPagina": 9}},
        {"data": [], "searchPageFilter": {"totalPagina": 9}},
    ])
    monkeypatch.setattr(revendedores.requests, "get", lambda *a, **k: RespostaFalsa(next(paginas)))

    destino = revendedores.baixar("SC", tmp_path / "revendedores-SC.json")
    assert json.loads(destino.read_text(encoding="utf-8")) == [{"cnpj": "1"}]


def test_ler_devolve_lista_vazia_quando_nao_foi_baixado(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_RAW", tmp_path)
    monkeypatch.setattr(config, "carimbo", lambda *a, **k: "2026-10-12")
    assert revendedores.ler("AC") == []
    assert revendedores.ler_ufs(["AC", "AL"]) == []


def test_ler_ufs_junta_o_que_foi_baixado(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_RAW", tmp_path)
    monkeypatch.setattr(config, "carimbo", lambda *a, **k: "2026-10-12")
    for uf, quantos in (("SC", 2), ("PR", 1)):
        (tmp_path / f"2026-10-12-revendedores-{uf}.json").write_text(
            json.dumps([{"uf": uf}] * quantos), encoding="utf-8"
        )

    assert len(revendedores.ler_ufs(["SC", "PR"])) == 3
    assert revendedores.postos_por_uf(revendedores.ler_ufs(["SC"])) == {"SC": 2}
