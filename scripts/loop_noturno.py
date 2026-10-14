"""Loop noturno da fase 2: girar um botão, medir o score de evidência e decidir.

    .\\preparar.ps1                                   (uma vez)
    python scripts/loop_noturno.py                     (até 12 ciclos, grava o log)
    python scripts/loop_noturno.py --ciclos 4          (rodada curta)

O verificador é o próprio score de evidência (p-valor × efeito × estabilidade). Cada
ciclo muda **um** parâmetro, mede de novo e aceita só se o score subir pelo menos 5%.
O log e o baseline ficam em ``log_noturno.md`` e ``baseline.json``; a hipótese
rejeitada três vezes é abandonada (senão é overfitting com outro nome).

Os quadros são lidos uma vez e reaproveitados: o custo do loop é o das correlações,
não o de ler 645 mil linhas de planilha por ciclo.

Convenção de commit dos ciclos automáticos: prefixo ``[loop]`` (os commits desta
primeira rodada saíram como ``feat(fase2)`` para não fugir do padrão do projeto).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console do Windows é cp1252

from combustivelbr import analise, config, fiscalizacao, historico, revendedores  # noqa: E402

sys.path.insert(0, str(RAIZ / "scripts"))
from inteligencia import carregar_acoes, carregar_precos  # noqa: E402

# Ganho mínimo para aceitar um ciclo (5%, do prompt da fase 2).
GANHO_MINIMO = 0.05
# Rejeições na mesma hipótese antes de abandonar.
REJEICOES_PARA_ABANDONAR = 3
# Quantas correlações com p < 0.05 o critério de parada pede.
CORRELACOES_MINIMAS = 4
# Ciclos mínimos antes de aceitar que o score estabilizou (senão o loop para na primeira
# trinca de variações pequenas e deixa metade do catálogo sem teste).
MINIMO_CICLOS_ANTES_DE_PARAR = 6

ARQUIVO_BASELINE = RAIZ / "baseline.json"
ARQUIVO_LOG = RAIZ / "log_noturno.md"


def hipoteses() -> list[tuple[str, str, dict, bool]]:
    """Catálogo de variações pequenas, uma por ciclo.

    Cada item é (hipótese, descrição, mudança, move_score). ``move_score=False`` marca os
    botões que **não** mexem na métrica de evidência (pesos do score fiscal, limiar de
    anomalia, porte mínimo): eles mudam a lista de alvos e anomalias publicada, e o loop
    registra isso como "sem efeito na métrica" em vez de fingir que rejeitou a hipótese.
    A hipótese é a família: rejeitar três variações da mesma família abandona o assunto.
    """
    itens: list[tuple[str, str, dict, bool]] = []

    for desde in ("2024-01", "2025-01", "2022-07"):
        itens.append(("janela de correlação", f"começar a correlação em {desde}", {"desde": desde}, True))
    for meses in (24, 36, 6):
        itens.append(("janela do IPF", f"contar ações dos últimos {meses} meses", {"janela_ipf": meses}, True))
    for limite in (0.01, 0.03, 0.05, 0.015):
        itens.append(("limiar de anomalia", f"mínimo colado passa a ser folga < {limite:.1%}",
                      {"limite_anomalia": limite}, False))
    for postos in (5, 8, 10):
        itens.append(("porte mínimo do município", f"exigir {postos} postos por município",
                      {"minimo_postos": postos}, False))
    for atrasos in ((1, 2, 3), (2, 3), (1,), (3,), (1, 2, 3, 6)):
        itens.append(("memória da fiscalização", f"lags {atrasos} entre ação e preço",
                      {"atrasos": atrasos}, True))
    itens.append(("método da correlação", "usar Spearman na evidência principal", {"metodo": "spearman"}, True))

    pesos = {
        "dispersão manda": {"dispersao": 0.5, "fiscalizacao": 0.2, "interdicao": 0.15, "variacao": 0.15},
        "fiscalização manda": {"dispersao": 0.2, "fiscalizacao": 0.5, "interdicao": 0.15, "variacao": 0.15},
        "interdição manda": {"dispersao": 0.2, "fiscalizacao": 0.2, "interdicao": 0.45, "variacao": 0.15},
        "variação manda": {"dispersao": 0.2, "fiscalizacao": 0.2, "interdicao": 0.15, "variacao": 0.45},
        "tudo igual": {"dispersao": 0.25, "fiscalizacao": 0.25, "interdicao": 0.25, "variacao": 0.25},
    }
    for nome, peso in pesos.items():
        itens.append(("pesos do score fiscal", f"pesos: {nome}", {"pesos": peso}, False))
    return itens


def intercalar(itens: list[tuple[str, str, dict, bool]]) -> list[tuple[str, str, dict, bool]]:
    """Round-robin por família: família ruim não consome a noite inteira de uma vez."""
    por_familia: dict[str, list] = {}
    for item in itens:
        por_familia.setdefault(item[0], []).append(item)

    fila: list[tuple[str, str, dict, bool]] = []
    while any(por_familia.values()):
        for familia in list(por_familia):
            if por_familia[familia]:
                fila.append(por_familia[familia].pop(0))
    return fila


def carregar_baseline(caminho: Path) -> dict:
    """Estado da rodada anterior (parâmetros vencedores e ciclos já testados).

    Sem arquivo, começa do conjunto padrão: a primeira noite não tem histórico para comparar.
    """
    if caminho.exists():
        return json.loads(caminho.read_text(encoding="utf-8"))
    return {"parametros": analise.Parametros().como_dicionario(), "score": 0.0, "ciclos": []}


def medir(quadros: dict, parametros: analise.Parametros) -> dict:
    """Roda o verificador: devolve score, evidências e quantas passam de p < 0.05."""
    resultado = analise.avaliar(
        quadros["acoes"], quadros["serie_uf"], quadros["municipios"], quadros["postos"], parametros
    )
    fortes = [item for item in resultado["evidencias"] if item.get("p") is not None and item["p"] < 0.05]
    return {
        "score": resultado["score"]["score"],
        "evidencias": resultado["score"]["evidencias"],
        "fortes": len(fortes),
        "resultado": resultado,
    }


def linha_do_ciclo(numero: int, hipotese: str, descricao: str, antes: float, depois: float,
                   decisao: str, observacao: str) -> str:
    """Uma linha do diário: hipótese, score antes e depois, decisão e o porquê."""
    return (
        f"[{datetime.now(config.FUSO).strftime('%H:%M')}] Ciclo {numero} — Hipótese: {hipotese} ({descricao})\n"
        f"        Métrica antes: {antes:.4f} | Métrica depois: {depois:.4f} | Decisão: {decisao}\n"
        f"        Observação: {observacao}\n"
    )


def publicar(quadros: dict, parametros: analise.Parametros) -> dict:
    """Regrava ``site/data/inteligencia.json`` com os parâmetros vencedores."""
    resultado = analise.avaliar(
        quadros["acoes"], quadros["serie_uf"], quadros["municipios"], quadros["postos"], parametros
    )
    zonas = resultado["zonas"]
    ufs = zonas  # já traz as colunas do IPF; merge de novo criaria colunas ``_x``/``_y``
    serie_uf = quadros["serie_uf"]
    acoes = quadros["acoes"]
    municipios = quadros["municipios"]
    cobertura = {
        "acoes_normalizadas": int(len(acoes)),
        "acoes_revenda": int(acoes["revenda"].sum()),
        "interdicoes_revenda": int((acoes["interdicao"] & acoes["revenda"]).sum()),
        "postos_ativos_api": int(sum(quadros["postos"].values())),
        "ufs": int(len(quadros["postos"])),
        "municipios_com_preco": int(municipios["municipio"].nunique()),
        "meses_de_preco": int(serie_uf["periodo"].nunique()),
        "municipios_com_fiscalizacao": int(resultado["fisc_municipio"]["municipio"].nunique()),
    }
    payload = analise.montar_inteligencia(
        ufs=ufs,
        evidencias=resultado["evidencias"],
        anomalias=resultado["anomalias"],
        alvos=resultado["alvos"],
        interditados=fiscalizacao.interditos(acoes),
        interdição=resultado["interdicao"],
        cobertura=cobertura,
        periodos={
            "fiscalizacao": f"{acoes['periodo'].min()} a {acoes['periodo'].max()}",
            "precos_uf": f"{serie_uf['periodo'].min()} a {serie_uf['periodo'].max()}",
            "correlacao_desde": parametros.desde,
            "janela_ipf_meses": parametros.janela_ipf,
        },
        score=resultado["score"],
        pesos=parametros.pesos or config.PESOS_SCORE_FISCAL,
        parametros=resultado["parametros"],
    )
    payload["loop"] = {
        "baseline": str(ARQUIVO_BASELINE.name),
        "log": str(ARQUIVO_LOG.name),
        "score_no_loop": resultado["score"]["score"],
    }
    config.ARQUIVO_INTELIGENCIA.parent.mkdir(parents=True, exist_ok=True)
    config.ARQUIVO_INTELIGENCIA.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )
    return payload


def main() -> int:
    """Varre os parâmetros do loop, grava o diário e atualiza o baseline."""
    parser = argparse.ArgumentParser(description="Loop noturno de evidência (fase 2)")
    parser.add_argument("--ciclos", type=int, default=12, help="máximo de ciclos (padrão 12)")
    argumentos = parser.parse_args()

    quadros = {
        "acoes": carregar_acoes(),
        "postos": revendedores.postos_por_uf(revendedores.normalizar(revendedores.ler_ufs())),
    }
    serie_uf, municipios = carregar_precos()
    quadros["serie_uf"] = serie_uf
    quadros["municipios"] = municipios
    if not quadros["postos"]:
        raise SystemExit("sem dados de revendedores em data/raw (rode scripts/inteligencia.py --baixar)")

    baseline = carregar_baseline(ARQUIVO_BASELINE)
    melhor = analise.Parametros(**{**baseline["parametros"], "atrasos": tuple(baseline["parametros"]["atrasos"])})
    inicial = medir(quadros, melhor)
    print(f"baseline: score {inicial['score']:.4f} em {inicial['evidencias']} correlações "
          f"({inicial['fortes']} com p < 0.05)")

    ciclos: list[dict] = list(baseline.get("ciclos", []))
    abandonadas: dict[str, int] = dict(baseline.get("rejeicoes_por_hipotese", {}))
    linhas = [
        "# Loop noturno — fase 2 (fiscalização × preço)",
        "",
        f"Rodada de {datetime.now(config.FUSO).strftime('%d/%m/%Y %H:%M')}. "
        f"Ganho mínimo para aceitar: {GANHO_MINIMO:.0%}; hipótese abandonada após "
        f"{REJEICOES_PARA_ABANDONAR} rejeições.",
        "",
        f"Ponto de partida: score **{inicial['score']:.4f}**, {inicial['evidencias']} correlações, "
        f"{inicial['fortes']} com p < 0.05.",
        "",
    ]

    fila = intercalar(hipoteses())
    numero = len(ciclos)
    estavel_em = 0
    parada = ""
    abandonadas_anunciadas: set[str] = set()
    while numero < argumentos.ciclos and fila:
        hipotese, descricao, mudanca, move_score = fila.pop(0)
        if abandonadas.get(hipotese, 0) >= REJEICOES_PARA_ABANDONAR:
            if hipotese not in abandonadas_anunciadas:
                abandonadas_anunciadas.add(hipotese)
                linhas.append(
                    f"- hipótese abandonada depois de {REJEICOES_PARA_ABANDONAR} rejeições: **{hipotese}**\n"
                )
            continue

        numero += 1
        candidato = replace(melhor, **mudanca)
        tentativa = medir(quadros, candidato)
        antes, depois = inicial["score"], tentativa["score"]  # referência é o melhor até agora
        veredito = analise.decidir_ciclo(antes, depois, move_score=move_score, ganho_minimo=GANHO_MINIMO)
        ganho, decisao = veredito["ganho"], veredito["decisao"]
        aceito = decisao == "ACEITO"
        cego = decisao == "SEM EFEITO NA MÉTRICA"

        if aceito:
            melhor = candidato

        if decisao == "ACEITO":
            ganho_texto = f"ganho de {ganho:.1%} sobre o melhor até agora"
        elif cego:
            ganho_texto = ("o score de evidência mede correlação, e este parâmetro só muda a "
                           "lista de alvos e anomalias publicada — não conta como rejeição")
        elif depois < antes:
            ganho_texto = f"piora de {abs(ganho):.1%} sobre o melhor até agora"
        else:
            ganho_texto = f"melhora de {ganho:.1%}, abaixo dos {GANHO_MINIMO:.0%} exigidos"

        observacao = (
            f"{tentativa['evidencias']} correlações, {tentativa['fortes']} com p < 0.05; {ganho_texto}"
        )
        if decisao == "ACEITO":
            inicial = tentativa  # o novo ponto de comparação passa a ser o aceito
        if decisao == "REJEITADO":
            abandonadas[hipotese] = abandonadas.get(hipotese, 0) + 1

        ciclos.append({
            "ciclo": numero,
            "hipotese": hipotese,
            "descricao": descricao,
            "mudanca": {chave: (list(valor) if isinstance(valor, tuple) else valor)
                        for chave, valor in mudanca.items()},
            "score_antes": round(antes, 4),
            "score_depois": round(depois, 4),
            "decisao": decisao,
            "observacao": observacao,
        })
        linhas.append(linha_do_ciclo(numero, hipotese, descricao, antes, depois, decisao, observacao))
        print(f"ciclo {numero:>2} {hipotese:<26} antes={antes:.4f} depois={depois:.4f} {decisao}")

        # parada: score estabilizado (duas variações pequenas seguidas) e já há evidência suficiente
        estavel_em = estavel_em + 1 if abs(ganho) < GANHO_MINIMO else 0
        if (estavel_em >= 2 and numero >= MINIMO_CICLOS_ANTES_DE_PARAR
                and tentativa["fortes"] >= CORRELACOES_MINIMAS):
            parada = ("score estabilizado (duas variações abaixo de 5%) com evidência suficiente")
            break

    if not parada:
        parada = ("limite de ciclos atingido" if numero >= argumentos.ciclos
                  else "hipóteses esgotadas")

    payload = publicar(quadros, melhor)
    estado = {
        "atualizado_em": datetime.now(config.FUSO).isoformat(timespec="seconds"),
        "score": payload["score_evidencia"]["score"],
        "parametros": melhor.como_dicionario(),
        "ciclos": ciclos,
        "rejeicoes_por_hipotese": abandonadas,
        "parada": parada,
    }
    ARQUIVO_BASELINE.write_text(
        json.dumps(estado, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )

    linhas += [
        "",
        f"**Parada**: {parada}.",
        "",
        f"**Parâmetros vencedores**: `{json.dumps(melhor.como_dicionario(), ensure_ascii=False)}`",
        "",
        f"Score publicado: **{payload['score_evidencia']['score']}** "
        f"({payload['score_evidencia']['evidencias']} correlações, "
        f"{sum(1 for item in payload['correlacoes'] if item['p'] is not None and item['p'] < 0.05)} "
        "com p < 0.05).",
        "",
    ]
    ARQUIVO_LOG.write_text("\n".join(linhas), encoding="utf-8", newline="\n")

    print(f"parada: {parada}")
    print(f"parâmetros vencedores: {melhor.como_dicionario()}")
    print(f"gravado: {ARQUIVO_LOG.name}, {ARQUIVO_BASELINE.name}, {config.ARQUIVO_INTELIGENCIA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
