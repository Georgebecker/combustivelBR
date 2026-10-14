"""Testes das notícias: leitura do feed, tom da manchete e montagem da lista.

Rodam sem rede: o feed é ``tests/fixtures/noticias.xml`` e a busca é substituída
por ``monkeypatch``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from combustivelbr import config, noticias, transformacao

FEED = Path(__file__).parent / "fixtures" / "noticias.xml"
AMOSTRA = Path(__file__).parent / "fixtures" / "amostra_precos.csv"

OFICIAL = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Queda da gasolina chega aos postos de Santa Catarina</title>
    <link>https://exemplo.test/oficial/1</link>
    <pubDate>Sat, 10 Oct 2026 12:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Bets devolvem dinheiro a apostadores</title>
    <link>https://exemplo.test/oficial/2</link>
    <pubDate>Sat, 10 Oct 2026 13:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""

AGREGADOR = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Brent sobe com conflito e pressiona o diesel - Reuters</title>
    <link>https://exemplo.test/agregador/1</link>
    <pubDate>Sun, 11 Oct 2026 09:00:00 GMT</pubDate>
    <source url="https://www.reuters.com">Reuters</source>
  </item>
</channel></rss>
"""


class RespostaFalsa:
    """Resposta mínima de rede, para os testes não dependerem de internet."""

    def __init__(self, conteudo: str, status: int = 200):
        self.content = conteudo.encode("utf-8")
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture()
def bruto():
    return transformacao.ler_bruto(AMOSTRA)


@pytest.fixture()
def itens():
    return noticias.ler_feed(FEED.read_bytes(), "nacional")


def achar(lista: list[dict], titulo: str) -> dict:
    for item in lista:
        if item["titulo"] == titulo:
            return item
    raise AssertionError(f"nenhum item com título {titulo!r}")


# ---------------------------------------------------------------- leitura do feed
def test_le_os_itens_do_feed(itens):
    assert len(itens) == 4  # o item sem título é ignorado


def test_tira_o_nome_do_veiculo_do_fim_do_titulo(itens):
    primeiro = achar(
        itens, "Governo zera tributos sobre a gasolina e publica MP de R$ 7,5 bilhões"
    )

    assert primeiro["fonte"] == "Agência Brasil"
    assert primeiro["url"] == "https://exemplo.test/nacional/tributos"


def test_data_do_feed_vira_iso(itens):
    primeiro = achar(
        itens, "Governo zera tributos sobre a gasolina e publica MP de R$ 7,5 bilhões"
    )

    assert primeiro["publicado_em"] == "2026-10-09T15:02:47+00:00"


def test_guarda_o_ambito_da_consulta(itens):
    assert {item["ambito"] for item in itens} == {"nacional"}


def test_feed_ilegivel_avisa(tmp_path):
    arquivo = tmp_path / "quebrado.xml"
    arquivo.write_text("<rss><channel>", encoding="utf-8")

    with pytest.raises(noticias.FalhaDeNoticias, match="feed ilegível"):
        noticias.ler_feed(arquivo.read_text(encoding="utf-8"), "nacional")


def test_usa_o_nome_do_feed_quando_o_item_nao_traz_o_veiculo():
    """Feeds oficiais não têm <source>: o veículo é o próprio feed."""
    itens = noticias.ler_feed(OFICIAL, "nacional", "Agência Brasil")

    assert itens[0]["fonte"] == "Agência Brasil"
    assert len(itens) == 2


def test_item_sem_endereco_util_e_ignorado():
    feed = """<?xml version="1.0"?><rss><channel><item>
      <title>Sem link</title><guid>nao-e-endereco</guid>
    </item></channel></rss>"""

    assert noticias.ler_feed(feed, "nacional") == []


# ---------------------------------------------------------------- assunto e fontes
def test_assunto_fala_de_combustivel():
    assert noticias.assunto_relevante("ANP divulga preços do diesel")
    assert noticias.assunto_relevante("Postos reduzem o etanol em SP")
    assert not noticias.assunto_relevante("Bets devolvem dinheiro a apostadores")
    assert not noticias.assunto_relevante("Senado homenageia associação beneficente")


def test_assunto_alheio_com_palavra_de_combustivel_nao_entra():
    """'GNV Kids' casou com a palavra do combustível, mas a manchete é de futebol."""
    assert not noticias.assunto_relevante("Galo x Coritiba: ingressos a R$ 29,90 e GNV Kids")
    assert not noticias.assunto_relevante("Jogo do campeonato: ingressos com desconto na gasolina")
    assert noticias.assunto_relevante("Brent sobe e pressiona o preço do diesel")


def test_buscar_junta_as_fontes_e_filtra_o_assunto(monkeypatch):
    """Feed oficial traz assunto geral: só entra o que fala de combustível."""
    def get_falso(url, **_):
        if "senado" in url:
            raise requests.ConnectionError("feed fora do ar")
        if "agencia" in url:
            return RespostaFalsa(OFICIAL)
        return RespostaFalsa(AGREGADOR)

    monkeypatch.setattr(noticias.requests, "get", get_falso)

    titulos = [item["titulo"] for item in noticias.buscar()]

    assert "Queda da gasolina chega aos postos de Santa Catarina" in titulos
    assert "Bets devolvem dinheiro a apostadores" not in titulos
    assert "Brent sobe com conflito e pressiona o diesel" in titulos


def test_buscar_aguenta_fonte_fora_do_ar(monkeypatch):
    def get_falso(url, **_):
        raise requests.ConnectionError("sem rede")

    monkeypatch.setattr(noticias.requests, "get", get_falso)

    assert noticias.buscar() == []


# ---------------------------------------------------------------- tom e estados
def test_tom_de_beneficio():
    assert noticias.classificar("Governo zera tributos sobre a gasolina") == "beneficio"
    assert noticias.classificar("Queda do etanol chega aos postos") == "beneficio"


def test_tom_de_prejuizo():
    assert noticias.classificar("Brent sobe com conflito no Oriente Médio") == "prejuizo"
    assert noticias.classificar("Reajuste encarece o diesel nas refinarias") == "prejuizo"


def test_desconto_que_nao_chegou_a_bomba_pesa_no_bolso():
    """'Não repassam a queda' tem palavra de queda, mas o efeito é o contrário."""
    assert noticias.classificar("Postos de MG ainda não repassam a queda do diesel") == "prejuizo"


def test_tom_neutro_quando_nao_ha_palavra_de_peso():
    assert noticias.classificar("ANP divulga levantamento semanal de preços") == "neutro"


def test_guerra_pesa_no_bolso_mesmo_sem_verbo_de_preco():
    """Caso real publicado: 'estabilidade ao longo da guerra com subsídios' não é alívio."""
    assert noticias.classificar(
        "Preço da gasolina mantém estabilidade ao longo da guerra com subsídios"
    ) == "prejuizo"
    assert noticias.classificar(
        "Petróleo Brent ultrapassa US$ 107 após ataque Houthi a aeroporto saudita"
    ) == "prejuizo"


def test_direcao_do_preco_vence_o_contexto():
    """O título que diz para onde o preço foi manda, mesmo citando a causa contrária."""
    assert noticias.classificar("Fim da guerra derruba o preço do petróleo") == "beneficio"
    assert noticias.classificar("Governo corta tributo do diesel") == "beneficio"


def test_oferta_ampliada_alivia_o_bolso():
    """Mais produção interna é mais combustível no mercado: alívio, não peso.

    A palavra de direção aqui fala de **oferta**, não de preço — ler "alta" como preço
    invertia o sentido da manchete.
    """
    assert noticias.classificar(
        "Opep prevê alta recorde na produção de combustíveis no Brasil em 2026"
    ) == "beneficio"
    assert noticias.classificar(
        "Opep mantém projeção de alta de 600 mil bpd na oferta fora da Opep+ em 2026"
    ) == "beneficio"
    assert noticias.classificar(
        "Produção recorde no Brasil afasta risco de desabastecimento em meio a guerra"
    ) == "beneficio"


def test_oferta_cortada_pesa_no_bolso():
    """O contrário também vale: menos oferta é peso, mesmo com verbo que sugere queda."""
    assert noticias.classificar(
        "OPEP discute corte de produção em meio a guerra comercial"
    ) == "prejuizo"
    assert noticias.classificar(
        "Ataque a refinaria na Arábia derruba a oferta mundial de petróleo"
    ) == "prejuizo"


def test_palavra_curta_nao_casa_dentro_de_outra():
    """'cai' dentro de 'Caixa' classificava manchete de banco como alívio no bolso."""
    assert noticias.classificar("Caixa reduz juros do financiamento") == "beneficio"
    assert noticias.classificar("Gasolina cai nos postos de SP") == "beneficio"


def test_acha_o_estado_pela_sigla_e_pelo_nome():
    assert noticias.estados_citados("Postos de MG não repassam a queda") == ["MG"]
    assert noticias.estados_citados("Preço cai em Santa Catarina e no Pará") == ["PA", "SC"]
    assert noticias.estados_citados("Brent sobe no exterior") == []


def test_preposicao_para_nao_vira_o_estado_do_para():
    assert noticias.estados_citados("Governo zera tributos para os motoristas") == []
    assert noticias.estados_citados("Governo zera tributos para o PARÁ") == ["PA"]


# ---------------------------------------------------------------- lista final
def test_coletar_sem_rede_devolve_lista_vazia(monkeypatch):
    def explodir():
        raise requests.ConnectionError("rede fora")

    monkeypatch.setattr(noticias, "buscar", explodir)

    coletadas = noticias.coletar()

    assert coletadas["itens"] == []
    assert coletadas["coletado_em"]


def test_coletar_tira_repetidas_e_corta_no_limite(monkeypatch):
    repetida = {
        "titulo": "Mesma manchete",
        "fonte": "G1",
        "url": "https://exemplo.test/1",
        "publicado_em": "2026-10-10T10:00:00+00:00",
        "ambito": "nacional",
        "tom": "neutro",
        "estados": [],
    }
    novas = [
        {**repetida, "titulo": f"Manchete {indice}", "url": f"https://exemplo.test/{indice}"}
        for indice in range(config.NOTICIAS_LIMITE + 5)
    ]
    monkeypatch.setattr(noticias, "buscar", lambda: [repetida, repetida, *novas])

    coletadas = noticias.coletar()

    assert len(coletadas["itens"]) == config.NOTICIAS_LIMITE
    assert len({item["titulo"] for item in coletadas["itens"]}) == config.NOTICIAS_LIMITE


def test_coletar_traz_beneficio_primeiro(monkeypatch):
    def manchetes():
        return [
            {
                "titulo": "Brent sobe",
                "fonte": "Reuters",
                "url": "https://exemplo.test/a",
                "publicado_em": "2026-10-11T09:00:00+00:00",
                "ambito": "exterior",
                "tom": "prejuizo",
                "estados": [],
            },
            {
                "titulo": "Queda chega aos postos",
                "fonte": "G1",
                "url": "https://exemplo.test/b",
                "publicado_em": "2026-10-09T09:00:00+00:00",
                "ambito": "nacional",
                "tom": "beneficio",
                "estados": [],
            },
        ]

    monkeypatch.setattr(noticias, "buscar", manchetes)

    assert [item["tom"] for item in noticias.coletar()["itens"]] == ["beneficio", "prejuizo"]


def test_coletar_nao_deixa_o_exterior_de_fora(monkeypatch):
    """O corte pelo limite não pode engolir o noticiário do exterior."""
    def manchetes():
        beneficios = [
            {
                "titulo": f"Queda do combustível {indice}",
                "fonte": "G1",
                "url": f"https://exemplo.test/{indice}",
                "publicado_em": "2026-10-10T10:00:00+00:00",
                "ambito": "nacional",
                "tom": "beneficio",
                "estados": [],
            }
            for indice in range(30)
        ]
        exterior = {
            "titulo": "Brent dispara com conflito no exterior",
            "fonte": "Reuters",
            "url": "https://exemplo.test/exterior",
            "publicado_em": "2026-10-01T10:00:00+00:00",
            "ambito": "exterior",
            "tom": "prejuizo",
            "estados": [],
        }
        return beneficios + [exterior]

    monkeypatch.setattr(noticias, "buscar", manchetes)

    itens = noticias.coletar()["itens"]

    assert len(itens) == config.NOTICIAS_LIMITE
    assert any(item["ambito"] == "exterior" for item in itens)


# ---------------------------------------------------------------- contrato do JSON
def test_payload_publica_as_noticias(bruto, monkeypatch):
    coletadas = {
        "coletado_em": "2026-10-12T21:00:00-03:00",
        "itens": [{"titulo": "Exemplo", "fonte": "G1", "url": "https://exemplo.test/1"}],
    }

    payload = transformacao.montar_payload(bruto, noticias=coletadas)

    assert payload["noticias"] == coletadas


def test_sem_noticias_novas_o_json_mantem_as_anteriores(bruto, tmp_path, monkeypatch):
    anterior = tmp_path / "dados.json"
    anterior.write_text(
        '{"noticias": {"coletado_em": "2026-10-11T10:00:00-03:00", "itens": [{"titulo": "Antiga"}]}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ARQUIVO_PROCESSADO", anterior)

    payload = transformacao.montar_payload(bruto)

    assert payload["noticias"]["itens"] == [{"titulo": "Antiga"}]


def test_sem_publicacao_anterior_o_json_publica_lista_vazia(bruto, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARQUIVO_PROCESSADO", tmp_path / "nao-existe.json")

    payload = transformacao.montar_payload(bruto)

    assert payload["noticias"] == {"coletado_em": "", "itens": []}
