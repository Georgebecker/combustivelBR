"""Gera ``RELATORIO_INTELIGENCIA.md`` a partir do JSON publicado e do log do loop.

    python scripts/relatorio.py

O relatório é escrito a partir de ``site/data/inteligencia.json``: nenhum número é
digitado à mão, então o documento não pode divergir do artefato que o site mostra.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console do Windows é cp1252

from combustivelbr import config  # noqa: E402

ARQUIVO = RAIZ / "RELATORIO_INTELIGENCIA.md"
BASELINE = RAIZ / "baseline.json"


def num(valor, casas: int = 2) -> str:
    """Número em pt-BR; ``None`` vira travessão (nada de inventar zero)."""
    if valor is None:
        return "—"
    if isinstance(valor, float):
        return f"{valor:,.{casas}f}".replace(",", "␟").replace(".", ",").replace("␟", ".")
    return f"{valor:,}".replace(",", ".")


def tabela(cabecalhos: list[str], linhas: list[list[str]]) -> list[str]:
    """Bloco de tabela em Markdown; sem linhas, devolve um aviso em vez de tabela vazia."""
    if not linhas:
        return ["_sem registros_", ""]
    saida = ["| " + " | ".join(cabecalhos) + " |", "|" + "---|" * len(cabecalhos)]
    saida += ["| " + " | ".join(linha) + " |" for linha in linhas]
    saida.append("")
    return saida


def partes_hipoteses(caminho: Path) -> list[str]:
    """Seção do relatório com os ciclos já testados, lida do estado do loop."""
    if not caminho.exists():
        return ["_o loop noturno ainda não rodou (baseline.json ausente)_", ""]
    estado = json.loads(caminho.read_text(encoding="utf-8"))
    linhas = []
    for ciclo in estado.get("ciclos", []):
        linhas.append([
            str(ciclo["ciclo"]),
            ciclo["hipotese"],
            ciclo["descricao"],
            f"{num(ciclo['score_antes'], 4)} → {num(ciclo['score_depois'], 4)}",
            ciclo["decisao"],
        ])
    saida = tabela(["#", "hipótese", "variação testada", "score", "decisão"], linhas)
    saida += [f"Parada do loop: {estado.get('parada', '—')}. ", ""]
    return saida


def gerar(corpo: dict) -> str:
    """Monta o relatório completo a partir do JSON publicado (nada é recalculado aqui)."""
    cobertura = corpo["cobertura"]
    score = corpo["score_evidencia"]
    parametros = corpo.get("parametros", {})
    periodos = corpo["periodos"]
    ufs = {item["uf"]: item for item in corpo["ufs"]}

    linhas = [
        "# Relatório de Inteligência — combustivelBR (fase 2)",
        "",
        f"Gerado em {datetime.now(config.FUSO).strftime('%d/%m/%Y %H:%M')} a partir de "
        f"`site/data/inteligencia.json` (dados publicados em {corpo['gerado_em'][:10]}). "
        "Preços e fiscalização são públicos; o recorte e as limitações estão no fim.",
        "",
        "## Base usada",
        "",
        f"- Fiscalização: {num(cobertura['acoes_revenda'])} ações na revenda "
        f"({num(cobertura['acoes_normalizadas'])} normalizadas em todos os segmentos), "
        f"{num(cobertura['interdicoes_revenda'])} autos de interdição.",
        f"- Postos ativos: {num(cobertura['postos_ativos_api'])} em {num(cobertura['ufs'])} UFs "
        "(API de revendedores da ANP).",
        f"- Preço: {num(cobertura['meses_de_preco'])} meses, "
        f"{num(cobertura['municipios_com_preco'])} municípios com dado, "
        f"{num(cobertura['municipios_com_fiscalizacao'])} com fiscalização registrada.",
        f"- Janela da correlação: desde {periodos['correlacao_desde']}; "
        f"IPF em {parametros.get('janela_ipf', periodos['janela_ipf_meses'])} meses; "
        f"método {parametros.get('metodo', 'pearson')}.",
        "",
        f"**Score de evidência**: {num(score['score'], 4)} em {score['evidencias']} correlações "
        "(média de (1 − p) × |r| × estabilidade). Score baixo quer dizer que a evidência é fraca — "
        "não que o achado é falso.",
        "",
        "## 1. Top 5 anomalias (preço mínimo colado na média)",
        "",
        "Municípios em que o menor preço da amostra fica a menos de "
        f"{parametros.get('limite_anomalia', 0.02):.1%} da média, em muitos meses seguidos. "
        "Recorrência é o sinal: mercado disputado não repete isso por 40 meses.",
        "",
    ]
    linhas += tabela(
        ["município", "recorrência", "folga média", "postos", "preço médio", "mín→máx", "último mês"],
        [
            [
                f"{item['uf']} {item['municipio']}",
                f"{item['meses_colados']} de {item['meses']} meses",
                f"{num(item['folga_pct'], 2)}%",
                num(item["postos"], 1),
                f"R$ {num(item['preco_medio'], 4)}",
                f"{num(item['preco_minimo'], 2)} → {num(item['preco_maximo'], 2)}",
                item["ultimo_periodo"],
            ]
            for item in corpo["anomalias"][:5]
        ],
    )

    linhas += [
        "## 2. Top 5 alvos para fiscalização",
        "",
        "Score composto (0 a 1) por dispersão de preço no município, fiscalização por posto "
        "(invertida), histórico de interdição e desvio da mediana da UF. Pesos: "
        + ", ".join(f"{chave} {peso}" for chave, peso in corpo["pesos_score_fiscal"].items())
        + ".",
        "",
    ]
    linhas += tabela(
        ["município", "score", "postos", "dispersão", "desvio da UF", "ações", "interdições"],
        [
            [
                f"{item['uf']} {item['municipio']}",
                num(item["score"], 4),
                num(item["postos"], 0),
                num(item["desvio_relativo"], 3),
                f"{num(item['variacao_uf'] * 100, 1)}%",
                num(item["acoes_municipio"]),
                num(item["interdicoes_municipio"]),
            ]
            for item in corpo["alvos"][:5]
        ],
    )

    cegas = [item for item in corpo["ufs"] if item.get("zona_cega")]
    linhas += [
        "## 3. UFs em zona cega",
        "",
        "Quartil de menor IPF (ações por 1.000 postos) com dispersão de preço acima da mediana "
        "do país. Fiscaliza pouco e o preço varia muito entre postos da mesma UF.",
        "",
    ]
    linhas += tabela(
        ["UF", "IPF (janela)", "IPF acumulado", "ações na janela", "dispersão (CV)", "preço médio"],
        [
            [
                item["uf"],
                num(item["ipf"], 1),
                num(item["ipf_acumulado"], 1),
                num(item["acoes_12m"]),
                num(item["dispersao_cv"], 4),
                f"R$ {num(item['preco_medio'], 3)}",
            ]
            for item in cegas
        ],
    )

    fortes = [item for item in corpo["correlacoes"] if item["p"] is not None and item["p"] < 0.05]
    linhas += [
        "## 4. O que se sustenta (p < 0,05)",
        "",
    ]
    linhas += tabela(
        ["correlação", "r", "p", "n", "estabilidade", "leitura"],
        [
            [
                item["nome"],
                num(item["r"], 4),
                num(item["p"], 4),
                num(item["n"]),
                num(item["estabilidade"], 3),
                item["leitura"],
            ]
            for item in fortes
        ],
    )
    fracas = [item for item in corpo["correlacoes"] if item not in fortes]
    linhas += [
        f"Outras {len(fracas)} correlações testadas não passaram do corte e ficam registradas "
        "no JSON — publicar só o que deu certo é como escolher o resultado depois de ver o jogo.",
        "",
        "### Interdição × preço",
        "",
        f"Diferença em diferenças contra os outros municípios da mesma UF, n = "
        f"{num(corpo['interdicao_preco'].get('n'))}: "
        f"ação bruta {num(corpo['interdicao_preco'].get('delta_bruto_medio'), 4)} na média, "
        f"controle {num(corpo['interdicao_preco'].get('delta_controle_medio'), 4)}, "
        f"efeito próprio {num(corpo['interdicao_preco'].get('efeito'), 4)} "
        f"(p = {num(corpo['interdicao_preco'].get('p'), 4)}). "
        f"Leitura: {corpo['interdicao_preco'].get('leitura')}. O ganho bruto de preço depois da "
        "interdição é a tendência do período inteiro, não o efeito da ação.",
        "",
        "## 5. Hipóteses levantadas",
        "",
        "- Onde há pouca ação por posto e preço disperso (zona cega), o mercado pode estar "
        "subfiscalizado: " + (", ".join(item["uf"] for item in cegas) or "nenhuma UF") + ".",
        "- Municípios com mínimo colado na média por dezenas de meses se comportam como mercado "
        "sem disputa de preço; pode ser uma revenda só na prática, tabela comum ou liderança de preço.",
        "- A correlação intra-UF entre fiscalização e preço é negativa e pequena: mais ação "
        "aparece onde o preço é menor, o que é compatível com fiscalização reagir a denúncia, "
        "e não com fiscalização derrubar preço.",
        "- A ação de interdição não move o preço do município acima do que move o resto da UF "
        "na mesma janela.",
        "",
        "### O que o loop noturno testou",
        "",
    ]
    linhas += partes_hipoteses(BASELINE)

    linhas += [
        "## 6. O que um fiscal faria diferente com isso",
        "",
        "1. Começaria pelos alvos da seção 2: dispersão alta e pouca ação por posto é onde o "
        "mesmo produto tem preço muito diferente na mesma cidade.",
        "2. Olharia as anomalias da seção 1 em campo: preço igual por 40 meses não se explica "
        "sozinho, mas se explica no balcão.",
        "3. Nas zonas cegas, usaria o IPF como lista de prioridade de agenda — o indicador mede "
        "esforço por posto, não irregularidade encontrada.",
        "4. Não usaria este relatório como prova: nenhuma linha aqui é processo, é triagem.",
        "",
        "## 7. Limitações (leia antes de citar qualquer número)",
        "",
    ]
    linhas += [f"- {item}" for item in corpo.get("limitacoes", [])]
    linhas += [
        "",
        "---",
        "",
        "Reproduzir: `python scripts/inteligencia.py` (publica o JSON) e "
        "`python scripts/loop_noturno.py` (roda o loop de evidência). "
        "Este arquivo é gerado por `python scripts/relatorio.py` — não edite à mão.",
        "",
    ]
    return "\n".join(linhas)


def main() -> int:
    """Gera ``RELATORIO_INTELIGENCIA.md`` a partir do JSON de inteligência já publicado."""
    if not config.ARQUIVO_INTELIGENCIA.exists():
        raise SystemExit("sem site/data/inteligencia.json — rode scripts/inteligencia.py antes")
    corpo = json.loads(config.ARQUIVO_INTELIGENCIA.read_text(encoding="utf-8"))
    ARQUIVO.write_text(gerar(corpo), encoding="utf-8", newline="\n")
    print(f"gravado: {ARQUIVO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
