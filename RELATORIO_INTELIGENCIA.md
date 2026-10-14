# Relatório de Inteligência — combustivelBR (fase 2)

Gerado em 14/10/2026 13:25 a partir de `site/data/inteligencia.json` (dados publicados em 2026-10-14). Preços e fiscalização são públicos; o recorte e as limitações estão no fim.

## Base usada

- Fiscalização: 469.991 ações na revenda (645.283 normalizadas em todos os segmentos), 15.162 autos de interdição.
- Postos ativos: 45.762 em 27 UFs (API de revendedores da ANP).
- Preço: 45 meses, 461 municípios com dado, 2.756 com fiscalização registrada.
- Janela da correlação: desde 2023-01; IPF em 12 meses; método pearson.

**Score de evidência**: 0,0579 em 9 correlações (média de (1 − p) × |r| × estabilidade). Score baixo quer dizer que a evidência é fraca — não que o achado é falso.

## 1. Top 5 anomalias (preço mínimo colado na média)

Municípios em que o menor preço da amostra fica a menos de 2.0% da média, em muitos meses seguidos. Recorrência é o sinal: mercado disputado não repete isso por 40 meses.

| município | recorrência | folga média | postos | preço médio | mín→máx | último mês |
|---|---|---|---|---|---|---|
| MS CORUMBA | 46 de 46 meses | 0,78% | 7,5 | R$ 6,8113 | 5,54 → 7,22 | 2026-10 |
| AM TEFE | 15 de 15 meses | 0,86% | 7,0 | R$ 7,5027 | 6,87 → 7,76 | 2024-06 |
| SE ITABAIANA | 44 de 45 meses | 0,27% | 8,0 | R$ 6,1631 | 4,95 → 7,24 | 2026-10 |
| PE SALGUEIRO | 38 de 39 meses | 0,50% | 8,0 | R$ 6,5653 | 5,68 → 7,22 | 2026-10 |
| MG CARATINGA | 38 de 39 meses | 0,99% | 7,0 | R$ 6,0070 | 5,19 → 6,79 | 2026-10 |

## 2. Top 5 alvos para fiscalização

Score composto (0 a 1) por dispersão de preço no município, fiscalização por posto (invertida), histórico de interdição e desvio da mediana da UF. Pesos: dispersao 0.35, fiscalizacao 0.25, interdicao 0.2, variacao 0.2.

| município | score | postos | dispersão | desvio da UF | ações | interdições |
|---|---|---|---|---|---|---|
| SP BARUERI | 0,7218 | 19 | 0,139 | 12,9% | 163 | 1 |
| SP GUARUJA | 0,5709 | 11 | 0,120 | 7,2% | 157 | 2 |
| SP SAO PAULO | 0,5259 | 274 | 0,094 | 0,8% | 9.351 | 306 |
| SP TATUI | 0,4931 | 9 | 0,075 | 5,3% | 17 | 0 |
| RS BAGE | 0,4850 | 12 | 0,021 | 15,7% | 34 | 0 |

## 3. UFs em zona cega

Quartil de menor IPF (ações por 1.000 postos) com dispersão de preço acima da mediana do país. Fiscaliza pouco e o preço varia muito entre postos da mesma UF.

| UF | IPF (janela) | IPF acumulado | ações na janela | dispersão (CV) | preço médio |
|---|---|---|---|---|---|
| MA | 290,6 | 4.775,2 | 521 | 0,0596 | R$ 5,911 |
| AC | 239,6 | 7.072,9 | 46 | 0,0437 | R$ 7,143 |
| PR | 278,1 | 6.454,3 | 822 | 0,0434 | R$ 6,155 |

## 4. O que se sustenta (p < 0,05)

| correlação | r | p | n | estabilidade | leitura |
|---|---|---|---|---|---|
| fiscalizacao_x_preco_pooled | -0,1872 | 0,0000 | 1.090 | 0,890 | andam em direções opostas, associação fraca (r=-0.187, p=0.000) |
| fiscalizacao_x_preco_pooled_spearman | -0,1568 | 0,0000 | 1.090 | 0,890 | andam em direções opostas, associação fraca (r=-0.157, p=0.000) |
| fiscalizacao_x_preco_intra_uf | -0,0638 | 0,0351 | 1.090 | 0,890 | andam em direções opostas, associação fraca (r=-0.064, p=0.035) |
| fiscalizacao_lag2_x_preco_intra_uf | -0,0676 | 0,0296 | 1.036 | 0,890 | andam em direções opostas, associação fraca (r=-0.068, p=0.030) |

Outras 5 correlações testadas não passaram do corte e ficam registradas no JSON — publicar só o que deu certo é como escolher o resultado depois de ver o jogo.

### Interdição × preço

Diferença em diferenças contra os outros municípios da mesma UF, n = 187: ação bruta 0,1103 na média, controle 0,1104, efeito próprio -0,0001 (p = 0,7728). Leitura: sem diferença detectável contra o controle. O ganho bruto de preço depois da interdição é a tendência do período inteiro, não o efeito da ação.

## 5. Hipóteses levantadas

- Onde há pouca ação por posto e preço disperso (zona cega), o mercado pode estar subfiscalizado: MA, AC, PR.
- Municípios com mínimo colado na média por dezenas de meses se comportam como mercado sem disputa de preço; pode ser uma revenda só na prática, tabela comum ou liderança de preço.
- A correlação intra-UF entre fiscalização e preço é negativa e pequena: mais ação aparece onde o preço é menor, o que é compatível com fiscalização reagir a denúncia, e não com fiscalização derrubar preço.
- A ação de interdição não move o preço do município acima do que move o resto da UF na mesma janela.

### O que o loop noturno testou

| # | hipótese | variação testada | score | decisão |
|---|---|---|---|---|
| 1 | janela de correlação | começar a correlação em 2024-01 | 0,0579 → 0,0497 | REJEITADO |
| 2 | janela do IPF | contar ações dos últimos 24 meses | 0,0579 → 0,0593 | REJEITADO |
| 3 | limiar de anomalia | mínimo colado passa a ser folga < 1.0% | 0,0579 → 0,0579 | SEM EFEITO NA MÉTRICA |
| 4 | porte mínimo do município | exigir 5 postos por município | 0,0579 → 0,0579 | SEM EFEITO NA MÉTRICA |
| 5 | memória da fiscalização | lags (1, 2, 3) entre ação e preço | 0,0579 → 0,0604 | REJEITADO |
| 6 | método da correlação | usar Spearman na evidência principal | 0,0579 → 0,0563 | REJEITADO |

Parada do loop: score estabilizado (duas variações abaixo de 5%) com evidência suficiente. 

## 6. O que um fiscal faria diferente com isso

1. Começaria pelos alvos da seção 2: dispersão alta e pouca ação por posto é onde o mesmo produto tem preço muito diferente na mesma cidade.
2. Olharia as anomalias da seção 1 em campo: preço igual por 40 meses não se explica sozinho, mas se explica no balcão.
3. Nas zonas cegas, usaria o IPF como lista de prioridade de agenda — o indicador mede esforço por posto, não irregularidade encontrada.
4. Não usaria este relatório como prova: nenhuma linha aqui é processo, é triagem.

## 7. Limitações (leia antes de citar qualquer número)

- Preço cobre 461 municípios em 45 meses, não o país inteiro: os arquivos mensais da ANP são uma amostra rotativa de municípios, então média nacional aqui não é censo.
- A fiscalização é acumulada (1998 em diante) e o denominador de postos ativos é de hoje: o IPF compara estoque antigo com estoque atual e favorece UFs com histórico longo.
- O campo statusSIGAF da API de revendedores vem vazio em 100% dos registros: não há como separar posto ativo de irregular por ali.
- As multas do dados.gov.br não têm arquivo baixável (página só renderiza em JavaScript e a API responde 401): valor de multa não entra em nenhum cálculo.
- Correlação não é causa. Fiscalização acha o que procura: uma UF com mais ações pode ser a que mais fiscaliza, não a que mais erra.
- Interdição e preço foram comparados por diferença em diferenças contra os outros municípios da mesma UF; município com uma única revenda não tem controle próprio.
- A série de preço publicada é mensal, então o IPF é cruzado com a dispersão do mês — não com variação semanal, que não existe nesta base.
- Zonas cegas usam ações por posto ativo; fiscalização por km² não entra porque o projeto não carrega área de UF.
- O peso de 'taxa de denúncias' do score de alvo virou histórico de interdição do município: não há base pública de denúncias por município.
- Auto de interdição é ato administrativo, não condenação definitiva: o autuado tem direito ao contraditório e à ampla defesa, e só o julgamento definitivo do processo comprova a infração — pode ser revertido em recurso.

---

Reproduzir: `python scripts/inteligencia.py` (publica o JSON) e `python scripts/loop_noturno.py` (roda o loop de evidência). Este arquivo é gerado por `python scripts/relatorio.py` — não edite à mão.
