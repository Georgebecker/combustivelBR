"""Roda a análise da fase 2 e publica o JSON de inteligência.

    .\\preparar.ps1                              (uma vez)
    python scripts/inteligencia.py               (usa o que já está em data/raw)
    python scripts/inteligencia.py --baixar      (busca fiscalização e série mensal antes)

Lê as fontes tratadas, calcula C1 a C7, mede o score de evidência e grava
``site/data/inteligencia.json`` — o mesmo arquivo que a aba Inteligência do site lê.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console do Windows é cp1252

import pandas as pd  # noqa: E402

from combustivelbr import analise, config, fiscalizacao, historico, revendedores, transformacao  # noqa: E402


def baixar_fontes() -> None:
    """Busca o que pode não estar em data/raw (rede)."""
    for nome, endereco in config.FISCALIZACAO_URLS:
        destino = config.DATA_RAW / f"{config.carimbo()}-{nome}.xlsx"
        if destino.exists():
            continue
        import requests

        print(f"baixando {nome} ...")
        resposta = requests.get(endereco, timeout=300, headers={"User-Agent": config.USER_AGENT})
        resposta.raise_for_status()
        destino.write_bytes(resposta.content)

    if not historico.arquivos_mensais():
        print("baixando a série mensal de preços ...")
        historico.baixar_mensais()

    if not revendedores.ler(config.UFS[0]):
        print("consultando a API de revendedores (uma UF por vez) ...")
        for uf in config.UFS:
            if not revendedores.ler(uf):
                revendedores.baixar(uf)


def carregar_acoes() -> pd.DataFrame:
    """Planilhas de fiscalização já baixadas, num só quadro (aborta se não houver nenhuma)."""
    caminhos = fiscalizacao.arquivos_baixados()
    if not caminhos:
        raise SystemExit("sem planilha de fiscalização em data/raw (rode com --baixar)")
    return fiscalizacao.ler_planilhas(caminhos)


def carregar_precos() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Série UF × mês e município × mês (reaproveita o que já foi tratado)."""
    arquivos = historico.arquivos_mensais()
    if not arquivos:
        raise SystemExit("sem arquivos mensais de preço em data/raw (rode com --baixar)")

    if config.ARQUIVO_PRECOS_UF_MES.exists():
        serie_uf = pd.read_csv(config.ARQUIVO_PRECOS_UF_MES, dtype={"periodo": str})
    else:
        serie_uf = historico.serie_uf_mes()
        serie_uf.to_csv(config.ARQUIVO_PRECOS_UF_MES, index=False, encoding="utf-8", lineterminator="\n")

    if config.ARQUIVO_PRECOS_MUNICIPIO_MES.exists():
        municipios = pd.read_csv(config.ARQUIVO_PRECOS_MUNICIPIO_MES, dtype={"periodo": str})
    else:
        quadros = [historico.agregar_municipios(caminho) for caminho in arquivos]
        janela = config.DATA_RAW / f"{config.carimbo()}-gasolina-etanol.csv"
        if janela.exists():
            quadros.append(historico.agregar_municipios(janela, periodo=config.carimbo()[:7]))
        municipios = pd.concat(quadros, ignore_index=True)
        municipios.to_csv(config.ARQUIVO_PRECOS_MUNICIPIO_MES, index=False, encoding="utf-8", lineterminator="\n")

    return serie_uf, municipios


def parametros_do_baseline(desde: str | None) -> analise.Parametros:
    """Parâmetros do ``baseline.json``, se o loop noturno já rodou.

    Sem isso, uma execução manual de ``inteligencia.py`` reverteria em silêncio o que o loop
    aceitou — dois arquivos publicados com configurações diferentes na mesma pasta.
    """
    padrao = analise.Parametros()
    caminho = RAIZ / "baseline.json"
    if not caminho.exists():
        return padrao if desde is None else analise.Parametros(desde=desde)

    salvo = json.loads(caminho.read_text(encoding="utf-8")).get("parametros") or {}
    if desde is not None:
        salvo["desde"] = desde
    if "atrasos" in salvo:
        salvo["atrasos"] = tuple(salvo["atrasos"])
    conhecidos = {campo for campo in analise.Parametros().__dataclass_fields__} & set(salvo)
    return analise.Parametros(**{campo: salvo[campo] for campo in conhecidos})


def main() -> int:
    """Roda a análise e publica ``site/data/inteligencia.json``."""
    parser = argparse.ArgumentParser(description="Análise de fiscalização × preço (fase 2)")
    parser.add_argument("--baixar", action="store_true", help="busca as fontes que faltam antes de analisar")
    parser.add_argument("--desde", default=None,
                        help="início da janela de correlação (padrão: o que está no baseline.json)")
    argumentos = parser.parse_args()
    parametros = parametros_do_baseline(argumentos.desde)

    if argumentos.baixar:
        baixar_fontes()

    acoes = carregar_acoes()
    serie_uf, municipios = carregar_precos()
    postos = revendedores.postos_por_uf(revendedores.normalizar(revendedores.ler_ufs()))
    if not postos:
        raise SystemExit("sem dados de revendedores em data/raw (rode com --baixar)")

    interditados_cnpj = fiscalizacao.interditos(acoes)

    resultado = analise.avaliar(acoes, serie_uf, municipios, postos, parametros)
    score = resultado["score"]
    evidencias = resultado["evidencias"]
    zonas = resultado["zonas"]
    ipf = resultado["ipf"]
    anomalias = resultado["anomalias"]
    alvos = resultado["alvos"]
    interdição = resultado["interdicao"]
    fisc_municipio = resultado["fisc_municipio"]

    # ``zonas`` já carrega as colunas do IPF (zonas_cegas parte do quadro do IPF): repetir
    # o merge aqui renomearia para ``_x``/``_y`` e o JSON perderia acoes_total/infracoes_12m
    ufs = zonas

    periodos = {
        "fiscalizacao": f"{acoes['periodo'].min()} a {acoes['periodo'].max()}",
        "precos_uf": f"{serie_uf['periodo'].min()} a {serie_uf['periodo'].max()}",
        "correlacao_desde": parametros.desde,
        "janela_ipf_meses": resultado["parametros"]["janela_ipf"],
    }
    cobertura = {
        "acoes_normalizadas": int(len(acoes)),
        "acoes_revenda": int(acoes["revenda"].sum()),
        "interdicoes_revenda": int((acoes["interdicao"] & acoes["revenda"]).sum()),
        "postos_ativos_api": int(sum(postos.values())),
        "ufs": int(len(postos)),
        "municipios_com_preco": int(municipios["municipio"].nunique()),
        "meses_de_preco": int(serie_uf["periodo"].nunique()),
        "municipios_com_fiscalizacao": int(fisc_municipio["municipio"].nunique()),
    }

    payload = analise.montar_inteligencia(
        ufs=ufs,
        evidencias=evidencias,
        anomalias=anomalias,
        alvos=alvos,
        interditados=interditados_cnpj,
        interdição=interdição,
        cobertura=cobertura,
        periodos=periodos,
        score=score,
        pesos=config.PESOS_SCORE_FISCAL,
        parametros=resultado["parametros"],
    )
    config.ARQUIVO_INTELIGENCIA.parent.mkdir(parents=True, exist_ok=True)
    config.ARQUIVO_INTELIGENCIA.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, allow_nan=False) + "\n",
        encoding="utf-8", newline="\n",
    )

    print(f"ações: {cobertura['acoes_normalizadas']:,} ({cobertura['acoes_revenda']:,} em revenda)")
    print(f"postos ativos: {cobertura['postos_ativos_api']:,} em {cobertura['ufs']} UFs")
    print(f"preço: {cobertura['meses_de_preco']} meses, {cobertura['municipios_com_preco']} municípios")
    print(f"score de evidência: {score['score']} em {score['evidencias']} correlações")
    for item in payload["correlacoes"]:
        print(f"  {item['nome']:<42} r={item['r']} p={item['p']} n={item['n']} — {item['leitura']}")
    print(f"anomalias (minimo colado na media): {len(payload['anomalias'])} | alvos: {len(payload['alvos'])}")
    print(f"interdição × preço: {interdição}")
    print(f"gravado: {config.ARQUIVO_INTELIGENCIA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
