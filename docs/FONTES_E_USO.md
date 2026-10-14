# Fontes e condições de uso

Este projeto baixa dados públicos da ANP, trata e publica uma base derivada (JSON) num site
estático. Esta página registra o que as regras oficiais exigem de nós e como estamos cumprindo —
para que qualquer pessoa que reutilize o projeto saiba o que pode e o que não pode fazer.

## De onde vêm os dados

| Conjunto | Página de origem | O que lemos |
|---|---|---|
| Levantamento de Preços de Combustíveis | `gov.br/anp` → dados abertos → série histórica de preços | CSV por revenda (últimas 4 semanas e arquivos mensais) |
| Ações de Fiscalização do Abastecimento | `gov.br/anp` → dados abertos → ações de fiscalização | XLSX do painel (uma linha por procedimento) |
| Revendedores (cadastro) | `revendedoresapi.anp.gov.br/v1/combustivel` | JSON por UF — é o denominador dos indicadores |
| Manchetes | feeds RSS públicos (Agência Brasil, Agência Gov, Senado e agregador) | título, veículo, data e link |

## O que a norma exige e o que fazemos

| Regra | Obrigação | Como cumprimos |
|---|---|---|
| Decreto nº 8.777/2016, art. 2º, III e art. 3º, IV | Dados abertos podem ser usados, cruzados e redistribuídos, **creditando a fonte** | O rodapé do site e o campo `fonte` de cada JSON trazem nome, endereço e arquivo lido |
| Termo de Uso do portal da ANP | Reprodução **sem fins lucrativos**, com **citação clara e visível**, de preferência com link | Citação com link no rodapé; o site e o repositório não vendem serviço |
| Termo de Uso do portal da ANP | Proibido usar a **marca/logo da ANP** | Usamos identidade visual própria; nenhuma marca de terceiro é reproduzida |
| Publicação das ações de fiscalização (SFI) | Dados **preliminares**: o autuado tem contraditório e ampla defesa e só o julgamento definitivo comprova a infração | Aviso na aba Inteligência, na lista de interdições e no campo `limitacoes` do JSON |
| Painéis dinâmicos da ANP | O dado pode mudar sem aviso | Todo número publicado sai com mês de referência e data de coleta |
| Decreto nº 8.777/2016, art. 3º, III | Descrição suficiente para o leitor entender ressalvas | O JSON carrega as limitações junto do número; o site as exibe |
| `robots.txt` da ANP | Acesso a robôs permitido nas áreas públicas | Requisições com `User-Agent` identificado e sem varredura agressiva |

## Licença dos nossos artefatos

- **Código**: MIT (veja [LICENSE](../LICENSE)).
- **Base derivada** (JSON, resumos e indicadores): **CC BY 4.0**, com atribuição à ANP como fonte
  dos dados originais e a este projeto pelo tratamento.

Esta é a leitura mais permissiva e é o que o Decreto nº 8.777/2016 autoriza para bases publicadas em
formato aberto. Se você reutilizar a base, mantenha a atribuição e a data de coleta.

## Ambiguidades que encontramos (e como decidimos)

1. **Não há licença explícita nos dados abertos da ANP.** Nem a página de dados abertos, nem o
   inventário de dados, nem o Plano de Dados Abertos 2026–2028 declaram CC-BY, ODbL ou qualquer
   licença para os conjuntos. Decidimos pela leitura do Decreto nº 8.777/2016, que é o que rege
   dados abertos do Executivo federal e o que a própria ANP invoca ao publicar a série de preços.
2. **O rodapé do portal declara CC BY-ND 3.0** (Atribuição, **Sem Derivações**), o que em tese
   proibiria uma base derivada como esta. O rodapé é padrão de modelo do `gov.br` (aparece igual em
   páginas de outros órgãos) e conflita com o próprio Decreto nº 8.777/2016; consideramos que ele se
   aplica ao *conteúdo editorial* das páginas, não aos *conjuntos de dados* publicados como abertos.
   Registramos a contradição em vez de escondê-la.
3. **Há um termo em PDF (2021) que proíbe robôs e varredura** e é mais restritivo que o termo em
   HTML. O escopo declarado dele são os *serviços* da ANP que lidam com informações pessoais, e não
   os arquivos da página de dados abertos. Mesmo assim, nosso coletor é conservador: baixa poucos
   arquivos da fonte oficial, com `User-Agent` próprio, e não faz varredura em massa das APIs.
4. **"Sem fins lucrativos"** no termo em HTML: o site é gratuito e não vende serviço. Qualquer
   monetização (anúncio, patrocínio, venda de dado tratado) precisa ser reavaliada à luz dessa
   cláusula antes de acontecer.
5. **A API "Do Poço ao Posto" exige autenticação** e não publica termos de uso, então não a usamos.
   A API de revendedores é anônima e é a única que consumimos.

## O que NÃO fazemos

- Não usamos a marca ou o logotipo da ANP.
- Não apresentamos dado preliminar de fiscalização como condenação definitiva.
- Não atribuímos à ANP erro de leitura, de cálculo ou de agregação nosso.
- Não republicamos texto de terceiros: das manchetes guardamos apenas título, veículo, data e link
  (Lei nº 9.610/1998, art. 46, III).
- Não vendemos serviço com base no conteúdo da ANP.

Última verificação das regras: 14/10/2026.
