"""Testes da análise (fase 2): indicadores, correlação com p-valor, anomalia, alvo e score.

Tudo com quadro sintético: sem rede, sem depender do dado real da ANP.
"""

from __future__ import annotations

import pandas as pd
import pytest

from combustivelbr import analise


def painel_ufs(ufs: dict[str, list[float]], *, inicio: str = "2024-01") -> pd.DataFrame:
    """Painel preço por UF × mês: ``{"SP": [5.0, 5.1], "SC": [...]}``."""
    linhas = []
    for uf, precos in ufs.items():
        for posicao, preco in enumerate(precos):
            mes = pd.Timestamp(inicio) + pd.DateOffset(months=posicao)
            linhas.append({"uf": uf, "periodo": mes.strftime("%Y-%m"), "preco_medio": preco})
    return pd.DataFrame(linhas)


# ---------------------------------------------------------------- indicador de fiscalização
@pytest.fixture()
def acoes_fisc():
    linhas = []
    for indice in range(15):
        mes = (pd.Timestamp("2024-01") + pd.DateOffset(months=indice)).strftime("%Y-%m")
        linhas.append({"uf": "SP", "periodo": mes, "documento": f"SP-{mes}", "revenda": True,
                       "infracao": True, "interdicao": indice == 14, "municipio": "SAO PAULO"})
        linhas.append({"uf": "SC", "periodo": mes, "documento": f"SC-{mes}", "revenda": True,
                       "infracao": False, "interdicao": False, "municipio": "FLORIANOPOLIS"})
    # ação fora da revenda não conta
    linhas.append({"uf": "SC", "periodo": "2025-03", "documento": "GLP", "revenda": False,
                   "infracao": False, "interdicao": False, "municipio": "FLORIANOPOLIS"})
    return pd.DataFrame(linhas)


def test_ipf_usa_os_ultimos_doze_meses(acoes_fisc):
    ipf = analise.ipf_por_uf(acoes_fisc, {"SP": 500, "SC": 100}).set_index("uf")

    assert ipf.loc["SP", "acoes_12m"] == 12  # 15 meses na base, 12 na janela
    assert ipf.loc["SP", "acoes_total"] == 15
    assert ipf.loc["SP", "ipf"] == pytest.approx(12 / 500 * 1000, abs=0.01)
    assert ipf.loc["SC", "acoes_12m"] == 12  # a ação de GLP fica de fora
    assert ipf.loc["SC", "ipf"] == pytest.approx(120.0, abs=0.01)


def test_ipf_traz_o_periodo_da_janela(acoes_fisc):
    ipf = analise.ipf_por_uf(acoes_fisc, {"SP": 500}).set_index("uf")
    assert ipf.loc["SP", "periodo_inicio"] == "2024-04"
    assert ipf.loc["SP", "periodo_fim"] == "2025-03"


def test_uf_sem_acao_fica_com_zero_e_nao_com_media(acoes_fisc):
    ipf = analise.ipf_por_uf(acoes_fisc, {"SP": 500, "RR": 30}).set_index("uf")
    assert ipf.loc["RR", "acoes_12m"] == 0
    assert ipf.loc["RR", "ipf"] == 0
    assert pd.isna(ipf.loc["RR", "taxa_interdicao"])  # 0/0 não é 0%


def test_taxa_de_interdicao_e_percentual_da_janela(acoes_fisc):
    ipf = analise.ipf_por_uf(acoes_fisc, {"SP": 500}).set_index("uf")
    assert ipf.loc["SP", "taxa_interdicao"] == pytest.approx(1 / 12 * 100, abs=0.01)


def test_dispersao_por_uf_respeita_periodo_de_corte():
    precos = pd.DataFrame({
        "uf": ["SP", "SP", "SC", "SC"],
        "periodo": ["2024-01", "2024-02", "2024-01", "2024-02"],
        "coeficiente_variacao": [0.05, 0.06, 0.02, 0.02],
        "preco_medio": [5.0, 5.1, 6.0, 6.2],
        "postos": [100, 100, 50, 50],
    })
    todos = analise.dispersao_por_uf(precos).set_index("uf")
    so_ultimo = analise.dispersao_por_uf(precos, from_periodo="2024-02").set_index("uf")

    assert todos.loc["SP", "dispersao_cv"] == pytest.approx(0.055, abs=1e-5)
    assert so_ultimo.loc["SP", "dispersao_cv"] == pytest.approx(0.06, abs=1e-5)
    assert so_ultimo.loc["SP", "meses"] == 1


# ---------------------------------------------------------------- correlação com p-valor
def test_amostra_pequena_nao_vira_correlacao():
    resultado = analise.correlacionar(pd.Series([1, 2, 3]), pd.Series([1, 2, 3]))
    assert resultado["r"] is None and resultado["p"] is None
    assert resultado["n"] == 3


def test_correlacao_perfeita_da_um_e_zero():
    x = pd.Series(range(10), dtype=float)
    resultado = analise.correlacionar(x, x * 2 + 1)
    assert resultado["r"] == pytest.approx(1.0)
    assert resultado["p"] < 0.001
    assert resultado["n"] == 10


def test_correlacao_ignora_nulo_e_infinito():
    x = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, None, float("inf")])
    y = pd.Series(range(10), dtype=float)
    resultado = analise.correlacionar(x, y)
    assert resultado["n"] == 8


def test_sem_variacao_nao_da_coeficiente():
    resultado = analise.correlacionar(pd.Series([1.0] * 10), pd.Series(range(10), dtype=float))
    assert resultado["r"] is None


def test_spearman_pega_relacao_nao_linear():
    x = pd.Series(range(1, 21), dtype=float)
    pearson = analise.correlacionar(x, x**3)["r"]
    spearman = analise.correlacionar(x, x**3, metodo="spearman")["r"]
    assert spearman > pearson
    assert spearman == pytest.approx(1.0)


def test_efeito_fixo_tira_a_media_de_cada_uf():
    painel = pd.DataFrame({"uf": ["SP", "SP", "SC", "SC"], "valor": [1.0, 3.0, 10.0, 20.0]})
    fixo = analise._sem_efeito_fixo(painel, ["valor"])
    assert fixo["valor"].tolist() == [-1.0, 1.0, -5.0, 5.0]


def test_pooled_e_intra_uf_podem_discordar_de_SINAL():
    """Nível diferente entre UFs pode inventar correlação: é o teste que separa os dois."""
    # dentro de cada UF a fiscalização cai enquanto o preço sobe; mas SC tem preço
    # muito maior e fiscalização muito maior, o que empurra o agrupado para positivo
    ufs = {"SP": [], "SC": []}
    linhas = []
    for indice in range(10):
        mes = (pd.Timestamp("2024-01") + pd.DateOffset(months=indice)).strftime("%Y-%m")
        linhas.append({"uf": "SP", "periodo": mes, "acoes": 100 - indice * 5, "preco_medio": 5.0 + indice * 0.1})
        linhas.append({"uf": "SC", "periodo": mes, "acoes": 400 - indice * 5, "preco_medio": 9.0 + indice * 0.1})
    acoes = pd.DataFrame(linhas)
    precos = acoes[["uf", "periodo", "preco_medio"]]

    resultado = analise.correlacao_fiscalizacao_preco(acoes[["uf", "periodo", "acoes"]], precos)
    por_nome = {item["nome"]: item for item in resultado["evidencias"]}

    assert por_nome["fiscalizacao_x_preco_pooled"]["r"] > 0
    assert por_nome["fiscalizacao_x_preco_intra_uf"]["r"] == pytest.approx(-1.0)
    assert resultado["ufs"] == 2 and resultado["observacoes"] == 20


def test_correlacao_com_atraso_traz_lag1_e_lag2():
    linhas = []
    for indice in range(12):
        mes = (pd.Timestamp("2024-01") + pd.DateOffset(months=indice)).strftime("%Y-%m")
        linhas.append({"uf": "SP", "periodo": mes, "acoes": float(indice + 1), "preco_medio": 5.0 + indice * 0.1})
    painel = pd.DataFrame(linhas)
    resultado = analise.correlacao_fiscalizacao_preco(painel[["uf", "periodo", "acoes"]],
                                                     painel[["uf", "periodo", "preco_medio"]])
    nomes = {item["nome"] for item in resultado["evidencias"]}
    assert {"fiscalizacao_lag1_x_preco_intra_uf", "fiscalizacao_lag2_x_preco_intra_uf"} <= nomes


# ---------------------------------------------------------------- anomalia do mínimo colado
def municipios_com_folga(*folgas: float, postos: int = 5, municipio: str = "CORUMBA") -> pd.DataFrame:
    return pd.DataFrame({
        "uf": ["MS"] * len(folgas),
        "municipio": [municipio] * len(folgas),
        "periodo": [f"2024-{indice + 1:02d}" for indice in range(len(folgas))],
        "postos": [postos] * len(folgas),
        "preco_medio": [6.0] * len(folgas),
        "preco_minimo": [6.0 * (1 - folga) for folga in folgas],
        "preco_maximo": [6.5] * len(folgas),
    })


def test_anomalia_por_recorrencia():
    municipios = pd.concat([
        municipios_com_folga(0.005, 0.008, 0.01),  # colado nos três meses
        municipios_com_folga(0.2, 0.2),  # mercado disputado
    ])
    resultado = analise.anomalias_minimo_colado(municipios)
    assert list(resultado["municipio"]) == ["CORUMBA"]
    assert resultado["meses_colados"].iloc[0] == 3
    assert resultado["meses"].iloc[0] == 3
    assert resultado["taxa_colada"].iloc[0] == 1.0


def test_anomalia_ordena_quem_esta_colado_em_mais_meses_primeiro():
    municipios = pd.concat([
        municipios_com_folga(0.005, 0.005, 0.2, municipio="A"),  # 2 de 3 meses
        municipios_com_folga(0.005, 0.005, 0.005, 0.005, municipio="B"),  # 4 de 4 meses
    ])
    resultado = analise.anomalias_minimo_colado(municipios)
    assert list(resultado["municipio"]) == ["B", "A"]
    assert resultado["meses_colados"].tolist() == [4, 2]
    assert resultado["taxa_colada"].tolist() == [1.0, 0.667]


def test_municipio_com_poucos_postos_sai_da_anomalia():
    municipios = municipios_com_folga(0.001, 0.001, postos=2)
    assert analise.anomalias_minimo_colado(municipios).empty


def test_sem_anomalia_devolve_quadro_vazio():
    assert analise.anomalias_minimo_colado(municipios_com_folga(0.3, 0.4)).empty


# ---------------------------------------------------------------- zona cega
def test_zona_cega_e_pouca_fiscalizacao_com_preco_disperso():
    ipf = pd.DataFrame({"uf": list("ABCD"), "ipf": [1.0, 2.0, 50.0, 90.0]})
    dispersao = pd.DataFrame({
        "uf": list("ABCD"),
        "dispersao_cv": [0.10, 0.02, 0.09, 0.01],
        "preco_medio": [6.0, 6.0, 6.0, 6.0],
    })
    resultado = analise.zonas_cegas(ipf, dispersao).set_index("uf")

    assert bool(resultado.loc["A", "zona_cega"]) is True  # IPF baixo e dispersão alta
    assert bool(resultado.loc["B", "zona_cega"]) is False  # IPF baixo, mas preço colado
    assert bool(resultado.loc["D", "zona_cega"]) is False  # disperso, mas muito fiscalizado
    assert resultado["zona_cega"].iloc[0]  # as zonas cegas vêm primeiro


# ---------------------------------------------------------------- alvos e score de fiscalização
@pytest.fixture()
def municipios_preco():
    linhas = []
    for municipio, desvio, preco in [("DISPERSO", 0.9, 6.0), ("COLADO", 0.05, 6.0),
                                     ("CARO", 0.2, 7.5), ("NORMAL", 0.2, 6.0)]:
        for mes in range(1, 4):
            linhas.append({
                "uf": "SP", "municipio": municipio, "periodo": f"2024-{mes:02d}",
                "postos": 20, "preco_medio": preco, "preco_minimo": preco - desvio / 2,
                "desvio": desvio,
            })
    return pd.DataFrame(linhas)


def test_alvo_junta_dispersao_fiscalizacao_e_variacao(municipios_preco):
    fisc = pd.DataFrame({
        "uf": ["SP", "SP"],
        "municipio": ["DISPERSO", "NORMAL"],
        "acoes": [0, 50],  # o disperso não recebeu nenhuma ação; o normal, 50
        "interdicoes": [0, 0],
    })
    alvos = analise.score_fiscal(municipios_preco, fisc).set_index("municipio")

    assert alvos.loc["DISPERSO", "score"] == alvos["score"].max()  # disperso e sem fiscalização
    assert alvos.loc["DISPERSO", "comp_dispersao"] == 1.0
    assert alvos.loc["DISPERSO", "comp_fiscalizacao"] == 1.0  # sem ação nenhuma
    assert alvos.loc["NORMAL", "comp_fiscalizacao"] == 0.0  # o mais fiscalizado por posto
    assert alvos.loc["COLADO", "comp_dispersao"] == 0.0
    assert alvos.loc["CARO", "comp_variacao"] == 1.0  # fugiu da mediana da UF


def test_pesos_do_score_mudam_o_resultado(municipios_preco):
    fisc = pd.DataFrame({"uf": ["SP"], "municipio": ["DISPERSO"], "acoes": [0], "interdicoes": [0]})
    so_dispersao = analise.score_fiscal(
        municipios_preco, fisc, pesos={"dispersao": 1.0, "fiscalizacao": 0, "interdicao": 0, "variacao": 0}
    ).set_index("municipio")
    assert so_dispersao.loc["DISPERSO", "score"] == 1.0
    assert so_dispersao.loc["COLADO", "score"] == 0.0


def test_alvo_com_nome_de_municipio_diferente_fica_sem_fiscalizacao(municipios_preco):
    alvos = analise.score_fiscal(municipios_preco, pd.DataFrame(
        columns=["uf", "municipio", "acoes", "interdicoes"]
    )).set_index("municipio")
    assert alvos["acoes_municipio"].eq(0).all()


def test_municipio_com_menos_de_tres_postos_nao_e_alvo():
    precos = pd.DataFrame({
        "uf": ["SP"], "municipio": ["PEQUENO"], "periodo": ["2024-01"],
        "postos": [2], "preco_medio": [6.0], "preco_minimo": [5.0], "desvio": [1.0],
    })
    alvos = analise.score_fiscal(precos, pd.DataFrame(columns=["uf", "municipio", "acoes", "interdicoes"]))
    assert alvos.empty


def test_limite_de_alvos_e_respeitado(municipios_preco):
    alvos = analise.score_fiscal(
        municipios_preco, pd.DataFrame(columns=["uf", "municipio", "acoes", "interdicoes"]), limite=2
    )
    assert len(alvos) == 2


# ---------------------------------------------------------------- estabilidade e score de evidência
def test_estabilidade_temporal_zero_quando_o_sinal_inverte():
    linhas = []
    for indice in range(12):
        linhas.append({
            "uf": "SP",
            "periodo": (pd.Timestamp("2024-01") + pd.DateOffset(months=indice)).strftime("%Y-%m"),
            "x": float(indice if indice < 6 else 11 - indice),
            "y": float(indice),
        })
    painel = pd.DataFrame(linhas)
    assert analise.estabilidade_temporal(painel, coluna_x="x", coluna_y="y") == 0.0


def test_estabilidade_temporal_alta_quando_o_sinal_se_mantem():
    linhas = []
    for indice in range(12):
        linhas.append({
            "uf": "SP",
            "periodo": (pd.Timestamp("2024-01") + pd.DateOffset(months=indice)).strftime("%Y-%m"),
            "x": float(indice),
            "y": float(indice * 2),
        })
    painel = pd.DataFrame(linhas)
    assert analise.estabilidade_temporal(painel, coluna_x="x", coluna_y="y") == 1.0


def test_estabilidade_amostral_cai_quando_as_metades_discordam():
    concordante = pd.DataFrame({"x": range(20), "y": range(20)})
    discordante = pd.DataFrame({"x": list(range(20)), "y": list(range(10)) + list(range(10, 0, -1))})

    assert analise.estabilidade_amostral(concordante, coluna_x="x", coluna_y="y") == 1.0
    assert analise.estabilidade_amostral(discordante, coluna_x="x", coluna_y="y") < 0.5


def test_score_de_evidencia_sem_evidencia_valida_e_zero():
    assert analise.score_evidencia([{"nome": "x", "r": None, "p": None, "n": 3}])["score"] == 0.0
    assert analise.score_evidencia([])["score"] == 0.0


def test_evidencia_fraca_baixa_o_score_do_conjunto():
    forte = {"nome": "forte", "r": 0.8, "p": 0.0, "n": 500, "estabilidade": 1.0}
    fraca = {"nome": "fraca", "r": 0.02, "p": 0.95, "n": 500, "estabilidade": 1.0}

    so_forte = analise.score_evidencia([forte])
    com_fraca = analise.score_evidencia([forte, fraca])

    assert so_forte["score"] == pytest.approx(0.8)
    assert com_fraca["score"] < so_forte["score"]
    # a fraca contribui quase nada, mas entra na média
    assert com_fraca["detalhes"][1]["contribuicao"] == pytest.approx(0.02 * 0.05, abs=1e-4)


def test_estabilidade_zerada_anula_a_contribuicao():
    instavel = {"nome": "instavel", "r": 0.9, "p": 0.0, "n": 500, "estabilidade": 0.0}
    assert analise.score_evidencia([instavel])["score"] == 0.0


# ---------------------------------------------------------------- interdição × preço
def quadro_de_interdicoes(ufs: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "uf": ufs,
        "municipio": [f"MUNICIPIO-{indice}" for indice in range(len(ufs))],
        "periodo": ["2024-06"] * len(ufs),
        "interdicao": [True] * len(ufs),
        "revenda": [True] * len(ufs),
        "documento": [f"DF-{indice}" for indice in range(len(ufs))],
    })


def precos_municipio(delta_controle: float, efeito: float, *, ufs: list[str] | None = None) -> pd.DataFrame:
    """Preço do município alvo e de um vizinho de controle na mesma UF.

    Os dois partem do mesmo nível no período anterior; depois do mês do auto, o vizinho
    sobe ``delta_controle`` (a tendência comum) e o alvo sobe ``delta_controle + efeito``.
    O efeito próprio varia um pouco entre municípios para o posto não empatar tudo.
    """
    ufs = ufs or ["SP"] * 8
    periodos = ["2024-03", "2024-04", "2024-05", "2024-06", "2024-07", "2024-08"]
    linhas = []
    for indice, uf in enumerate(ufs):
        base = 6.0
        efeito_do_municipio = efeito * (1 + indice * 0.01)
        for posicao, periodo in enumerate(periodos):
            depois = posicao >= 3
            linhas.append({"uf": uf, "municipio": f"MUNICIPIO-{indice}", "periodo": periodo,
                           "preco_medio": base + (delta_controle + efeito_do_municipio if depois else 0.0)})
            linhas.append({"uf": uf, "municipio": f"VIZINHO-{indice}", "periodo": periodo,
                           "preco_medio": base + (delta_controle if depois else 0.0)})
    return pd.DataFrame(linhas)


def test_interdicao_sem_efeito_proprio_e_absorvida_pelo_controle():
    """Quando o município sobe igual ao resto da UF, o efeito é zero."""
    resultado = analise.interdição_x_preco(quadro_de_interdicoes(["SP"] * 8), precos_municipio(0.4, 0.0))
    assert resultado["n"] == 8
    assert resultado["efeito"] == pytest.approx(0.0, abs=1e-6)
    assert resultado["delta_bruto_medio"] == resultado["delta_controle_medio"]
    assert resultado["leitura"] == "sem diferença detectável contra o controle"


def test_interdicao_com_efeito_proprio_aparece_no_resultado():
    resultado = analise.interdição_x_preco(quadro_de_interdicoes(["SP"] * 8), precos_municipio(0.1, 0.5))
    assert resultado["efeito"] > 0
    assert resultado["delta_bruto_medio"] > resultado["delta_controle_medio"]
    assert resultado["efeito_pct"] > 0
    assert resultado["p"] < 0.05
    assert "sobe" in resultado["leitura"]


def test_interdicao_com_amostra_pequena_avisa():
    resultado = analise.interdição_x_preco(
        quadro_de_interdicoes(["SP"] * 3), precos_municipio(0.1, 0.5, ufs=["SP"] * 3)
    )
    assert resultado["n"] == 3
    assert resultado["efeito"] is None
    assert resultado["leitura"] == "amostra pequena demais"


def test_interdicao_sem_preco_nao_quebra():
    resultado = analise.interdição_x_preco(quadro_de_interdicoes(["SP"] * 8), pd.DataFrame(
        columns=["uf", "municipio", "periodo", "preco_medio", "preco_minimo", "postos", "desvio"]
    ))
    assert resultado["n"] == 0


# ---------------------------------------------------------------- limitações e contrato publicado
def test_limitacoes_derivam_da_cobertura():
    limitacoes = analise.limitacoes_projeto(
        {"interdicoes_revenda": 15162}, meses_preco=45, municipios_preco=461
    )
    texto = " ".join(limitacoes)

    assert len(limitacoes) == 10
    assert "461 municípios" in texto and "45 meses" in texto
    assert "statusSIGAF" in texto
    assert "multa" in texto.lower()
    assert "Correlação não é causa" in texto
    # desvios do pedido original declarados: semanal, km² e denúncia por município
    assert "semanal" in texto and "km²" in texto and "denúncia" in texto


def test_limitacoes_sem_interdicao_nao_falam_de_recurso():
    limitacoes = analise.limitacoes_projeto({}, meses_preco=1, municipios_preco=1)
    assert len(limitacoes) == 9
    assert "recurso" not in " ".join(limitacoes)


def test_ufs_publicadas_trazem_acoes_acumuladas_sem_coluna_duplicada():
    """Regressão: repetir o merge do IPF renomeia as colunas para ``_x``/``_y`` e o campo some."""
    ipf = pd.DataFrame({
        "uf": ["SP"], "postos": [10], "acoes_12m": [5], "acoes_total": [40], "infracoes_12m": [2],
        "interdicoes_12m": [1], "ipf": [500.0], "ipf_acumulado": [4000.0], "taxa_interdicao": [20.0],
        "periodo_inicio": ["2025-10"], "periodo_fim": ["2026-09"],
    })
    dispersao = pd.DataFrame({"uf": ["SP"], "dispersao_cv": [0.05], "preco_medio": [6.0]})
    payload = analise.montar_inteligencia(
        ufs=analise.zonas_cegas(ipf, dispersao),
        evidencias=[],
        anomalias=pd.DataFrame(),
        alvos=pd.DataFrame(),
        interditados=pd.DataFrame(),
        interdição={"n": 0},
        cobertura={},
        periodos={},
        score={"score": 0.0, "evidencias": 0},
        pesos={},
    )

    publicado = payload["ufs"][0]
    assert publicado["acoes_total"] == 40
    assert publicado["ipf_acumulado"] == 4000.0
    assert not [chave for chave in publicado if chave.endswith(("_x", "_y"))]
    assert payload["limitacoes"]  # as limitações vão junto do artefato


def test_regra_do_loop_aceita_a_partir_de_cinco_por_cento():
    assert analise.decidir_ciclo(1.0, 1.05)["decisao"] == "ACEITO"  # no corte, aceita
    assert analise.decidir_ciclo(1.0, 1.0499)["decisao"] == "REJEITADO"  # logo abaixo, rejeita
    assert analise.decidir_ciclo(1.0, 1.0)["decisao"] == "REJEITADO"  # empate não é ganho


def test_regra_do_loop_registra_o_ganho():
    veredito = analise.decidir_ciclo(0.05, 0.06)
    assert veredito["decisao"] == "ACEITO"
    assert veredito["ganho"] == 0.2
    assert analise.decidir_ciclo(0.05, 0.04)["decisao"] == "REJEITADO"


def test_regra_do_loop_nao_aceita_tudo_quando_o_score_de_partida_e_zero():
    """Com score inicial 0 não existe ganho percentual: só aceita quem cria evidência."""
    assert analise.decidir_ciclo(0.0, 0.02)["decisao"] == "ACEITO"
    assert analise.decidir_ciclo(0.0, 0.0)["decisao"] == "REJEITADO"
    assert analise.decidir_ciclo(0.0, 0.0)["ganho"] is None

def test_parametro_que_nao_move_a_metrica_nao_e_rejeitado():
    """Pesos do score fiscal não mexem nas correlações: dizer "rejeitado" seria falso."""
    veredito = analise.decidir_ciclo(0.0579, 0.0579, move_score=False)
    assert veredito["decisao"] == "SEM EFEITO NA MÉTRICA"
    # mas se mexer no número, volta a valer a regra normal
    assert analise.decidir_ciclo(0.0579, 0.0400, move_score=False)["decisao"] == "REJEITADO"
    assert analise.decidir_ciclo(0.0579, 0.0579)["decisao"] == "REJEITADO"


def test_leitura_do_coeficiente_nao_exagera():
    assert "sem evidência" in analise.leitura(0.9, 0.4)
    assert "sem amostra" in analise.leitura(None, None)
    assert "forte" in analise.leitura(-0.9, 0.0)
    assert "andam em direções opostas" in analise.leitura(-0.2, 0.01)
