"""Configuração central: caminhos, fonte pública e parâmetros do pipeline.

Nenhum módulo deve montar caminho na mão: tudo sai daqui.
"""

from __future__ import annotations

import os
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------- caminhos
RAIZ = Path(__file__).resolve().parents[2]

DATA_RAW = RAIZ / "data" / "raw"
DATA_PROCESSED = RAIZ / "data" / "processed"
SITE = RAIZ / "site"
SITE_DATA = SITE / "data"

ARQUIVO_PROCESSADO = DATA_PROCESSED / "dados.json"
ARQUIVO_DO_SITE = SITE_DATA / "dados.json"

# ---------------------------------------------------------------- coleta
# Página pública que lista os arquivos. O nome do CSV muda a cada mês, então a
# descoberta dos endereços históricos sai daqui (o pipeline usa os de 4 semanas).
FONTE_NOME = "ANP — Levantamento de Preços de Combustíveis"
FONTE_URL = os.environ.get(
    "COMBUSTIVELBR_FONTE_URL",
    "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/"
    "serie-historica-de-precos-de-combustiveis",
)

BASE_ARQUIVOS = "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc"

# Um arquivo por grupo de produto; cada linha é uma revenda (não um resumo).
FONTES_DADOS = (
    ("gasolina-etanol", f"{BASE_ARQUIVOS}/qus/ultimas-4-semanas-gasolina-etanol.csv"),
    ("diesel-gnv", f"{BASE_ARQUIVOS}/qus/ultimas-4-semanas-diesel-gnv.csv"),
)
USER_AGENT = "combustivelBR/0.1 (+https://github.com/Georgebecker/combustivelBR)"
TIMEOUT_SEGUNDOS = 30

# ---------------------------------------------------------------- domínio
# Recorte do projeto. "BR" (padrão) usa todos os estados do arquivo público;
# qualquer outra sigla estreita o recorte (ex.: COMBUSTIVELBR_UF=SC).
UFS_TODAS = ("BR", "TODAS", "")
UF_PADRAO = os.environ.get("COMBUSTIVELBR_UF", "BR")

# O GNV sai em R$/m³ e os demais em R$/litro: somar unidades diferentes mente,
# então a primeira fatia fica só com preço por litro.
UNIDADE_PADRAO = "R$ / litro"

# Produtos reconhecidos no bruto (ver `transformacao.PRODUTOS_ANP`).
PRODUTOS = ("Gasolina", "Gasolina Aditivada", "Diesel", "Diesel S10", "Etanol")

FUSO = ZoneInfo("America/Sao_Paulo")


def garantir_diretorios() -> None:
    """Cria as pastas de trabalho (idempotente)."""
    for caminho in (DATA_RAW, DATA_PROCESSED, SITE_DATA):
        caminho.mkdir(parents=True, exist_ok=True)


def normalizar_texto(texto: str) -> str:
    """``'  Florianópolis '`` -> ``'FLORIANOPOLIS'``: sem acento, sem espaço sobrando.

    Chave de junção entre bases públicas diferentes: sem isto o mesmo município
    entra duas vezes ao cruzar arquivos de fontes distintas.
    """
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    return "".join(letra for letra in sem_acento if not unicodedata.combining(letra)).strip().upper()


def carimbo(agora: datetime | None = None) -> str:
    """Data local (America/Sao_Paulo) no formato usado nos nomes de arquivo bruto."""
    return (agora or datetime.now(FUSO)).strftime("%Y-%m-%d")


# Unidades da federação (a API de revendedores é consultada uma UF por vez).
UFS = (
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
    "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
)

# ---------------------------------------------------------------- fiscalização
BASE_FISCALIZACAO = (
    "https://www.gov.br/anp/pt-br/centrais-de-conteudo/paineis-dinamicos-da-anp/"
    "arquivos-dados-brutos-do-painel-dinamico-da-fiscalizacao-do-abastecimento-da-sfi/"
)
FISCALIZACAO_URLS = (
    ("fiscalizacao-1998-2018", f"{BASE_FISCALIZACAO}dados-fisc-1998-2018.xlsx"),
    ("fiscalizacao-2019-2026", f"{BASE_FISCALIZACAO}dados-fisc-a-partir-2019.xlsx"),
)

# ---------------------------------------------------------------- revendedores
REVENDEDORES_URL = os.environ.get(
    "COMBUSTIVELBR_REVENDEDORES_URL", "https://revendedoresapi.anp.gov.br/v1/combustivel"
)
REVENDEDORES_TIMEOUT_SEGUNDOS = 120
REVENDEDORES_TENTATIVAS = 4
REVENDEDORES_ESPERA_SEGUNDOS = 8
# A API responde 429 quando chamada em sequência: estes códigos pedem nova tentativa.
REVENDEDORES_ESPERA_CODIGOS = (429, 500, 502, 503, 504)

# ---------------------------------------------------------------- inteligência
# ---------------------------------------------------------------- série histórica
# Os arquivos mensais por revenda começam em 2023 (o nome muda de mês para mês).
ANO_INICIO_SERIE = 2023
ANO_FIM_SERIE = 2026

ARQUIVO_INTELIGENCIA = SITE_DATA / "inteligencia.json"
ARQUIVO_PRECOS_UF_MES = DATA_PROCESSED / "precos-uf-mes.csv"
ARQUIVO_PRECOS_MUNICIPIO_MES = DATA_PROCESSED / "precos-municipio-mes.csv"
ARQUIVO_ACOES_UF = DATA_PROCESSED / "fiscalizacao-por-uf.csv"
ARQUIVO_ACOES_UF_MES = DATA_PROCESSED / "fiscalizacao-por-uf-mes.csv"
ARQUIVO_POSTOS_UF = DATA_PROCESSED / "postos-por-uf.csv"
ARQUIVO_ACOES_MUNICIPIO = DATA_PROCESSED / "fiscalizacao-por-municipio.csv"

# Janela em que preço e fiscalização coexistem nas duas bases (o preço começa em 2026-09
# no recorte de 4 semanas; a fiscalização é mensal, então a série começa em 2019).
PERIODO_MINIMO_SERIE = "2019-01"
# Recorte do ranking de municípios-alvo: só o que tem fiscalização e preço no período.
PESOS_SCORE_FISCAL = {"dispersao": 0.35, "fiscalizacao": 0.25, "interdicao": 0.2, "variacao": 0.2}


# ---------------------------------------------------------------- notícias
# Manchetes sobre preço de combustível: o pipeline lê os feeds e publica no mesmo JSON
# (o site continua offline e sem depender de CORS de terceiros).
NOTICIAS_URL = os.environ.get("COMBUSTIVELBR_NOTICIAS_URL", "https://news.google.com/rss/search")

# Feeds de veículos oficiais/públicos. São feeds gerais, então o item só entra se o
# título falar do assunto (ver `noticias.assunto_relevante`).
NOTICIAS_FEEDS = (
    {
        "ambito": "nacional",
        "veiculo": "Agência Brasil",
        "url": "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml",
        "assunto": True,
    },
    {
        "ambito": "nacional",
        "veiculo": "Agência Gov",
        "url": "https://agenciagov.ebc.com.br/rss.xml",
        "assunto": True,
    },
    {
        "ambito": "nacional",
        "veiculo": "Senado Federal",
        "url": "https://www12.senado.leg.br/noticias/rss",
        "assunto": True,
    },
)

# Buscas no agregador público: alcançam ANP, MME, Câmara e o noticiário do exterior.
# Termos entre aspas para não trazer assunto alheio (buscador casa palavra solta).
NOTICIAS_BUSCAS = (
    (
        "nacional",
        '"preço da gasolina" OR "preço do diesel" OR "preço dos combustíveis" '
        'OR "preço do etanol" OR "tributos dos combustíveis" OR "ICMS dos combustíveis" '
        'OR "desconto no preço"',
    ),
    (
        "exterior",
        '"preço do petróleo" OR "barril de petróleo" OR OPEP OR Brent '
        "(alta OR oferta OR corte OR sanções OR conflito)",
    ),
)

# Palavras que fazem uma manchete entrar no resumo (sem acento, minúsculas).
NOTICIAS_ASSUNTO = (
    "combustiv",
    "gasolina",
    "diesel",
    "etanol",
    "gnv",
    "anp",
    "petroleo",
    "brent",
    "refinaria",
    "icms",
    "posto",
    "bomba",
    "barril",
    "opep",
    "petrobras",
    "biocombustiv",
    "derivado",
)

# Assunto alheio que casa por acaso com a palavra do combustível
# (ex.: "GNV Kids" num anúncio de jogo de futebol).
NOTICIAS_RUIDO = (
    "kids",
    "ingresso",
    "jogo",
    "loteria",
    "aposta",
    "mega-sena",
    "palpite",
    "escalacao",
    "campeonato",
    "futebol",
)

NOTICIAS_POR_CONSULTA = 25
NOTICIAS_LIMITE = 12
NOTICIAS_TIMEOUT_SEGUNDOS = 20
