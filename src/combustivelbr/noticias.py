"""Manchetes sobre preço de combustível, lidas de feeds públicos (RSS).

O site é estático e funciona offline: quem lê o feed é o pipeline, e o resultado vai
para o mesmo JSON que o site já consome. A coleta é *best-effort* — se a rede falhar,
o JSON mantém as notícias da execução anterior em vez de derrubar o pipeline.

Do feed guardamos só o necessário para levar o leitor até a fonte: título, veículo,
endereço e data. O texto da matéria é de quem publicou, não nosso.
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import requests

from . import config

# Como ler o tom da manchete (comparação sem acento e em minúsculas).
#
# Duas famílias de palavra, com pesos diferentes na decisão:
#   direção  — o título diz para onde o preço foi ("cai", "sobe"): decide sozinho;
#   contexto — o título explica o motivo, sem dizer a direção ("guerra", "subsídio"):
#              só decide quando não há direção nenhuma.
# Sem essa separação "estabilidade ao longo da guerra com subsídios" virava alívio no bolso
# só porque a palavra "subsídio" estava lá.

PALAVRAS_QUEDA = (
    "queda",
    "quedas",
    "recuo",
    "cai",
    "caiu",
    "caem",
    "derruba",
    "recua",
    "recuam",
    "despenca",
    "abaixo de",
    "mais barato",
    "reduz",
    "reducao",
    "reducoes",
)

PALAVRAS_ALTA = (
    "alta",
    "altas",
    "sobe",
    "sobem",
    "subiu",
    "aumenta",
    "aumento",
    "aumentos",
    "reajuste",
    "encarece",
    "dispara",
    "eleva",
    "ultrapassa",
    "salta",
    "avanco",
    "acima de",
    "mais caro",
)

# Contexto de alívio: política pública que tende a segurar o preço na bomba.
PALAVRAS_ALIVIO = (
    "desconto",
    "zera",
    "zero",
    "corta",
    "corte",
    "cortes",
    "suspens",
    "congela",
    "barat",
    "alivio",
    "desonera",
    "isencao",
    "subsidi",
)

# Contexto de pressão: choque de oferta ou de custo que empurra o preço para cima, mesmo
# quando o título não traz verbo de preço.
PALAVRAS_PRESSAO = (
    "guerra",
    "guerras",
    "belico",
    "ataque",
    "ataques",
    "bombardeio",
    "houthi",
    "tensao",
    "tensoes",
    "escalada",
    "embargo",
    "sancao",
    "sancoes",
    "estreito de ormus",
    "oriente medio",
    "fechamento de porto",
    "cessar-fogo rompido",
    "conflito",
    "crise",
    "escassez",
    "pressao",
    "carestia",
    "piora",
)

# Oferta e demanda: a palavra de direção pode estar falando de **disponibilidade**, não de
# preço. "Alta na produção" é mais combustível no mercado (alívio para o bolso; produção
# interna reduz o risco de desabastecimento e a exposição a conflito externo), enquanto
# "queda na produção" e "alta na demanda" são pressão. O padrão exige o verbo perto do
# substantivo para não ler frase solta.
_VERBOS_SUBIDA = (
    r"(alta|altas|aumento|aumenta|aumentam|eleva|elevacao|amplia|ampliacao|avanco|avanca|"
    r"avancam|recorde|sobe|sobem|retoma|retomada|nova|novas|mais)"
)
_VERBOS_OFERTA_MENOR = (
    r"(corte|cortes|corta|cortam|queda|reducao|reduz|reduzem|parada|interrupcao|interrompe|"
    r"ataque|ataques|bombardeio|fechamento|fecha|suspensao|suspende|derruba|derrubam)"
)
_SUPRIMENTO = r"(producao|oferta|capacidade|refino|refinaria|refinarias|exportacao|autossuficiencia)"
_DEMANDA = r"(demanda|importacao|consumo)"

PADROES_OFERTA = (
    # O substantivo também vem antes do qualificador: "produção recorde", "oferta maior".
    (
        rf"{_SUPRIMENTO}(?:\s+\S+){{0,2}}\s+(recorde|maior|ampliada|ampliadas|crescente|"
        r"suficiente|em alta)",
        "alivio",
    ),
    (rf"{_VERBOS_SUBIDA}(?:\s+\S+){{0,5}}\s+{_SUPRIMENTO}", "alivio"),
    (rf"{_VERBOS_OFERTA_MENOR}(?:\s+\S+){{0,5}}\s+{_SUPRIMENTO}", "pressao"),
    (rf"{_VERBOS_SUBIDA}(?:\s+\S+){{0,5}}\s+{_DEMANDA}", "pressao"),
)

# Chaves que valem como **começo** de palavra: "suspens" pega suspensão, suspender e
# suspensões; as demais exigem palavra inteira (com plural regular).
PALAVRAS_PREFIXO = ("suspens", "barat", "subsidi", "desonera", "congela", "reduz")

# Desconto que não chegou à bomba também pesa no bolso do motorista.
FRASES_SEM_REPASSE = (
    "nao repass",
    "nao chegou a bomba",
    "nao chega a bomba",
    "nao caiu",
    "nao recuou",
    "seguram o preco",
    "resistem em")

# Nome do estado como aparece na manchete -> sigla usada pelo recorte.
ESTADOS = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA",
    "ceara": "CE", "distrito federal": "DF", "espirito santo": "ES", "goias": "GO",
    "maranhao": "MA", "mato grosso": "MT", "mato grosso do sul": "MS",
    "minas gerais": "MG", "paraiba": "PB", "parana": "PR", "pernambuco": "PE",
    "piaui": "PI", "rio de janeiro": "RJ", "rio grande do norte": "RN",
    "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR", "santa catarina": "SC",
    "sao paulo": "SP", "sergipe": "SE", "tocantins": "TO", "para": "PA",
}

SIGLAS = tuple(sorted({sigla for sigla in ESTADOS.values()}))


class FalhaDeNoticias(RuntimeError):
    """Não deu para ler o feed de notícias (rede, formato ou resposta vazia)."""


def sem_acento(texto: str) -> str:
    """``'Preço da Gasolina'`` -> ``'preco da gasolina'`` (busca de palavra-chave)."""
    return _dobra(texto).lower()


def _dobra(texto: str) -> str:
    """Tira o acento preservando a caixa — "Pará" vira "Para", "para" continua "para"."""
    decomposto = unicodedata.normalize("NFKD", str(texto))
    return "".join(letra for letra in decomposto if not unicodedata.combining(letra))


def _texto(elemento: ET.Element | None) -> str:
    return (elemento.text or "").strip() if elemento is not None else ""


def _data(bruto: str) -> str:
    """Data do feed em ISO-8601 (``''`` quando o feed não traz data legível)."""
    if not bruto:
        return ""
    try:
        momento = parsedate_to_datetime(bruto)
    except (TypeError, ValueError):
        return ""
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.isoformat(timespec="seconds")


def classificar(titulo: str) -> str:
    """Tom da manchete: ``beneficio`` (alivia o bolso), ``prejuizo`` ou ``neutro``.

    É leitura automática por palavra-chave, não é a conclusão de ninguém: o site
    mostra o rótulo como pista, com o link para o leitor conferir.
    """
    alvo = sem_acento(titulo)
    if any(frase in alvo for frase in FRASES_SEM_REPASSE):
        return "prejuizo"

    # Tira do texto os trechos que falam de oferta: eles saem da leitura de preço e passam a
    # contar do lado certo (oferta ampliada alivia, oferta cortada pesa).
    alvo, oferta_ampla, oferta_apertada = _separar_oferta(alvo)

    queda = _contar(alvo, PALAVRAS_QUEDA) + oferta_ampla
    alta = _contar(alvo, PALAVRAS_ALTA) + oferta_apertada
    if queda != alta:
        return "beneficio" if queda > alta else "prejuizo"

    # Sem direção no título (ou com as duas), quem decide é o motivo declarado. No empate
    # fica "prejuizo": choque de oferta (guerra, embargo, crise) eleva o preço, e uma palavra
    # de política no mesmo título não cancela o choque — quem abastece paga a conta.
    pressao = _contar(alvo, PALAVRAS_PRESSAO)
    alivio = _contar(alvo, PALAVRAS_ALIVIO)
    if pressao or alivio:
        return "prejuizo" if pressao >= alivio else "beneficio"
    return "neutro"


def _separar_oferta(alvo: str) -> tuple[str, int, int]:
    """Separa o que o título diz de oferta: devolve (resto, alívios, pressões).

    O trecho casado sai do texto para não ser lido de novo como direção de preço.
    """
    contagem = {"alivio": 0, "pressao": 0}
    for padrao, lado in PADROES_OFERTA:
        def _trocar(_casado: re.Match[str], lado: str = lado) -> str:
            contagem[lado] += 1
            return " "

        alvo = re.sub(padrao, _trocar, alvo)
    return alvo, contagem["alivio"], contagem["pressao"]


def _contar(alvo: str, palavras: tuple[str, ...]) -> int:
    """Quantas palavras-chave aparecem no título já normalizado.

    A busca exige **fim de palavra** (plural com ``s``/``es`` ainda conta): sem isso "cai"
    casaria dentro de "caixa" e uma manchete de banco viraria alívio no bolso. Os radicais
    que valem como começo de palavra estão em :data:`PALAVRAS_PREFIXO`.
    """
    total = 0
    for palavra in palavras:
        chave = re.escape(palavra)
        padrao = rf"(?<![a-z]){chave}" if palavra in PALAVRAS_PREFIXO else rf"(?<![a-z]){chave}(?:s|es)?(?![a-z])"
        if re.search(padrao, alvo):
            total += 1
    return total


def estados_citados(titulo: str) -> list[str]:
    """Siglas dos estados citados na manchete.

    O nome do estado só conta quando vem como nome próprio ("Pará", "Santa Catarina"):
    em minúsculas, "para" é a preposição e viraria um estado fantasma na contagem.
    """
    alvo = _dobra(titulo)
    palavras = set(re.findall(r"[A-Za-z]+", alvo))
    citados = {sigla for sigla in SIGLAS if sigla in palavras}

    for nome, sigla in ESTADOS.items():
        formas = (" ".join(parte.capitalize() for parte in nome.split()), nome.upper())
        for forma in formas:
            if re.search(rf"(?<![A-Za-z]){forma}(?![A-Za-z])", alvo):
                citados.add(sigla)
                break

    return sorted(citados)


def assunto_relevante(titulo: str) -> bool:
    """A manchete fala de combustível? (feeds oficiais são gerais e a busca casa palavra solta)"""
    alvo = sem_acento(titulo)
    if any(ruido in alvo for ruido in config.NOTICIAS_RUIDO):
        return False
    return any(palavra in alvo for palavra in config.NOTICIAS_ASSUNTO)


def ler_feed(texto: str | bytes, ambito: str, veiculo_padrao: str = "") -> list[dict]:
    """Itens de um feed RSS (título, veículo, endereço, data, tom e estados)."""
    try:
        raiz = ET.fromstring(texto)
    except ET.ParseError as erro:
        raise FalhaDeNoticias(f"feed ilegível ({ambito}): {erro}") from erro

    itens = []
    for item in raiz.iter("item"):
        # O veículo vem no <source>; feed sem essa tag usa o nome do próprio feed
        veiculo = _texto(item.find("source")) or veiculo_padrao
        titulo = _texto(item.find("title"))
        # O agregador repete o veículo no fim do título: "Manchete - Veículo"
        if veiculo and titulo.endswith(f" - {veiculo}"):
            titulo = titulo[: -(len(veiculo) + 3)].strip()

        endereco = _texto(item.find("link")) or _texto(item.find("guid"))
        if not titulo or not endereco.startswith("http"):
            continue

        itens.append(
            {
                "titulo": titulo,
                "fonte": veiculo or "fonte não identificada",
                "url": endereco,
                "publicado_em": _data(_texto(item.find("pubDate"))),
                "ambito": ambito,
                "tom": classificar(titulo),
                "estados": estados_citados(titulo),
            }
        )
    return itens


def _buscar_no_agregador(ambito: str, consulta: str) -> list[dict]:
    """Uma consulta no agregador público de notícias (feeds por termo de busca)."""
    parametros = urlencode({"q": consulta, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"})
    resposta = requests.get(
        config.NOTICIAS_URL,
        params=parametros,
        timeout=config.NOTICIAS_TIMEOUT_SEGUNDOS,
        headers={"User-Agent": config.USER_AGENT},
    )
    resposta.raise_for_status()
    itens = ler_feed(resposta.content, ambito, "agregador público")
    return itens[: config.NOTICIAS_POR_CONSULTA]


def buscar() -> list[dict]:
    """Manchetes dos feeds oficiais e das buscas: uma fonte fora do ar não derruba as outras."""
    itens: list[dict] = []

    for fonte in config.NOTICIAS_FEEDS:
        try:
            resposta = requests.get(
                fonte["url"],
                timeout=config.NOTICIAS_TIMEOUT_SEGUNDOS,
                headers={"User-Agent": config.USER_AGENT},
            )
            resposta.raise_for_status()
            encontrados = ler_feed(resposta.content, fonte["ambito"], fonte["veiculo"])
        except (requests.RequestException, FalhaDeNoticias):
            continue

        if fonte["assunto"]:
            encontrados = [item for item in encontrados if assunto_relevante(item["titulo"])]
        itens.extend(encontrados)

    for ambito, consulta in config.NOTICIAS_BUSCAS:
        try:
            encontrados = _buscar_no_agregador(ambito, consulta)
        except (requests.RequestException, FalhaDeNoticias):
            continue
        itens.extend([item for item in encontrados if assunto_relevante(item["titulo"])])

    return itens


def _selecionar(itens: list[dict]) -> list[dict]:
    """Escolha equilibrada: alívio, aperto e exterior precisam caber no mesmo resumo.

    Sem esta escolha, o corte por limite deixaria o exterior de fora — justamente o
    que o leitor quer ver antes de o preço subir na bomba.
    """
    recentes = sorted(itens, key=lambda item: item["publicado_em"] or "", reverse=True)
    escolhidos: list[dict] = []
    vistos: set[str] = set()

    def juntar(candidatos: list[dict], quantos: int) -> None:
        """Completa a lista com candidatos até o limite, equilibrando os tons.

        A ordem de entrada já vem do interesse (alívio, peso, neutro, exterior); aqui só se
        respeita o teto de itens para o site não virar um mural de manchetes.
        """
        for item in candidatos:
            if quantos <= 0 or len(escolhidos) >= config.NOTICIAS_LIMITE:
                return
            chave = sem_acento(item["titulo"])[:90]
            if chave in vistos:
                continue
            vistos.add(chave)
            escolhidos.append(item)
            quantos -= 1

    juntar([item for item in recentes if item["tom"] == "beneficio"], 4)
    juntar([item for item in recentes if item["tom"] == "prejuizo"], 4)
    juntar([item for item in recentes if item["ambito"] == "exterior"], 4)
    juntar(recentes, config.NOTICIAS_LIMITE)
    return escolhidos


def coletar() -> dict:
    """Notícias prontas para o JSON. Rede fora do ar vira lista vazia, nunca exceção."""
    try:
        itens = buscar()
    except (requests.RequestException, FalhaDeNoticias):
        itens = []

    return {
        "coletado_em": datetime.now(config.FUSO).isoformat(timespec="seconds"),
        "itens": _selecionar(itens),
    }
