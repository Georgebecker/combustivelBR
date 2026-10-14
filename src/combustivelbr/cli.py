"""Linha de comando do projeto.

    python -m combustivelbr coletar [--amostra] [--url URL]
    python -m combustivelbr processar [--arquivo CAMINHO] [--uf UF]
    python -m combustivelbr pipeline [--amostra] [--url URL] [--uf UF]
    python -m combustivelbr servir [--porta 8000]

Sem ``--amostra`` nem ``--url``, a coleta baixa os arquivos públicos da ANP.
``processar`` sem ``--arquivo`` usa os brutos da fonte: a amostra local fica de fora.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__, coleta, config, noticias, transformacao

AMOSTRA_PADRAO = config.RAIZ / "tests" / "fixtures" / "amostra_precos.csv"

# Como o operador lê as contagens dos cortes no fim da execução (Regras de Ouro, R19).
ROTULOS_DAS_CONTAGENS = {
    "linhas_no_bruto": "linhas lidas",
    "fora_da_unidade": "fora da unidade R$ / litro",
    "fora_da_uf": "fora da UF",
    "produto_desconhecido": "produto fora da lista",
    "sem_data": "sem data válida",
    "sem_preco": "sem preço de venda",
    "linhas_repetidas": "linhas repetidas no arquivo",
    "coletas_resumidas": "coletas por município",
    "coletas_repetidas": "coletas repetidas entre arquivos",
}


def mostrar(caminho: Path) -> str:
    """Caminho relativo à raiz quando possível; absoluto quando está fora dela."""
    try:
        return str(caminho.relative_to(config.RAIZ))
    except ValueError:
        return str(caminho)


def coletar(argumentos: argparse.Namespace) -> list[Path]:
    """Grava o bruto: a amostra local, o endereço informado ou as fontes públicas."""
    if argumentos.amostra:
        return [coleta.usar_amostra(AMOSTRA_PADRAO)]
    if argumentos.url:
        return [coleta.baixar(argumentos.url)]
    return coleta.baixar_fontes()


def imprimir_contagens(contagens: dict[str, int]) -> None:
    """Declara quantas linhas entraram e quantas saíram em cada corte."""
    partes = [
        f"{ROTULOS_DAS_CONTAGENS.get(chave, chave)}: {valor:,}".replace(",", ".")
        for chave, valor in contagens.items()
        if valor or chave == "linhas_no_bruto"
    ]
    if partes:
        print(" | ".join(partes))


def relatar(payload: dict, gravados: list[Path], contagens: dict[str, int]) -> None:
    """Resultado do processamento: cortes, número de registros e arquivos gravados."""
    imprimir_contagens(contagens)
    print(f"{len(payload['registros'])} registros processados")
    for destino in gravados:
        print(f"  gravado: {mostrar(destino)}")


def construir_parser() -> argparse.ArgumentParser:
    """Monta o CLI: um subcomando por etapa (coletar, processar, pipeline e servir)."""
    parser = argparse.ArgumentParser(
        prog="combustivelbr",
        description="Coleta, trata e publica preços de combustíveis (dados públicos).",
    )
    parser.add_argument("--versao", action="version", version=f"combustivelBR {__version__}")
    comandos = parser.add_subparsers(dest="comando", required=True)

    coletar = comandos.add_parser("coletar", help="baixa o bruto da fonte para data/raw/")
    coletar.add_argument("--url", help="endereço alternativo da fonte")
    coletar.add_argument("--amostra", action="store_true", help="usa a amostra local em vez da rede")

    processar = comandos.add_parser("processar", help="data/raw/ -> data/processed/ + site/data/")
    processar.add_argument("--arquivo", type=Path, help="bruto específico (padrão: todos os da fonte)")
    processar.add_argument("--uf", help="recorte de UF (padrão: todas; ex.: SC)")

    pipeline = comandos.add_parser("pipeline", help="coletar e processar em sequência")
    pipeline.add_argument("--url", help="endereço alternativo da fonte")
    pipeline.add_argument("--amostra", action="store_true", help="usa a amostra local em vez da rede")
    pipeline.add_argument("--uf", help="recorte de UF (padrão: todas; ex.: SC)")
    pipeline.add_argument(
        "--sem-noticias", action="store_true", help="não busca manchetes nos feeds públicos"
    )

    servir = comandos.add_parser("servir", help="sobe a API e o site local")
    servir.add_argument("--porta", type=int, default=8000)
    servir.add_argument("--host", default="127.0.0.1")
    servir.add_argument("--recarregar", action="store_true", help="reinicia ao salvar arquivo")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do CLI — é o que ``python -m combustivelbr`` chama."""
    argumentos = construir_parser().parse_args(argv)
    config.garantir_diretorios()

    if argumentos.comando == "coletar":
        for arquivo in coletar(argumentos):
            print(f"bruto gravado: {mostrar(arquivo)}")
        return 0

    if argumentos.comando == "processar":
        relatar(*transformacao.processar(argumentos.arquivo, uf=argumentos.uf))
        return 0

    if argumentos.comando == "pipeline":
        arquivos = coletar(argumentos)
        for arquivo in arquivos:
            print(f"bruto gravado: {mostrar(arquivo)}")

        manchetes = None
        if not argumentos.sem_noticias:
            coletadas = noticias.coletar()
            if coletadas["itens"]:
                manchetes = coletadas
                print(f"manchetes: {len(manchetes['itens'])} (fontes públicas, link para o original)")
            else:
                print("aviso: sem manchetes novas; o JSON mantém as anteriores")

        relatar(
            *transformacao.processar(
                arquivos=arquivos,
                fonte_url=argumentos.url,
                uf=argumentos.uf,
                noticias=manchetes,
            )
        )
        return 0

    if argumentos.comando == "servir":
        import uvicorn

        print(f"site e API em http://{argumentos.host}:{argumentos.porta}/")
        uvicorn.run(
            "combustivelbr.servidor:app",
            host=argumentos.host,
            port=argumentos.porta,
            reload=argumentos.recarregar,
        )
        return 0

    return 1
