# Arquitetura

## Fluxo

```
fonte pública ──(coleta.py)──► data/raw/            prova: bytes como vieram, nunca editados
                                   │
                                   ▼
                        (transformacao.py)──► data/processed/dados.json
                                   │                      │
                                   │                      ├──► site/data/dados.json ──► site estático
                                   │                      │
                                   └──────────────────────┴──► servidor.py (API opcional, mesmo JSON)
```

Uma única verdade: o JSON. O site estático e a API leem o **mesmo** arquivo, gerado pelo pipeline.

## Fonte de dados

| | |
|---|---|
| Página | `config.FONTE_URL` — série histórica de preços de combustíveis nos dados abertos da ANP |
| Arquivos | `config.FONTES_DADOS`: últimas 4 semanas de **gasolina/etanol** e de **diesel/GNV** |
| Formato | CSV com separador `;`, decimal com vírgula, data `DD/MM/AAAA`, UTF-8 com BOM (latin-1 como reserva) |
| Grão | uma linha por **revenda**/produto/data de coleta — não é resumo |

Colunas usadas: `Estado - Sigla`, `Municipio`, `Produto`, `Data da Coleta`, `Valor de Venda`,
`Revenda`, `CNPJ da Revenda`, `Unidade de Medida` (o resto é ignorado; o mapa está em
`transformacao.MAPA_COLUNAS`). Com dois arquivos, `fonte.arquivo_bruto` traz os dois nomes
separados por vírgula.

Este resumo lê **só** os arquivos da fonte principal — nome começado por data completa
(`AAAA-MM-DD`). A série mensal da fase 2 (`AAAA-MM-precos-*.csv`, insumo de `historico.py`)
fica de fora: sem essa separação o `dados.json` publicaria os 46 meses da série.

### Dois resumos, nesta ordem

1. **Revenda → município/mês** (`transformacao.resumir_estacoes`): cada revenda entra **uma vez**
   no mês, com a média das coletas dela. `postos_pesquisados` é a contagem de revendas distintas
   — a mesma loja pesquisada em três dias do mês é um posto, não três. Mínimo e máximo saem das
   coletas; `data_coleta` é a coleta mais recente do mês.
2. **Município → estado/mês** (`transformacao.resumir`): média ponderada pelo número de postos.
   Como cada revenda pertence a um município, o resultado é a **média das revendas** do estado
   no mês. O quadro do passo 1 vai publicado em `municipios[]` (`resumir_municipios`): é o mesmo
   cálculo, exposto — não uma segunda conta que possa divergir da primeira.

## Contrato do JSON

```json
{
  "gerado_em": "2026-10-12T16:08:00-03:00",
  "fonte": {
    "nome": "ANP — Levantamento de Preços de Combustíveis",
    "url": "https://.../",
    "arquivo_bruto": "2026-10-12-gasolina-etanol.csv, 2026-10-12-diesel-gnv.csv",
    "coletado_em": "2026-10-12T16:08:00-03:00"
  },
  "uf": "BR",
  "produtos": ["Diesel", "Diesel S10", "Etanol", "Gasolina", "Gasolina Aditivada"],
  "periodos": ["2026-09", "2026-10"],
  "registros": [
    {
      "produto": "Gasolina",
      "estado": "SC",
      "periodo": "2026-09",
      "municipios": 3,
      "postos_pesquisados": 412,
      "preco_minimo": 5.89,
      "preco_medio": 6.181,
      "preco_maximo": 6.58
    }
  ],
  "municipios": [
    {
      "produto": "Gasolina",
      "estado": "SC",
      "municipio": "FLORIANOPOLIS",
      "periodo": "2026-09",
      "postos_pesquisados": 158,
      "preco_minimo": 5.89,
      "preco_medio": 6.12,
      "preco_maximo": 6.49
    }
  ],
  "noticias": {
    "coletado_em": "2026-10-12T21:20:00-03:00",
    "itens": [
      {
        "titulo": "Governo zera tributos sobre a gasolina e publica MP",
        "fonte": "Agência Brasil",
        "url": "https://.../materia",
        "publicado_em": "2026-10-09T15:02:47+00:00",
        "ambito": "nacional",
        "tom": "beneficio",
        "estados": ["SP"]
      }
    ]
  }
}
```

| Campo | Significado |
|---|---|
| `gerado_em` | quando o pipeline rodou (fuso `America/Sao_Paulo`) |
| `fonte.*` | de onde o bruto veio e qual arquivo de `data/raw/` foi lido |
| `uf` | recorte padrão do projeto: `BR` (todos os estados); `--uf SC` estreita |
| `produtos`, `periodos` | listas ordenadas para montar os filtros do site |
| `registros[]` | uma linha por produto + estado + mês |
| `municipios[]` | uma linha por produto + **município** + mês: é o degrau que `registros` agrega, publicado para o site descer ao município sem recalcular. Mesmas colunas de preço, com `municipio` no lugar de `municipios` |
| `municipios` | quantos municípios entraram no grupo |
| `postos_pesquisados` | soma dos postos pesquisados no grupo |
| `preco_minimo` / `preco_maximo` | extremos do grupo |
| `preco_medio` | **média ponderada** pelo número de postos |
| `noticias.coletado_em` | quando as manchetes foram buscadas (`""` quando nunca houve coleta) |
| `noticias.itens[]` | `titulo`, `fonte`, `url`, `publicado_em`, `ambito` (`nacional`/`exterior`) e `tom` (`beneficio`/`prejuizo`/`neutro`) |

## O que o site mostra

| Bloco | O que traz |
|---|---|
| Recorte | filtros de produto, mês e estado, o botão **Pesquisar** (aplica a seleção) e o de limpar |
| Cartões | média do recorte, lugar mais barato, lugar mais caro e a amplitude: **nacional** quando o recorte é o país, **estadual** quando há UF escolhida |
| Destaques do bolso | **sempre** as três menores médias (troféu) e as três maiores (joinha para baixo) — de estados ou das cidades da UF escolhida |
| Ranking | todos os estados; com uma UF escolhida o ranking desce ao município daquela UF, comparando as cidades contra a média estadual |
| Tabela | produto × estado × mês, do mais barato ao mais caro: fundo verde no barato, vermelho no caro |
| Notícias | manchetes em "alivia o bolso" (verde), "pesa no bolso" (vermelho) e neutras, com o estado citado |
| Inteligência | segunda aba: score de evidência, teste de interdição × preço, correlações com p-valor, IPF por UF (com zona cega), anomalias de preço mínimo colado, alvos de fiscalização, interdições recentes e as limitações do artefato |

Decisões de tela: cores em variáveis `--cor-*` no `:root`; tema claro pelo `prefers-color-scheme`;
vidro e desfoque reduzidos em tela estreita (custo de pintura do `backdrop-filter`); foco visível que
não fica escondido atrás do topo fixo; alvos de toque de 44 px; tabela com `aria-sort` e barras do
ranking marcadas como decorativas — o preço aparece em texto para quem usa leitor de tela.

## Decisões que valem explicação

- **Média ponderada, não média de médias.** Amostras de cidades diferentes têm tamanhos diferentes;
  média simples daria peso igual a um município com 40 postos e a outro com 400 (Regras de Ouro, R14 e R20).
- **GNV fica fora desta fatia.** Ele sai em R$/m³ e os demais em R$/litro: somar unidades diferentes
  produziria uma média falsa. O corte é `config.UNIDADE_PADRAO`.
- **Gasolina aditivada não se mistura com a comum.** É outro produto, com outro preço: linha própria,
  em vez de inflar a média da gasolina.
- **A junção de arquivos acontece no grão da revenda** (`CHAVE_DA_REVENDA`). O arquivo de 4 semanas
  se sobrepõe ao do dia anterior; sem essa chave, o mesmo posto entraria duas vezes no preço do mês.
- **Município normalizado** (`normalizar_municipio`): "FLORIANÓPOLIS" e "FLORIANOPOLIS" são o mesmo
  município e não podem virar dois na contagem.
- **`data/raw/` não entra no git.** É a prova do que a fonte publicou; o `.gitignore` protege e o
  tratamento nunca escreve lá.
- **`data/processed/` e `site/data/` entram no git.** São o resultado publicado; o site é estático,
  então o JSON precisa estar no repositório para o site funcionar (GitHub Pages, por exemplo).
- **Site sem framework e sem CDN.** Abre por `file://`, funciona offline e não depende de terceiros.
- **Os ícones são desenhados no próprio projeto** (sprite SVG inline). Sem biblioteca de terceiros:
  nada de licença para creditar, nada para baixar e nada de ícone "quebrado" quando o site abre offline.
- **Notícia entra só com título, veículo, data e link.** O texto é de quem publicou; o site leva o
  leitor até lá (Lei 9.610/98, art. 46, III). Não se republica matéria nem imagem de terceiro.
- **A leitura do tom da manchete é automática e assumida como pista.** "Não repassam a queda" tem
  palavra de queda, mas pesa no bolso — por isso a frase tem peso próprio e o site avisa que o rótulo
  é heurístico e que a conferência é no veículo original.
- **Falha de rede não apaga notícia.** Sem manchetes novas, o JSON mantém as da execução anterior.
- **O site não fala com a rede além do próprio arquivo.** Os feeds são lidos pelo pipeline: nada de
  CORS, nada de conteúdo de terceiro carregado no navegador do visitante.
- **Servidor opcional em FastAPI.** Serve o mesmo JSON; não guarda estado nem cria uma segunda cópia.

## Fase 2 — fiscalização × preço

Segunda camada do projeto: cruzar o preço com a **ação de fiscalização** da ANP. Publicada em
`site/data/inteligencia.json`, exibida na aba Inteligência do site e servida pelas rotas
`/inteligencia/*` do `servidor.py`.

### Fontes

| | |
|---|---|
| Fiscalização | 2 XLSX do painel dinâmico (`config.FISCALIZACAO_URLS`): uma linha por documento, com UF, município, CNPJ, segmento, procedimento e data (1998 em diante) |
| Revendedores | API pública `config.REVENDEDORES_URL`: CNPJ, endereço, bandeira, coordenada. Dá o **denominador** dos indicadores (postos por UF) |
| Série mensal de preço | arquivos mensais de gasolina/etanol da mesma série histórica (`historico.py`), grão de revenda |

### Módulos

| Módulo | Papel |
|---|---|
| `fiscalizacao.py` | XLSX → quadro normalizado; resumos por UF, UF × mês e município; lista de interditados |
| `revendedores.py` | cliente da API com espera progressiva (a API responde 429 em sequência) e retomada por UF |
| `historico.py` | descoberta e leitura dos arquivos mensais; agregação UF × mês e município × mês |
| `analise.py` | C1 a C7, correlação com p-valor, anomalia, score fiscal, score de evidência, montagem do JSON |
| `scripts/inteligencia.py` | roda a análise e publica o JSON |
| `scripts/loop_noturno.py` | loop de evidência: gira um parâmetro, mede o score, decide ACEITO/REJEITADO |
| `scripts/relatorio.py` | gera `RELATORIO_INTELIGENCIA.md` a partir do JSON publicado |

### Contrato do JSON de inteligência

```json
{
  "gerado_em": "2026-10-12T22:16:00-03:00",
  "periodos": {"fiscalizacao": "1998-01 a 2026-09", "precos_uf": "2023-01 a 2026-10",
               "correlacao_desde": "2023-01", "janela_ipf_meses": 12},
  "cobertura": {"acoes_normalizadas": 645283, "acoes_revenda": 469991,
                "interdicoes_revenda": 15162, "postos_ativos_api": 45762, "ufs": 27,
                "municipios_com_preco": 461, "meses_de_preco": 45,
                "municipios_com_fiscalizacao": 2756},
  "pesos_score_fiscal": {"dispersao": 0.35, "fiscalizacao": 0.25, "interdicao": 0.2, "variacao": 0.2},
  "parametros": {"desde": "2023-01", "janela_ipf": 12, "limite_anomalia": 0.02,
                 "minimo_postos": 3, "atrasos": [1, 2], "metodo": "pearson"},
  "score_evidencia": {"score": 0.0579, "evidencias": 9, "detalhes": []},
  "limitacoes": ["..."],
  "ufs": [{"uf": "MA", "postos": 1793, "acoes_12m": 521, "acoes_total": 8562,
           "infracoes_12m": 165, "interdicoes_12m": 14, "ipf": 290.57,
           "ipf_acumulado": 4775.24, "taxa_interdicao": 2.69, "dispersao_cv": 0.0596,
           "preco_medio": 5.9112, "periodo_inicio": "2025-10", "periodo_fim": "2026-09",
           "zona_cega": true}],
  "correlacoes": [{"nome": "fiscalizacao_x_preco_pooled", "metodo": "pearson", "r": -0.1872,
                   "p": 0.0, "n": 1090, "estabilidade": 0.8902, "leitura": "..."}],
  "anomalias": [{"uf": "MS", "municipio": "CORUMBA", "meses": 46, "meses_colados": 46,
                 "taxa_colada": 1.0, "postos": 7.5, "folga_pct": 0.779,
                 "preco_minimo": 5.54, "preco_medio": 6.8113, "preco_maximo": 7.22,
                 "amplitude": 1.68, "ultimo_periodo": "2026-10"}],
  "alvos": [{"uf": "SP", "municipio": "BARUERI", "score": 0.7218, "comp_dispersao": 1.0,
             "comp_fiscalizacao": 0.8284, "comp_interdicao": 0.0033, "comp_variacao": 0.8202}],
  "interditos": [{"uf": "CE", "municipio": "PINDORETAMA", "cnpj": "44695202000170",
                  "interdicoes": 2, "primeira": 1788393600000, "ultima": 1788393600000}],
  "interdicao_preco": {"n": 187, "efeito": -0.0001, "efeito_pct": -0.001,
                       "delta_bruto_medio": 0.1103, "delta_controle_medio": 0.1104,
                       "p": 0.772782, "estatistica": 8575.0, "leitura": "...", "exemplos": []},
  "loop": {"baseline": "baseline.json", "log": "log_noturno.md", "score_no_loop": 0.0579}
}
```

`interditos[].primeira/.ultima` saem como epoch em milissegundos (efeito do `to_json` do pandas):
quem exibe formata.

### Indicadores

| Nome | Como é calculado | Cuidado |
|---|---|---|
| IPF | ações na revenda nos últimos 12 meses ÷ postos ativos × 1.000, por UF | O acumulado desde 1998 também vai no JSON, mas usa denominador de hoje: é contexto, não indicador |
| TI | autos de interdição ÷ ações × 100, por UF | Interdição é ato administrativo, não condenação |
| Anomalia de mínimo colado | (média − mínimo) ÷ média < 2% no município, com 3 postos ou mais | O sinal é a **recorrência** em meses, não um mês solto |
| C4 | fiscalização mensal × preço mensal, no painel UF × mês | Publica *pooled* e *intra-UF* (sem a média da própria UF) — sem isso a diferença de nível entre UFs vira correlação falsa |
| C6 | preço antes × depois do auto de interdição | **Diferença em diferenças** contra os outros municípios da mesma UF: sem controle, o resultado mede a inflação do período, não o efeito da ação |
| Score fiscal (C7) | dispersão, fiscalização por posto (invertida), interdição e desvio da mediana da UF, normalizados 0–1 e somados por peso | É ordenação para triagem, não probabilidade |
| `score_evidencia` | média de (1 − p) × \|r\| × estabilidade sobre as correlações válidas | Evidência fraca **puxa o score para baixo**: é o incentivo do loop |

### Decisões que valem explicação (fase 2)

- **Toda correlação publicada sai com r, p e n.** Sem os três não é achado, é palpite — e o
  `leitura()` já escreve a frase pronta, para o site não inventar interpretação própria.
- **Correlação sem amostra mínima não vira número.** Abaixo de 8 observações o JSON publica
  `r: null` em vez de um coeficiente frágil.
- **Estabilidade se mede de dois jeitos.** Série temporal: primeira metade contra a segunda.
  Corte transversal (UF × UF): a amostra é partida em duas. Sinal que inverte zera a estabilidade.
- **`dayfirst` não se adivinha: o formato é detectado.** `03/04/2024` é 3 de abril no Brasil e
  4 de março nos EUA, e as duas leituras devolvem data válida — o erro passaria calado. Pior:
  `dayfirst=True` junto de `format="mixed"` inverte ISO ambíguo (`2024-04-03` vira 4 de março).
  Então ISO é lido como ISO, `dd/mm/aaaa` como `dd/mm/aaaa`, e o resto vira nulo.
- **As limitações vão dentro do JSON**, geradas a partir da própria cobertura. Quem consome o
  arquivo recebe a ressalva junto do número, não num README que ninguém abre.
- **O que o loop aceita não é opinião.** Ganho de 5% no `score_evidencia` ou nada: os parâmetros
  de hoje passaram por 6 variações e nenhuma superou o corte (`log_noturno.md`).
- **Nenhum dado derivado é escrito no bruto.** Planilhas, JSON da API e CSV mensais são prova
  (fora do git); o tratamento lê de lá e grava só em `data/processed/` e no site.

## Pastas

| Pasta | O que é |
|---|---|
| `src/combustivelbr/` | o pacote: `config`, `coleta`, `transformacao`, `noticias`, `servidor`, `cli`, `fiscalizacao`, `revendedores`, `historico`, `analise` |
| `data/raw/` | bruto baixado (fora do git) |
| `data/processed/` | JSON tratado (versionado) |
| `site/` | HTML/CSS/JS estático + `site/data/dados.json` e `site/data/inteligencia.json` |
| `tests/` | testes (pytest) + `fixtures/` |
| `docs/` | este documento e as Regras de Ouro |
| `notebooks/` | rascunho e exploração (Regras de Ouro, R23) |
| `scripts/` | `inteligencia.py`, `loop_noturno.py`, `relatorio.py` e auxiliares |

Na raiz, três arquivos da fase 2: `baseline.json` (melhores parâmetros medidos), `log_noturno.md`
(um bloco por ciclo do loop) e `RELATORIO_INTELIGENCIA.md` (gerado por `scripts/relatorio.py`).

## A definir quando o trabalho for especificado

1. **Série histórica.** Resolvido na fase 2 (`historico.py` lê a página da fonte e extrai o mês do
   nome, que é irregular: `01-dados-abertos-precos-gasolina-etanol.csv`, `06-...-2026-06-...`, e em
   2026 um arquivo sem extensão). O que falta é ampliar a janela: hoje a série mensal começa em 2023.
2. **Recorte** de UFs: hoje é o país inteiro (`config.UF_PADRAO = "BR"`); `--uf` ou a variável
   `COMBUSTIVELBR_UF` estreitam para uma sigla. Produtos já mapeados em `transformacao.PRODUTOS_ANP`.
3. **Periodicidade** da coleta (cron/tarefa agendada).
4. **Multas.** O painel de multas do `dados.gov.br` não tem arquivo baixável (página só renderiza
   em JavaScript e a API responde 401). Enquanto isso, valor de multa não entra em conta nenhuma.
5. **Mapa dos postos.** A API de revendedores devolve latitude e longitude; falta desenhar.
