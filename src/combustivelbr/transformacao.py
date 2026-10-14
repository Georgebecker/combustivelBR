"""Transforma o bruto de ``data/raw/`` no JSON publicado.

Fluxo do projeto: bruto -> **validado** -> resumo -> ``data/processed/dados.json``
e ``site/data/dados.json`` (o site é estático e lê esse arquivo).
Contrato do JSON: ``docs/ARQUITETURA.md``.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config

# Colunas que o bruto precisa ter depois do tratamento (é o que `resumir` consome).
COLUNAS_OBRIGATORIAS = (
    "data_coleta",
    "estado",
    "municipio",
    "produto",
    "postos_pesquisados",
    "preco_minimo",
    "preco_medio",
    "preco_maximo",
)

COLUNAS_NUMERICAS = ("postos_pesquisados", "preco_minimo", "preco_medio", "preco_maximo")

# Colunas publicadas no recorte por município: é o degrau intermediário que `resumir`
# agrega para chegar ao estado, e o que deixa o site descer ao município sem recalcular.
COLUNAS_MUNICIPIO = (
    "produto",
    "estado",
    "municipio",
    "periodo",
    "postos_pesquisados",
    "preco_minimo",
    "preco_medio",
    "preco_maximo",
)

# Coluna do arquivo público da ANP -> coluna interna. O bruto traz uma linha por
# revenda; o resumo por município é montado em `resumir_estacoes`.
MAPA_COLUNAS = {
    "Estado - Sigla": "estado",
    "Municipio": "municipio",
    "Produto": "produto",
    "Data da Coleta": "data_coleta",
    "Valor de Venda": "preco_medio",
    "Unidade de Medida": "unidade",
    "Revenda": "revenda",
    "CNPJ da Revenda": "revenda_cnpj",
}

# Nome do produto no arquivo público -> nome usado aqui dentro. Gasolina aditivada
# não é gasolina comum (custa mais), então fica em linha própria.
PRODUTOS_ANP = {
    "GASOLINA": "Gasolina",
    "GASOLINA ADITIVADA": "Gasolina Aditivada",
    "DIESEL": "Diesel",
    "DIESEL S10": "Diesel S10",
    "ETANOL": "Etanol",
}

# Identifica uma coleta (município/produto/dia) ao juntar mais de um arquivo bruto.
CHAVE_DA_COLETA = ("data_coleta", "estado", "municipio", "produto")

# Identifica uma revenda numa coleta — é o que evita contar o mesmo posto duas vezes.
CHAVE_DA_REVENDA = ("revenda_id", "produto", "data_coleta")

# Quadro intermediário do arquivo por revenda, antes do resumo por município.
COLUNAS_ESTACAO = ("produto", "estado", "municipio", "revenda_id", "data_coleta", "preco_medio")


class BrutoInvalido(RuntimeError):
    """O bruto não tem as colunas esperadas (o layout da fonte mudou?)."""


def normalizar_municipio(nome: str) -> str:
    """``'  Florianópolis '`` -> ``'FLORIANOPOLIS'``: sem acento, sem espaço sobrando.

    Sem isso o mesmo município entra duas vezes na contagem (com e sem acento).
    """
    return config.normalizar_texto(nome)


def _texto(caminho: Path) -> str:
    """Texto do bruto: UTF-8 (com ou sem BOM) e, se não decodificar, latin-1."""
    conteudo = Path(caminho).read_bytes()
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return conteudo.decode("latin-1")


def _separador(cabecalho: str) -> str:
    """O arquivo público separa por ponto e vírgula; a amostra interna, por vírgula."""
    return ";" if cabecalho.count(";") > cabecalho.count(",") else ","


def _e_layout_anp(df: pd.DataFrame) -> bool:
    """O bruto é o arquivo por revenda da ANP ou já vem no formato interno?"""
    return set(MAPA_COLUNAS).issubset(df.columns)


def _numero(serie: pd.Series) -> pd.Series:
    """Número a partir do texto, aceitando vírgula ou ponto como separador decimal."""
    return pd.to_numeric(
        serie.astype(str).str.strip().str.replace(",", ".", regex=False), errors="coerce"
    )


def _validar(df: pd.DataFrame, caminho: Path) -> pd.DataFrame:
    """Confere que o bruto já resumido tem as colunas internas."""
    faltando = [coluna for coluna in COLUNAS_OBRIGATORIAS if coluna not in df.columns]
    if faltando:
        raise BrutoInvalido(
            f"{caminho.name}: sem as colunas {', '.join(faltando)} "
            f"(encontradas: {', '.join(map(str, df.columns))})"
        )
    return df


def ler_estacoes(df: pd.DataFrame, *, uf: str | None = None) -> tuple[pd.DataFrame, dict[str, int]]:
    """Normaliza o arquivo por revenda: uma linha por revenda/produto/dia.

    Não agrega: a junção de arquivos precisa da revenda para não contar o mesmo
    posto duas vezes (o arquivo de 4 semanas se sobrepõe ao do dia anterior).
    """
    uf = (uf or config.UF_PADRAO).strip().upper()
    contagens = {"linhas_no_bruto": len(df)}
    dados = df.rename(columns=MAPA_COLUNAS).copy()

    # O GNV sai em R$/m³: entrar aqui junto com o litro produziria uma média falsa.
    dados["unidade"] = dados["unidade"].str.strip()
    outra_unidade = dados["unidade"] != config.UNIDADE_PADRAO
    contagens["fora_da_unidade"] = int(outra_unidade.sum())
    dados = dados[~outra_unidade]

    dados["estado"] = dados["estado"].str.strip().str.upper()
    # "BR" é o país inteiro: só corta por UF quando o recorte é uma sigla
    if uf not in config.UFS_TODAS:
        fora_da_uf = dados["estado"] != uf
        contagens["fora_da_uf"] = int(fora_da_uf.sum())
        dados = dados[~fora_da_uf]

    dados["produto"] = dados["produto"].str.strip().str.upper().map(PRODUTOS_ANP)
    sem_produto = dados["produto"].isna()
    contagens["produto_desconhecido"] = int(sem_produto.sum())
    dados = dados[~sem_produto]

    dados["municipio"] = dados["municipio"].map(normalizar_municipio)
    dados["data_coleta"] = _datas(dados["data_coleta"])
    dados["preco_medio"] = _numero(dados["preco_medio"])

    sem_data = dados["data_coleta"].isna()
    contagens["sem_data"] = int(sem_data.sum())
    sem_preco = dados["preco_medio"].isna()
    contagens["sem_preco"] = int(sem_preco.sum())
    dados = dados[~sem_data & ~sem_preco]

    # O CNPJ identifica a revenda; sem ele, o nome da revenda é o rótulo disponível.
    cnpj = dados["revenda_cnpj"].str.strip()
    dados["revenda_id"] = cnpj.mask(cnpj == "", dados["revenda"].str.strip())

    sem_repetidas = dados.drop_duplicates(subset=list(CHAVE_DA_REVENDA), keep="last")
    contagens["linhas_repetidas"] = len(dados) - len(sem_repetidas)
    return sem_repetidas.loc[:, list(COLUNAS_ESTACAO)].reset_index(drop=True), contagens


def _datas(serie: pd.Series) -> pd.Series:
    """Data da coleta em ``AAAA-MM-DD``, aceitando os dois formatos que a fonte já publicou.

    ISO é lido como ISO e ``dd/mm/aaaa`` no formato brasileiro — adivinhar ``dayfirst``
    trocaria dia por mês sem avisar (03/04 é 3 de abril aqui e 4 de março lá fora). Fora
    desses dois formatos a data vira nula, e a linha aparece na contagem ``sem_data`` em vez
    de a base esvaziar em silêncio.
    """
    texto = serie.astype("string").str.strip()
    iso = pd.to_datetime(texto, format="%Y-%m-%d", errors="coerce")
    brasileira = pd.to_datetime(texto, format="%d/%m/%Y", errors="coerce")
    return iso.fillna(brasileira).dt.strftime("%Y-%m-%d")


def resumir_estacoes(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por município/produto/mês, com cada revenda pesando uma vez.

    Pesar cada *coleta* faria a revenda pesquisada três vezes no mês valer o triplo
    das outras; ``postos_pesquisados`` é a contagem de revendas distintas do mês.
    """
    if df.empty:
        return pd.DataFrame(columns=list(COLUNAS_OBRIGATORIAS))

    dados = df.copy()
    dados["periodo"] = dados["data_coleta"].map(periodo)

    por_revenda = dados.groupby(
        ["produto", "estado", "municipio", "revenda_id", "periodo"], as_index=False
    ).agg(
        preco_medio_revenda=("preco_medio", "mean"),
        # mínimo e máximo saem das coletas; a média sai das revendas
        preco_minimo=("preco_medio", "min"),
        preco_maximo=("preco_medio", "max"),
        data_coleta=("data_coleta", "max"),
    )

    resumo = por_revenda.groupby(
        ["produto", "estado", "municipio", "periodo"], as_index=False
    ).agg(
        postos_pesquisados=("revenda_id", "nunique"),
        preco_medio=("preco_medio_revenda", "mean"),
        preco_minimo=("preco_minimo", "min"),
        preco_maximo=("preco_maximo", "max"),
        data_coleta=("data_coleta", "max"),
    )
    return resumo.loc[:, list(COLUNAS_OBRIGATORIAS)].reset_index(drop=True)


def _ler_quadro(caminho: Path) -> pd.DataFrame:
    """Lê o CSV bruto como texto (separador detectado no cabeçalho)."""
    texto = _texto(caminho)
    linhas = texto.splitlines()
    cabecalho = linhas[0] if linhas else ""
    return pd.read_csv(
        io.StringIO(texto), sep=_separador(cabecalho), dtype=str, keep_default_na=False
    )


def estacoes_do_bruto(
    caminho: Path, *, uf: str | None = None
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Lê um bruto e devolve o grão da revenda (sem agregar por município).

    É o que a análise precisa: dispersão de preço e contagem de revendas só existem
    antes do resumo. O quadro tem ``revenda_id``, ``produto``, ``data_coleta`` e ``preco_medio``.
    """
    df = _ler_quadro(caminho)
    if _e_layout_anp(df):
        return ler_estacoes(df, uf=uf)
    return _validar(df, caminho), {"linhas_no_bruto": len(df)}


def preparar(caminho: Path, *, uf: str | None = None) -> tuple[pd.DataFrame, dict[str, int]]:
    """Lê um bruto e devolve o quadro no formato interno, com as contagens de cada corte."""
    df = _ler_quadro(caminho)
    if _e_layout_anp(df):
        estacoes, contagens = ler_estacoes(df, uf=uf)
        resumo = resumir_estacoes(estacoes)
        contagens["coletas_resumidas"] = len(resumo)
        return resumo, contagens
    return _validar(df, caminho), {"linhas_no_bruto": len(df)}


def ler_bruto(caminho: Path) -> pd.DataFrame:
    """Lê o CSV bruto e devolve o quadro no formato interno (sem as contagens)."""
    return preparar(caminho)[0]


def ler_brutos(
    caminhos: Iterable[Path], *, uf: str | None = None
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Lê vários brutos e junta: a mesma coleta de posto conta uma vez só.

    O arquivo de 4 semanas se sobrepõe ao do dia anterior — sem esta junção no nível
    da revenda, o mesmo posto entraria duas vezes no preço do mês.
    """
    estacoes: list[pd.DataFrame] = []
    quadros: list[pd.DataFrame] = []
    contagens: dict[str, int] = {"linhas_no_bruto": 0}

    for caminho in caminhos:
        df = _ler_quadro(caminho)
        if _e_layout_anp(df):
            estacao, parciais = ler_estacoes(df, uf=uf)
            estacoes.append(estacao)
        else:
            quadros.append(_validar(df, caminho))
            parciais = {"linhas_no_bruto": len(df)}
        for chave, valor in parciais.items():
            contagens[chave] = contagens.get(chave, 0) + valor

    if estacoes:
        estacoes_juntas = pd.concat(estacoes, ignore_index=True)
        sem_repetidas = estacoes_juntas.drop_duplicates(
            subset=list(CHAVE_DA_REVENDA), keep="last"
        )
        contagens["coletas_repetidas"] = len(estacoes_juntas) - len(sem_repetidas)
        quadros.append(resumir_estacoes(sem_repetidas))

    if not quadros:
        raise BrutoInvalido("nenhum bruto informado para processar")

    junto = pd.concat(quadros, ignore_index=True)
    sem_repetidas = junto.drop_duplicates(subset=list(CHAVE_DA_COLETA), keep="last")
    contagens["coletas_repetidas"] = (
        contagens.get("coletas_repetidas", 0) + len(junto) - len(sem_repetidas)
    )
    contagens["coletas_resumidas"] = len(sem_repetidas)
    return sem_repetidas.reset_index(drop=True), contagens


def _com_numeros(df: pd.DataFrame) -> pd.DataFrame:
    """Converte as colunas numéricas aceitando vírgula ou ponto como separador decimal."""
    convertido = df.copy()
    for coluna in COLUNAS_NUMERICAS:
        convertido[coluna] = _numero(convertido[coluna])
    return convertido


def periodo(data_coleta: str) -> str:
    """``'2026-09-03'`` -> ``'2026-09'`` (mês de referência do dado)."""
    return str(data_coleta)[:7]


def tipos_nativos(registros: list[dict]) -> list[dict]:
    """Converte tipos do numpy para tipos do Python e normaliza ausentes para ``None``.

    ``json.dumps`` não aceita numpy nem ``NaN``.
    """
    limpos = []
    for registro in registros:
        linha = {}
        for chave, valor in registro.items():
            if hasattr(valor, "item"):
                valor = valor.item()
            if valor is None or (isinstance(valor, float) and valor != valor):
                linha[chave] = None
            elif isinstance(valor, float):
                linha[chave] = round(valor, 3)
            else:
                linha[chave] = valor
        limpos.append(linha)
    return limpos


def resumir(df: pd.DataFrame) -> list[dict]:
    """Uma linha por produto/estado/mês, com preço médio, mínimo, máximo e nº de postos.

    O preço médio é **ponderado** pelo número de postos pesquisados: média de médias mente
    quando o tamanho das amostras difere (Regras de Ouro, R14 e R20).
    """
    dados = _com_numeros(df)
    dados["periodo"] = dados["data_coleta"].map(periodo)
    dados["_peso_x_preco"] = dados["preco_medio"] * dados["postos_pesquisados"]

    agrupado = (
        dados.groupby(["produto", "estado", "periodo"], as_index=False)
        .agg(
            municipios=("municipio", "nunique"),
            postos_pesquisados=("postos_pesquisados", "sum"),
            _peso_x_preco=("_peso_x_preco", "sum"),
            preco_minimo=("preco_minimo", "min"),
            preco_maximo=("preco_maximo", "max"),
        )
    )
    agrupado["preco_medio"] = (
        agrupado["_peso_x_preco"] / agrupado["postos_pesquisados"]
    ).where(agrupado["postos_pesquisados"] > 0)

    agrupado = (
        agrupado.drop(columns=["_peso_x_preco"])
        .sort_values(["produto", "estado", "periodo"])
        .reset_index(drop=True)
    )
    return tipos_nativos(agrupado.to_dict(orient="records"))


def resumir_municipios(df: pd.DataFrame) -> list[dict]:
    """Uma linha por produto/estado/município/mês — o degrau que ``resumir`` agrega.

    Não é um cálculo novo: é o mesmo quadro que o resumo por estado consome, publicado à
    mostra para o site descer ao município sem refazer conta. ``postos_pesquisados`` conta
    revendas distintas do mês, como no resumo por estado.
    """
    if df.empty:
        return []
    dados = _com_numeros(df)
    dados["periodo"] = dados["data_coleta"].map(periodo)
    dados = dados.sort_values(["produto", "estado", "municipio", "periodo"]).reset_index(drop=True)
    return tipos_nativos(dados.loc[:, list(COLUNAS_MUNICIPIO)].to_dict(orient="records"))


def nome_dos_brutos(arquivo_bruto: Path | str | Iterable[Path] | None) -> str:
    """Nome do arquivo bruto lido (ou dos arquivos, separados por vírgula)."""
    if arquivo_bruto is None:
        return ""
    if isinstance(arquivo_bruto, (str, Path)):
        return Path(arquivo_bruto).name
    return ", ".join(Path(caminho).name for caminho in arquivo_bruto)


def noticias_anteriores() -> dict:
    """Notícias da última publicação, para o site não ficar sem nada quando a rede falha."""
    vazio = {"coletado_em": "", "itens": []}
    if not config.ARQUIVO_PROCESSADO.exists():
        return vazio
    try:
        anterior = json.loads(config.ARQUIVO_PROCESSADO.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return vazio
    return anterior.get("noticias") or vazio


def montar_payload(
    df: pd.DataFrame,
    *,
    fonte_url: str | None = None,
    arquivo_bruto: Path | str | Iterable[Path] | None = None,
    uf: str | None = None,
    noticias: dict | None = None,
    coletado_em: datetime | None = None,
    gerado_em: datetime | None = None,
) -> dict:
    """Monta o objeto publicado no JSON (contrato em ``docs/ARQUITETURA.md``)."""
    agora = datetime.now(config.FUSO)
    registros = resumir(df)

    return {
        "gerado_em": (gerado_em or agora).isoformat(timespec="seconds"),
        "fonte": {
            "nome": config.FONTE_NOME,
            "url": fonte_url or config.FONTE_URL,
            "arquivo_bruto": nome_dos_brutos(arquivo_bruto),
            "coletado_em": (coletado_em or agora).isoformat(timespec="seconds"),
        },
        "uf": (uf or config.UF_PADRAO).strip().upper(),
        "produtos": sorted({registro["produto"] for registro in registros}),
        "periodos": sorted({registro["periodo"] for registro in registros}),
        "registros": registros,
        "municipios": resumir_municipios(df),
        "noticias": noticias if noticias is not None else noticias_anteriores(),
    }


def gravar(payload: dict, destinos: Iterable[Path] | None = None) -> list[Path]:
    """Grava o mesmo JSON em ``data/processed/`` e em ``site/data/``."""
    destinos = list(destinos or (config.ARQUIVO_PROCESSADO, config.ARQUIVO_DO_SITE))
    gravados = []

    for destino in destinos:
        destino.parent.mkdir(parents=True, exist_ok=True)
        # allow_nan=False: NaN não é JSON válido e o navegador não conseguiria ler o arquivo.
        # Se algum NaN escapar de `tipos_nativos`, o erro aparece aqui, não no site.
        texto = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        # newline explicito: no Windows o padrao do Python seria CRLF e o projeto usa LF
        destino.write_text(texto, encoding="utf-8", newline="\n")
        gravados.append(destino)

    return gravados


def processar(
    arquivo_bruto: Path | None = None,
    *,
    fonte_url: str | None = None,
    arquivos: Iterable[Path] | None = None,
    uf: str | None = None,
    noticias: dict | None = None,
) -> tuple[dict, list[Path], dict[str, int]]:
    """Lê o(s) bruto(s), monta o payload e grava nos dois destinos.

    Sem ``arquivos`` nem ``arquivo_bruto``, lê todos os brutos da pasta do bruto.
    Devolve (payload, arquivos gravados, contagens de cada corte).
    """
    if arquivos is None:
        if arquivo_bruto is None:
            from . import coleta

            # sem a amostra local: ela é semente de teste e não entra no recorte real
            arquivos = coleta.brutos_da_fonte() or coleta.brutos()
        else:
            arquivos = [Path(arquivo_bruto)]
    arquivos = [Path(caminho) for caminho in arquivos]
    if not arquivos:
            raise BrutoInvalido("nada em data/raw/: rode a coleta antes de processar")

    quadro, contagens = ler_brutos(arquivos, uf=uf)
    payload = montar_payload(
        quadro,
        fonte_url=fonte_url,
        arquivo_bruto=arquivos,
        uf=uf,
        noticias=noticias,
        coletado_em=datetime.fromtimestamp(
            max(caminho.stat().st_mtime for caminho in arquivos), tz=config.FUSO
        ),
    )
    return payload, gravar(payload), contagens
