# Loop noturno — fase 2 (fiscalização × preço)

Rodada de 12/10/2026 22:16. Ganho mínimo para aceitar: 5%; hipótese abandonada após 3 rejeições.

Ponto de partida: score **0.0579**, 9 correlações, 4 com p < 0.05.

[22:16] Ciclo 1 — Hipótese: janela de correlação (começar a correlação em 2024-01)
        Métrica antes: 0.0579 | Métrica depois: 0.0497 | Decisão: REJEITADO
        Observação: 9 correlações, 2 com p < 0.05; piora de 14.2% sobre o melhor até agora

[22:16] Ciclo 2 — Hipótese: janela do IPF (contar ações dos últimos 24 meses)
        Métrica antes: 0.0579 | Métrica depois: 0.0593 | Decisão: REJEITADO
        Observação: 9 correlações, 4 com p < 0.05; melhora de 2.4%, abaixo dos 5% exigidos

[22:16] Ciclo 3 — Hipótese: limiar de anomalia (mínimo colado passa a ser folga < 1.0%)
        Métrica antes: 0.0579 | Métrica depois: 0.0579 | Decisão: SEM EFEITO NA MÉTRICA
        Observação: 9 correlações, 4 com p < 0.05; o score de evidência mede correlação, e este parâmetro só muda a lista de alvos e anomalias publicada — não conta como rejeição

[22:16] Ciclo 4 — Hipótese: porte mínimo do município (exigir 5 postos por município)
        Métrica antes: 0.0579 | Métrica depois: 0.0579 | Decisão: SEM EFEITO NA MÉTRICA
        Observação: 9 correlações, 4 com p < 0.05; o score de evidência mede correlação, e este parâmetro só muda a lista de alvos e anomalias publicada — não conta como rejeição

[22:16] Ciclo 5 — Hipótese: memória da fiscalização (lags (1, 2, 3) entre ação e preço)
        Métrica antes: 0.0579 | Métrica depois: 0.0604 | Decisão: REJEITADO
        Observação: 10 correlações, 5 com p < 0.05; melhora de 4.3%, abaixo dos 5% exigidos

[22:16] Ciclo 6 — Hipótese: método da correlação (usar Spearman na evidência principal)
        Métrica antes: 0.0579 | Métrica depois: 0.0563 | Decisão: REJEITADO
        Observação: 9 correlações, 4 com p < 0.05; piora de 2.8% sobre o melhor até agora


**Parada**: score estabilizado (duas variações abaixo de 5%) com evidência suficiente.

**Parâmetros vencedores**: `{"desde": "2023-01", "janela_ipf": 12, "limite_anomalia": 0.02, "minimo_postos": 3, "atrasos": [1, 2], "pesos": {"dispersao": 0.35, "fiscalizacao": 0.25, "interdicao": 0.2, "variacao": 0.2}, "metodo": "pearson"}`

Score publicado: **0.0579** (9 correlações, 4 com p < 0.05).
