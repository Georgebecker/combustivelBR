"""Correlações entre fiscalização da ANP e preço na bomba (fase 2).

Cada número publicado aqui sai com **coeficiente, p-valor e n**. Sem isso não é
achado, é palpite — e o prompt do projeto proíbe publicar correlação sem os dois.

Fórmulas implementadas (C1 a C7 do prompt da fase 2):

- **C1 IPF** = ações de fiscalização na revenda nos últimos 12 meses por 1.000 postos
  ativos (a API de revendedores dá o denominador). O prompt sugeria dividir por 1.000;
  o acumulado desde 1998 usa denominador de hoje, então o indicador publicável é a
  janela de 12 meses (o acumulado também vai no JSON, como contexto).
- **C2 TI** = autos de interdição / ações × 100, por UF.
- **C3 anomalia** = (médio − mínimo) / médio < 2% no município (mínimo colado na média).
- **C4 correlação** = fiscalização mensal × preço mensal, no painel UF × mês, em duas
  leituras: *pooled* (todas as observações) e *intra-UF* (descontada a média da UF, que
  é o teste honesto: sem isso a correlação pode virar só diferença de nível entre UFs).
- **C5 zonas cegas** = UF no quartil de menor IPF com dispersão acima da mediana.
- **C6 interdição × preço** = preço do município antes e depois do auto de interdição
  (comparação pareada, com p-valor de Wilcoxon).
- **C7 alvos** = score composto por dispersão, fiscalização (inverso), interdição e
  variação anômala, com pesos em ``config.PESOS_SCORE_FISCAL``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats

from . import config, fiscalizacao

# Janela do indicador de fiscalização (meses).
JANELA_IPF_MESES = 12
# Tamanho mínimo de amostra para publicar correlação.
MINIMO_OBSERVACOES = 8
# Mínimo por metade da amostra nos testes de estabilidade (metade de 8).
MINIMO_ESTABILIDADE = 4
# C3: folga mínima entre mínimo e média para o mês contar como "colado" (2%).
LIMITE_ANOMALIA = 0.02
# C3: município com menos postos que isso não entra (amostra pequena demais).
MINIMO_POSTOS_ANOMALIA = 3
# Ganho mínimo de score para o loop noturno aceitar um ciclo (5%, do prompt da fase 2).
GANHO_MINIMO_LOOP = 0.05
# Quantos alvos e anomalias entram no JSON publicado.
LIMITE_ALVOS = 15
LIMITE_ANOMALIAS = 15
LIMITE_INTERDITOS = 20


def _ultimos_periodos(periodos: pd.Series, meses: int) -> list[str]:
    return sorted(periodos.dropna().unique())[-meses:]


def ipf_por_uf(
    acoes: pd.DataFrame,
    postos: dict[str, int],
    *,
    meses: int = JANELA_IPF_MESES,
) -> pd.DataFrame:
    """C1: ações nos últimos ``meses`` e ações acumuladas, por UF, por 1.000 postos."""
    recorte = acoes[acoes["revenda"]]
    periodos = _ultimos_periodos(recorte["periodo"], meses)
    recentes = recorte[recorte["periodo"].isin(periodos)]

    resumo = pd.DataFrame({"uf": sorted(postos)})
    resumo["postos"] = resumo["uf"].map(postos)

    total = recorte.groupby("uf").size().rename("acoes_total")
    recente = recentes.groupby("uf").agg(
        acoes_12m=("documento", "size"),
        interdicoes_12m=("interdicao", "sum"),
        infracoes_12m=("infracao", "sum"),
        municipios_12m=("municipio", "nunique"),
    )
    resumo = resumo.merge(total, on="uf", how="left").merge(recente, on="uf", how="left")
    resumo[["acoes_total", "acoes_12m", "interdicoes_12m", "infracoes_12m", "municipios_12m"]] = (
        resumo[["acoes_total", "acoes_12m", "interdicoes_12m", "infracoes_12m", "municipios_12m"]]
        .fillna(0)
        .astype(int)
    )

    resumo["ipf"] = (resumo["acoes_12m"] / resumo["postos"] * 1000).round(2)
    resumo["ipf_acumulado"] = (resumo["acoes_total"] / resumo["postos"] * 1000).round(2)
    resumo["taxa_interdicao"] = (resumo["interdicoes_12m"] / resumo["acoes_12m"].replace(0, np.nan) * 100).round(2)
    resumo["periodo_inicio"] = periodos[0] if periodos else ""
    resumo["periodo_fim"] = periodos[-1] if periodos else ""
    return resumo.sort_values("ipf", ascending=False).reset_index(drop=True)


def dispersao_por_uf(precos_uf_mes: pd.DataFrame, *, from_periodo: str | None = None) -> pd.DataFrame:
    """Coeficiente de variação médio do preço dentro de cada UF (revenda contra revenda)."""
    recorte = precos_uf_mes
    if from_periodo:
        recorte = recorte[recorte["periodo"] >= from_periodo]
    resumo = recorte.groupby("uf", as_index=False).agg(
        dispersao_cv=("coeficiente_variacao", "mean"),
        preco_medio=("preco_medio", "mean"),
        postos_amostra=("postos", "mean"),
        meses=("periodo", "nunique"),
    )
    return resumo.round({"dispersao_cv": 5, "preco_medio": 4, "postos_amostra": 1}).sort_values(
        "dispersao_cv", ascending=False
    ).reset_index(drop=True)


def correlacionar(
    x: pd.Series, y: pd.Series, *, metodo: str = "pearson", minimo: int = MINIMO_OBSERVACOES
) -> dict:
    """Coeficiente com p-valor e n. Amostra pequena devolve ``r=None``.

    ``minimo`` existe para os testes internos de estabilidade, que rodam sobre metade
    da amostra: o corte de publicação (``MINIMO_OBSERVACOES``) continua valendo para o
    que vai no JSON.
    """
    pares = pd.DataFrame({"x": x, "y": y}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(pares) < minimo or pares["x"].nunique() < 2 or pares["y"].nunique() < 2:
        return {"metodo": metodo, "r": None, "p": None, "n": int(len(pares))}

    if metodo == "spearman":
        r, p = stats.spearmanr(pares["x"], pares["y"])
    else:
        r, p = stats.pearsonr(pares["x"], pares["y"])
    return {"metodo": metodo, "r": round(float(r), 4), "p": round(float(p), 6), "n": int(len(pares))}


def _sem_efeito_fixo(painel: pd.DataFrame, colunas: list[str], grupo: str = "uf") -> pd.DataFrame:
    """Tira a média de cada UF: sobra a variação dentro da UF (efeito fixo por UF)."""
    return painel.copy().assign(**{
        coluna: painel[coluna] - painel.groupby(grupo)[coluna].transform("mean") for coluna in colunas
    })


def correlacao_fiscalizacao_preco(
    acoes_uf_mes: pd.DataFrame,
    precos_uf_mes: pd.DataFrame,
    *,
    from_periodo: str | None = None,
    com_efeito_fixo: bool = True,
    atrasos: Sequence[int] = (1, 2),
    metodo: str = "pearson",
) -> dict:
    """C4: no painel UF × mês, fiscalização e preço andam juntos?"""
    # colunas fixadas: se as duas pontas trouxerem ``preco_medio``, o merge criaria
    # ``preco_medio_x``/``_y`` e todo mundo abaixo falharia com KeyError
    painel = acoes_uf_mes[["uf", "periodo", "acoes"]].merge(
        precos_uf_mes[["uf", "periodo", "preco_medio"]], on=["uf", "periodo"], how="inner"
    )
    if from_periodo:
        painel = painel[painel["periodo"] >= from_periodo]
    painel = painel.sort_values(["uf", "periodo"])

    evidencias: list[dict] = []
    pooled_pearson = correlacionar(painel["acoes"], painel["preco_medio"], metodo=metodo)
    pooled_spearman = correlacionar(painel["acoes"], painel["preco_medio"], metodo="spearman")
    evidencias.append({**pooled_pearson, "nome": "fiscalizacao_x_preco_pooled"})
    evidencias.append({**pooled_spearman, "nome": "fiscalizacao_x_preco_pooled_spearman"})

    if com_efeito_fixo:
        fixo = _sem_efeito_fixo(painel, ["acoes", "preco_medio"])
        evidencias.append({**correlacionar(fixo["acoes"], fixo["preco_medio"], metodo=metodo),
                           "nome": "fiscalizacao_x_preco_intra_uf"})
        # preço de hoje contra fiscalização de alguns meses antes (fiscalização reage ou precede?)
        painel_lag = painel.copy()
        for atraso in atrasos:
            painel_lag[f"acoes_lag{atraso}"] = painel_lag.groupby("uf")["acoes"].shift(atraso)
            fixo_lag = _sem_efeito_fixo(painel_lag.dropna(subset=[f"acoes_lag{atraso}"]),
                                        [f"acoes_lag{atraso}", "preco_medio"])
            evidencias.append({
                **correlacionar(fixo_lag[f"acoes_lag{atraso}"], fixo_lag["preco_medio"], metodo=metodo),
                "nome": f"fiscalizacao_lag{atraso}_x_preco_intra_uf",
            })

    return {
        "painel": painel,
        "evidencias": evidencias,
        "meses": int(painel["periodo"].nunique()),
        "ufs": int(painel["uf"].nunique()),
        "observacoes": int(len(painel)),
    }


def anomalias_minimo_colado(
    municipios: pd.DataFrame, *, limite: float = LIMITE_ANOMALIA, minimo_postos: int = MINIMO_POSTOS_ANOMALIA
) -> pd.DataFrame:
    """C3: municípios em que o preço mínimo está colado na média (nem os postos brigam).

    O sinal não é um mês solto — é a **recorrência**: um município onde o mínimo fica a
    2% da média em vários meses seguidos não se comporta como mercado disputado.
    """
    recorte = municipios[municipios["postos"] >= minimo_postos].copy()
    if recorte.empty:
        return recorte

    recorte["folga"] = (recorte["preco_medio"] - recorte["preco_minimo"]) / recorte["preco_medio"]
    recorte["colado"] = recorte["folga"] < limite

    por_municipio = recorte.groupby(["uf", "municipio"], as_index=False).agg(
        meses=("periodo", "nunique"),
        meses_colados=("colado", "sum"),
        folga_media=("folga", "mean"),
        postos=("postos", "median"),
        preco_medio=("preco_medio", "mean"),
        preco_minimo=("preco_minimo", "min"),
        preco_maximo=("preco_maximo", "max"),
        ultimo_periodo=("periodo", "max"),
    )
    por_municipio = por_municipio[por_municipio["meses_colados"] >= 1].copy()
    por_municipio["taxa_colada"] = (por_municipio["meses_colados"] / por_municipio["meses"]).round(3)
    por_municipio["folga_pct"] = (por_municipio["folga_media"] * 100).round(3)
    por_municipio["amplitude"] = (por_municipio["preco_maximo"] - por_municipio["preco_minimo"]).round(3)
    por_municipio = por_municipio.round({"preco_medio": 4, "preco_minimo": 3, "preco_maximo": 3})

    return por_municipio.sort_values(
        ["taxa_colada", "meses_colados", "folga_media"], ascending=[False, False, True]
    ).reset_index(drop=True)


def interdição_x_preco(
    acoes: pd.DataFrame,
    precos_municipio: pd.DataFrame,
    *,
    periodo_minimo: str = "2023-01",
    janela_meses: int = 3,
) -> dict:
    """C6: o preço do município cai depois de um auto de interdição?

    O preço sobe no país inteiro ao longo do tempo, então comparar "antes" com "depois"
    só mediria a tendência. O teste é de diferença em diferenças: o mesmo cálculo é feito
    para os demais municípios da UF (o controle) e o efeito é o **excesso** do município
    interditado sobre esse controle, na mesma janela.

    Só entram municípios presentes na amostra de preço antes e depois, e o p-valor sai de
    Wilcoxon sobre os efeitos pareados.
    """
    interditados = acoes[acoes["interdicao"] & acoes["revenda"] & (acoes["periodo"] >= periodo_minimo)]
    if interditados.empty or precos_municipio.empty:
        return {"n": 0, "efeito": None, "p": None, "leitura": "sem dados suficientes"}

    precos = precos_municipio.copy()
    periodos = sorted(precos["periodo"].unique())
    indice = {periodo: posicao for posicao, periodo in enumerate(periodos)}

    pares = []
    for (uf, municipio), grupo in interditados.groupby(["uf", "municipio"]):
        primeiro = grupo["periodo"].min()
        posicao = indice.get(primeiro)
        if posicao is None or posicao < janela_meses:
            continue
        antes = periodos[max(posicao - janela_meses, 0):posicao]
        depois = periodos[posicao:posicao + janela_meses]
        if not antes or not depois:
            continue

        do_municipio = precos_get(precos, uf, municipio)
        if do_municipio is None:
            continue
        p_antes = do_municipio[do_municipio["periodo"].isin(antes)]["preco_medio"]
        p_depois = do_municipio[do_municipio["periodo"].isin(depois)]["preco_medio"]
        if p_antes.empty or p_depois.empty:
            continue

        # controle: os outros municípios da mesma UF, nos mesmos meses
        da_uf = precos[(precos["uf"] == uf) & (precos["municipio"] != municipio)]
        c_antes = da_uf[da_uf["periodo"].isin(antes)].groupby("periodo")["preco_medio"].mean()
        c_depois = da_uf[da_uf["periodo"].isin(depois)].groupby("periodo")["preco_medio"].mean()
        if c_antes.empty or c_depois.empty:
            continue

        delta_tratado = float(p_depois.mean() - p_antes.mean())
        delta_controle = float(c_depois.mean() - c_antes.mean())
        pares.append(
            {
                "uf": uf,
                "municipio": municipio,
                "periodo": primeiro,
                "antes": float(p_antes.mean()),
                "depois": float(p_depois.mean()),
                "delta": delta_tratado,
                "delta_controle": delta_controle,
                "efeito": delta_tratado - delta_controle,
            }
        )

    if len(pares) < MINIMO_OBSERVACOES:
        return {"n": len(pares), "efeito": None, "p": None, "leitura": "amostra pequena demais"}

    quadro = pd.DataFrame(pares)
    efeito = quadro["efeito"].mean()
    if quadro["efeito"].abs().sum() == 0:
        # todo mundo com efeito exatamente zero: não há o que ranquear (e o Wilcoxon
        # divide por zero aqui) — a resposta honesta é "sem diferença"
        estatistica, p_valor = 0.0, 1.0
    else:
        estatistica, p_valor = stats.wilcoxon(quadro["efeito"])
    if p_valor < 0.05:
        leitura = ("preço sobe mais que o controle depois da interdição" if efeito > 0
                   else "preço cai mais que o controle depois da interdição")
    else:
        leitura = "sem diferença detectável contra o controle"

    return {
        "n": int(len(quadro)),
        "efeito": round(float(efeito), 4),
        "efeito_pct": round(float(efeito / quadro["antes"].mean() * 100), 3),
        "delta_bruto_medio": round(float(quadro["delta"].mean()), 4),
        "delta_controle_medio": round(float(quadro["delta_controle"].mean()), 4),
        "p": round(float(p_valor), 6),
        "estatistica": round(float(estatistica), 3),
        "leitura": leitura,
        "exemplos": quadro.sort_values("efeito").head(5).round(4).to_dict(orient="records"),
    }


def precos_get(precos_municipio: pd.DataFrame, uf: str, municipio: str) -> pd.DataFrame | None:
    """Recorte do município no quadro de preços (nome já normalizado nos dois lados)."""
    if precos_municipio.empty:
        return None
    recorte = precos_municipio[
        (precos_municipio["uf"] == uf) & (precos_municipio["municipio"] == municipio)
    ]
    return recorte if not recorte.empty else None


def zonas_cegas(ipf: pd.DataFrame, dispersao: pd.DataFrame) -> pd.DataFrame:
    """C5: fiscaliza pouco e o preço varia muito dentro da UF."""
    quadro = ipf.merge(dispersao[["uf", "dispersao_cv", "preco_medio"]], on="uf", how="inner")
    corte_ipf = quadro["ipf"].quantile(0.25)
    corte_disp = quadro["dispersao_cv"].median()
    quadro["zona_cega"] = (quadro["ipf"] <= corte_ipf) & (quadro["dispersao_cv"] >= corte_disp)
    quadro["corte_ipf_q1"] = round(float(corte_ipf), 2)
    quadro["corte_dispersao_mediana"] = round(float(corte_disp), 5)
    return quadro.sort_values(["zona_cega", "dispersao_cv"], ascending=[False, False]).reset_index(drop=True)


def _normalizar(serie: pd.Series, *, invertido: bool = False) -> pd.Series:
    """Escala 0 a 1 para somar variáveis de unidades diferentes."""
    if serie.nunique() < 2:
        return pd.Series(0.5, index=serie.index)
    escalado = (serie - serie.min()) / (serie.max() - serie.min())
    return 1 - escalado if invertido else escalado


def score_fiscal(
    municipios_preco: pd.DataFrame,
    fisc_municipio: pd.DataFrame,
    *,
    pesos: dict[str, float] | None = None,
    limite: int = LIMITE_ALVOS,
) -> pd.DataFrame:
    """C7: onde um fiscal olharia primeiro.

    Componentes (tudo normalizado 0–1, quanto maior mais suspeito):
    ``dispersao`` (preço varia muito entre postos do mesmo município),
    ``fiscalizacao`` (pouca ação em relação ao tamanho do mercado),
    ``interdicao`` (histórico de interdição no município),
    ``variacao`` (o preço do município fugiu da média da UF).
    """
    pesos = pesos or config.PESOS_SCORE_FISCAL
    # uma linha por município: o alvo é o lugar, não o mês
    precos = municipios_preco.copy()
    precos["desvio_relativo"] = precos["desvio"] / precos["preco_medio"]
    media_uf = precos.groupby(["uf", "periodo"])["preco_medio"].transform("median")
    precos["variacao_uf"] = (precos["preco_medio"] / media_uf - 1).abs()

    municipios = precos.groupby(["uf", "municipio"], as_index=False).agg(
        meses=("periodo", "nunique"),
        postos=("postos", "median"),
        preco_medio=("preco_medio", "mean"),
        desvio_relativo=("desvio_relativo", "mean"),
        variacao_uf=("variacao_uf", "mean"),
    )
    municipios = municipios[municipios["postos"] >= 3].copy()

    fisc = fisc_municipio.rename(columns={"acoes": "acoes_municipio", "interdicoes": "interdicoes_municipio"})
    quadro = municipios.merge(
        fisc[["uf", "municipio", "acoes_municipio", "interdicoes_municipio"]],
        on=["uf", "municipio"],
        how="left",
    )
    quadro[["acoes_municipio", "interdicoes_municipio"]] = (
        quadro[["acoes_municipio", "interdicoes_municipio"]].fillna(0).astype(int)
    )

    # fiscalização por posto do município (quanto menor, menos vigiado)
    quadro["fiscal_por_posto"] = quadro["acoes_municipio"] / quadro["postos"].replace(0, np.nan)

    componentes = {
        "dispersao": _normalizar(quadro["desvio_relativo"]),
        "fiscalizacao": _normalizar(quadro["fiscal_por_posto"].fillna(0), invertido=True),
        "interdicao": _normalizar(quadro["interdicoes_municipio"].astype(float)),
        "variacao": _normalizar(quadro["variacao_uf"]),
    }
    quadro["score"] = sum(componentes[nome] * peso for nome, peso in pesos.items()).round(4)
    for nome, valores in componentes.items():
        quadro[f"comp_{nome}"] = valores.round(4)

    return quadro.sort_values("score", ascending=False).head(limite).reset_index(drop=True)


def estabilidade_temporal(painel: pd.DataFrame, *, coluna_x: str, coluna_y: str) -> float:
    """Quanto o coeficiente muda entre a primeira e a segunda metade da série.

    1 = mesmo sinal e tamanho parecido; 0 = o achado não se sustenta no tempo.
    """
    if painel.empty or painel["periodo"].nunique() < 6:
        return 0.0
    periodos = sorted(painel["periodo"].unique())
    meio = len(periodos) // 2
    primeiros = painel[painel["periodo"].isin(periodos[:meio])]
    ultimos = painel[painel["periodo"].isin(periodos[meio:])]
    r1 = correlacionar(primeiros[coluna_x], primeiros[coluna_y], minimo=MINIMO_ESTABILIDADE).get("r")
    r2 = correlacionar(ultimos[coluna_x], ultimos[coluna_y], minimo=MINIMO_ESTABILIDADE).get("r")
    if r1 is None or r2 is None:
        return 0.0
    if (r1 > 0) != (r2 > 0):
        return 0.0
    return round(max(0.0, 1 - abs(r1 - r2) / max(abs(r1), abs(r2), 1e-9)), 4)


def estabilidade_amostral(
    quadro: pd.DataFrame, *, coluna_x: str, coluna_y: str, partes: int = 2
) -> float:
    """Estabilidade para correlação transversal: quebra a amostra em partes e compara.

    Sem série temporal não há "mudou com o tempo": o teste possível é ver se o
    coeficiente sobrevive quando a amostra é cortada ao meio.
    """
    if quadro.empty or len(quadro) < partes * MINIMO_ESTABILIDADE:
        return 0.0
    coeficientes = []
    for indice in np.array_split(np.arange(len(quadro)), partes):
        parte = quadro.iloc[indice]
        r = correlacionar(parte[coluna_x], parte[coluna_y], minimo=MINIMO_ESTABILIDADE).get("r")
        if r is None:
            return 0.0
        coeficientes.append(r)
    if any((r > 0) != (coeficientes[0] > 0) for r in coeficientes):
        return 0.0
    maior = max(abs(r) for r in coeficientes) or 1e-9
    return round(max(0.0, 1 - (max(coeficientes) - min(coeficientes)) / maior), 4)


def decidir_ciclo(
    antes: float, depois: float, *, move_score: bool = True, ganho_minimo: float = GANHO_MINIMO_LOOP
) -> dict:
    """Regra do loop noturno: só aceita se o score subir pelo menos ``ganho_minimo``.

    ``move_score=False`` é para os botões que **não** mexem na métrica (pesos do score fiscal,
    limiar de anomalia): quando o número não muda, o certo é dizer que a métrica é cega para
    eles, não carimbar "rejeitado" numa hipótese que nunca foi medida.
    """
    if antes <= 0:
        # Sem evidência válida não existe ganho percentual para comparar: a única saída
        # honesta é aceitar o candidato que *cria* evidência e recusar o que também zera.
        decisao = "ACEITO" if depois > 0 else "REJEITADO"
    elif depois >= antes * (1 + ganho_minimo):
        decisao = "ACEITO"
    elif not move_score and abs(depois - antes) < 1e-12:
        decisao = "SEM EFEITO NA MÉTRICA"
    else:
        decisao = "REJEITADO"
    ganho = (depois - antes) / antes if antes else None
    return {"decisao": decisao, "ganho": None if ganho is None else round(float(ganho), 4)}


def score_evidencia(evidencias: list[dict]) -> dict:
    """Métrica do loop: p-valor baixo + efeito grande + estável no tempo.

    ``score = média de (1 - p) × |r| × estabilidade`` sobre as evidências válidas.
    """
    validas = [item for item in evidencias if item.get("r") is not None and item.get("p") is not None]
    if not validas:
        return {"score": 0.0, "evidencias": 0, "detalhes": []}

    detalhes = []
    for item in validas:
        estabilidade = float(item.get("estabilidade", 1.0))
        contribuicao = (1 - float(item["p"])) * abs(float(item["r"])) * estabilidade
        detalhes.append({
            "nome": item["nome"],
            "r": item["r"],
            "p": item["p"],
            "n": item["n"],
            "estabilidade": estabilidade,
            "contribuicao": round(contribuicao, 4),
        })
    score = float(np.mean([item["contribuicao"] for item in detalhes]))
    return {"score": round(score, 4), "evidencias": len(detalhes), "detalhes": detalhes}


def leitura(r: float | None, p: float | None) -> str:
    """Frase curta para o relatório, sem exagerar no que o número diz."""
    if r is None or p is None:
        return "sem amostra suficiente"
    if p >= 0.05:
        return f"sem evidência (p={p:.3f}, n insuficiente ou relação fraca)"
    direcao = "sobem juntos" if r > 0 else "andam em direções opostas"
    forca = "forte" if abs(r) >= 0.6 else ("moderada" if abs(r) >= 0.3 else "fraca")
    return f"{direcao}, associação {forca} (r={r:.3f}, p={p:.3f})"


def limitacoes_projeto(cobertura: dict, *, meses_preco: int, municipios_preco: int) -> list[str]:
    """Limitações que acompanham o artefato — sem elas o número vira promessa.

    Cada item é derivado da própria cobertura: se a cobertura mudar, o texto muda junto.
    """
    itens = [
        (
            f"Preço cobre {municipios_preco} municípios em {meses_preco} meses, não o país inteiro: "
            "os arquivos mensais da ANP são uma amostra rotativa de municípios, então "
            "média nacional aqui não é censo."
        ),
        (
            "A fiscalização é acumulada (1998 em diante) e o denominador de postos ativos é de hoje: "
            "o IPF compara estoque antigo com estoque atual e favorece UFs com histórico longo."
        ),
        (
            "O campo statusSIGAF da API de revendedores vem vazio em 100% dos registros: "
            "não há como separar posto ativo de irregular por ali."
        ),
        (
            "As multas do dados.gov.br não têm arquivo baixável (página só renderiza em JavaScript "
            "e a API responde 401): valor de multa não entra em nenhum cálculo."
        ),
        (
            "Correlação não é causa. Fiscalização acha o que procura: uma UF com mais ações pode ser "
            "a que mais fiscaliza, não a que mais erra."
        ),
        (
            "Interdição e preço foram comparados por diferença em diferenças contra os outros "
            "municípios da mesma UF; município com uma única revenda não tem controle próprio."
        ),
        (
            "A série de preço publicada é mensal, então o IPF é cruzado com a dispersão do mês — "
            "não com variação semanal, que não existe nesta base."
        ),
        (
            "Zonas cegas usam ações por posto ativo; fiscalização por km² não entra porque o "
            "projeto não carrega área de UF."
        ),
        (
            "O peso de 'taxa de denúncias' do score de alvo virou histórico de interdição do "
            "município: não há base pública de denúncias por município."
        ),
    ]
    if cobertura.get("interdicoes_revenda"):
        itens.append(
            "Auto de interdição é ato administrativo, não condenação definitiva: o autuado tem "
            "direito ao contraditório e à ampla defesa, e só o julgamento definitivo do processo "
            "comprova a infração — pode ser revertido em recurso."
        )
    return itens


@dataclass(frozen=True)
class Parametros:
    """Botões que o loop noturno gira. O padrão é o que está publicado hoje."""

    desde: str = "2023-01"
    janela_ipf: int = JANELA_IPF_MESES
    limite_anomalia: float = LIMITE_ANOMALIA
    minimo_postos: int = MINIMO_POSTOS_ANOMALIA
    atrasos: tuple[int, ...] = (1, 2)
    pesos: dict[str, float] | None = None
    metodo: str = "pearson"

    def como_dicionario(self) -> dict:
        """Parâmetros em dicionário — é o formato que vai ao ``baseline.json`` e ao log."""
        return {
            "desde": self.desde,
            "janela_ipf": self.janela_ipf,
            "limite_anomalia": self.limite_anomalia,
            "minimo_postos": self.minimo_postos,
            "atrasos": list(self.atrasos),
            "pesos": dict(self.pesos or config.PESOS_SCORE_FISCAL),
            "metodo": self.metodo,
        }


def avaliar(
    acoes: pd.DataFrame,
    serie_uf: pd.DataFrame,
    municipios: pd.DataFrame,
    postos: dict[str, int],
    parametros: Parametros | None = None,
) -> dict:
    """Roda C1 a C7 com um conjunto de parâmetros e devolve tudo que a publicação usa.

    Separado da montagem do JSON porque o loop noturno precisa medir o score muitas
    vezes sobre os mesmos quadros: aqui ele troca parâmetros sem reler 645 mil linhas.
    """
    parametros = parametros or Parametros()
    pesos = dict(parametros.pesos or config.PESOS_SCORE_FISCAL)

    serie_mes = fiscalizacao.por_uf_mes(acoes)
    fisc_municipio = fiscalizacao.por_municipio(acoes, periodo_minimo=parametros.desde)

    # ---- C1, C2 e C5
    ipf = ipf_por_uf(acoes, postos, meses=parametros.janela_ipf)
    dispersao = dispersao_por_uf(serie_uf, from_periodo=parametros.desde)
    zonas = zonas_cegas(ipf, dispersao)
    correlacao_ipf = [
        {**correlacionar(zonas["ipf"], zonas["dispersao_cv"], metodo=parametros.metodo),
         "nome": "ipf_x_dispersao_uf"},
        {**correlacionar(zonas["ipf"], zonas["dispersao_cv"], metodo="spearman"),
         "nome": "ipf_x_dispersao_uf_spearman"},
        {**correlacionar(zonas["taxa_interdicao"], zonas["preco_medio"], metodo=parametros.metodo),
         "nome": "interdicao_x_preco_uf"},
        {**correlacionar(zonas["taxa_interdicao"], zonas["preco_medio"], metodo="spearman"),
         "nome": "interdicao_x_preco_uf_spearman"},
    ]

    # ---- C4
    c4 = correlacao_fiscalizacao_preco(
        serie_mes, serie_uf, from_periodo=parametros.desde, atrasos=parametros.atrasos,
        metodo=parametros.metodo,
    )
    estabilidade = estabilidade_temporal(c4["painel"], coluna_x="acoes", coluna_y="preco_medio")
    evidencias = [
        {**item, "estabilidade": estabilidade} for item in c4["evidencias"]
    ] + [
        {**item, "estabilidade": estabilidade_amostral(
            zonas,
            coluna_x="ipf" if "ipf" in item["nome"] else "taxa_interdicao",
            coluna_y="dispersao_cv" if "ipf" in item["nome"] else "preco_medio",
        )}
        for item in correlacao_ipf
    ]

    # ---- C3 e C7
    anomalias = anomalias_minimo_colado(
        municipios, limite=parametros.limite_anomalia, minimo_postos=parametros.minimo_postos
    )
    alvos = score_fiscal(municipios, fisc_municipio, pesos=pesos)

    # ---- C6
    interdicao = interdição_x_preco(acoes, municipios, periodo_minimo=parametros.desde)

    return {
        "parametros": parametros.como_dicionario(),
        "score": score_evidencia(evidencias),
        "evidencias": evidencias,
        "painel_c4": c4["painel"],
        "ipf": ipf,
        "dispersao": dispersao,
        "zonas": zonas,
        "anomalias": anomalias,
        "alvos": alvos,
        "fisc_municipio": fisc_municipio,
        "interdicao": interdicao,
        "serie_mes": serie_mes,
    }


def montar_inteligencia(
    *,
    ufs: pd.DataFrame,
    evidencias: list[dict],
    anomalias: pd.DataFrame,
    alvos: pd.DataFrame,
    interditados: pd.DataFrame,
    interdição: dict,
    cobertura: dict,
    periodos: dict,
    score: dict,
    pesos: dict[str, float],
    parametros: dict | None = None,
) -> dict:
    """Objeto publicado em ``site/data/inteligencia.json`` (contrato em ARQUITETURA.md)."""
    def registros(quadro: pd.DataFrame, colunas: list[str], limite: int | None = None) -> list[dict]:
        """Recorta colunas (e linhas) de um quadro para virar lista de dicionários no JSON.

        Passa por ``to_json`` para os tipos do pandas virarem tipos nativos — sem isso o
        ``json.dumps`` do artefato quebraria com ``Timestamp`` e ``NaN``.
        """
        recorte = quadro.head(limite) if limite else quadro
        recorte = recorte[[coluna for coluna in colunas if coluna in recorte.columns]]
        return json.loads(recorte.to_json(orient="records", force_ascii=False))

    return {
        "gerado_em": datetime.now(config.FUSO).isoformat(timespec="seconds"),
        "periodos": periodos,
        "cobertura": cobertura,
        "pesos_score_fiscal": pesos,
        "parametros": parametros or {},
        "score_evidencia": score,
        "limitacoes": limitacoes_projeto(
            cobertura,
            meses_preco=int(cobertura.get("meses_de_preco") or 0),
            municipios_preco=int(cobertura.get("municipios_com_preco") or 0),
        ),
        "ufs": registros(
            ufs,
            ["uf", "postos", "acoes_12m", "acoes_total", "infracoes_12m", "interdicoes_12m",
             "ipf", "ipf_acumulado", "taxa_interdicao", "dispersao_cv", "preco_medio",
             "periodo_inicio", "periodo_fim", "zona_cega"],
        ),
        "correlacoes": [
            {**item, "leitura": leitura(item.get("r"), item.get("p"))} for item in evidencias
        ],
        "anomalias": registros(
            anomalias,
            ["uf", "municipio", "meses", "meses_colados", "taxa_colada", "postos", "folga_pct",
             "preco_minimo", "preco_medio", "preco_maximo", "amplitude", "ultimo_periodo"],
            LIMITE_ANOMALIAS,
        ),
        "alvos": registros(
            alvos,
            ["uf", "municipio", "score", "meses", "postos", "preco_medio", "desvio_relativo",
             "variacao_uf", "acoes_municipio", "interdicoes_municipio", "comp_dispersao",
             "comp_fiscalizacao", "comp_interdicao", "comp_variacao"],
        ),
        "interditos": registros(
            interditados, ["uf", "municipio", "cnpj", "interdicoes", "primeira", "ultima"],
            LIMITE_INTERDITOS,
        ),
        "interdicao_preco": interdição,
    }
