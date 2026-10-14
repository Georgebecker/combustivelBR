/* Lê data/dados.json (contrato em docs/ARQUITETURA.md) e monta a tela.
   Sem dependência externa: o site tem de funcionar aberto direto no navegador, offline. */
'use strict';

const CAMINHO_DADOS = 'data/dados.json';
const NS_SVG = 'http://www.w3.org/2000/svg';
const NS_XLINK = 'http://www.w3.org/1999/xlink';

const moeda = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const moedaPrecisa = new Intl.NumberFormat('pt-BR', {
	style: 'currency', currency: 'BRL', minimumFractionDigits: 2, maximumFractionDigits: 3
});
const inteiro = new Intl.NumberFormat('pt-BR');
const momento = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
const soData = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });
const soMes = new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric' });
const percentual = new Intl.NumberFormat('pt-BR', {
	style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1
});
// As datas do artefato de inteligência vêm como epoch em milissegundos da meia-noite UTC:
// formatar no fuso local devolveria o dia anterior, então a leitura é em UTC.
const soDataUTC = new Intl.DateTimeFormat('pt-BR', {
	day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC'
});

const estado = {
	dados: null,
	noticias: { coletado_em: '', itens: [] },
	erro: '',
	// `menus` é o que está escolhido nas listas; `filtro` é o que está aplicado na tela.
	// A separação existe porque a tela tem o botão Pesquisar: mexer na lista não muda nada
	// até ele ser acionado.
	menus: { produto: '', periodo: '', uf: '' },
	filtro: { produto: '', periodo: '', uf: '' },
	ordem: { campo: 'preco_medio', asc: true }, // o mais barato primeiro, como pede a tela
	inteligencia: null,
	ordemIpf: { campo: 'ipf', asc: false } // IPF maior primeiro
};

document.addEventListener('DOMContentLoaded', iniciar);

/* ---------------------------------------------------------------- utilidades */
function el(tag, props, filhos) {
	const no = document.createElement(tag);
	Object.entries(props || {}).forEach(function (par) {
		const chave = par[0], valor = par[1];
		if (valor === null || valor === undefined) return;
		if (chave === 'class') no.className = valor;
		else if (chave === 'texto') no.textContent = valor;
		else if (chave === 'estilo') no.style.cssText = valor;
		else if (chave.indexOf('--') === 0) no.style.setProperty(chave, valor);
		else if (chave === 'aoClicar') no.addEventListener('click', valor);
		else no.setAttribute(chave, valor);
	});
	[].concat(filhos || []).forEach(function (filho) {
		if (filho) no.appendChild(filho);
	});
	return no;
}

function icone(nome, classe) {
	const svg = document.createElementNS(NS_SVG, 'svg');
	svg.setAttribute('class', classe || 'icone');
	svg.setAttribute('aria-hidden', 'true');
	svg.setAttribute('focusable', 'false');
	const uso = document.createElementNS(NS_SVG, 'use');
	uso.setAttributeNS(NS_XLINK, 'xlink:href', '#' + nome);
	uso.setAttribute('href', '#' + nome);
	svg.appendChild(uso);
	return svg;
}

function trocar(destino, conteudo) {
	destino.textContent = '';
	[].concat(conteudo || []).forEach(function (no) { if (no) destino.appendChild(no); });
}

function registros() {
	return estado.dados && Array.isArray(estado.dados.registros) ? estado.dados.registros : [];
}

function mediaPonderada(linhas) {
	const postos = linhas.reduce(function (soma, linha) { return soma + (linha.postos_pesquisados || 0); }, 0);
	if (!postos) return null;
	const soma = linhas.reduce(function (total, linha) {
		return total + (linha.preco_medio || 0) * (linha.postos_pesquisados || 0);
	}, 0);
	return soma / postos;
}

function variacao(preco, base) {
	if (!base || preco === null || preco === undefined) return null;
	return (preco - base) / base;
}

function textoVariacao(fracao) {
	if (fracao === null) return '—';
	return (fracao > 0 ? '+' : '') + percentual.format(fracao);
}

function delta(fracao, classeExtra) {
	const classe = fracao > 0.0005 ? 'delta--ruim' : (fracao < -0.0005 ? 'delta--bom' : 'delta--neutro');
	const nome = fracao > 0.0005 ? 'ico-seta-cima' : (fracao < -0.0005 ? 'ico-seta-baixo' : 'ico-info');
	return el('span', { class: 'delta ' + classe + (classeExtra ? ' ' + classeExtra : '') },
		[icone(nome), el('span', { texto: textoVariacao(fracao) })]);
}

/* ---------------------------------------------------------------- carga */
async function iniciar() {
	mostrarEsqueleto();
	ligarAbas();
	iniciarInteligencia();
	try {
		const resposta = await fetch(CAMINHO_DADOS, { cache: 'no-store' });
		if (!resposta.ok) throw new Error('HTTP ' + resposta.status);
		estado.dados = await resposta.json();
		estado.noticias = estado.dados.noticias && Array.isArray(estado.dados.noticias.itens)
			? estado.dados.noticias : { coletado_em: '', itens: [] };
		ajustarFiltroInicial();
		ligarEventos();
		desenhar();
	} catch (erro) {
		// Abrindo por file:// alguns navegadores bloqueiam a leitura do JSON: diga o caminho
		const dica = location.protocol === 'file:'
			? ' Abrindo direto do arquivo, o navegador pode barrar a leitura do JSON: use o servir.ps1 ou publique a pasta site/.'
			: '';
		estado.erro = erro.message + dica;
		mostrarErro(estado.erro);
	}
}

function ajustarFiltroInicial() {
	const produtos = estado.dados.produtos || [];
	const periodos = estado.dados.periodos || [];
	const inicial = {
		produto: produtos.indexOf('Gasolina') >= 0 ? 'Gasolina' : (produtos[0] || ''),
		periodo: periodos.length ? periodos[periodos.length - 1] : '',
		uf: ''
	};
	estado.menus = Object.assign({}, inicial);
	estado.filtro = Object.assign({}, inicial);
}

function ligarEventos() {
	campo('filtro-produto', 'produto');
	campo('filtro-periodo', 'periodo');
	campo('filtro-estado', 'uf');

	const pesquisar = document.getElementById('pesquisar');
	if (pesquisar) {
		pesquisar.addEventListener('click', function () { aplicarPesquisa(); });
	}

	const limpar = document.getElementById('limpar');
	if (limpar) {
		limpar.addEventListener('click', function () {
			ajustarFiltroInicial();
			desenhar();
		});
	}

	document.querySelectorAll('#tabela thead th[data-campo] button').forEach(function (botao) {
		botao.addEventListener('click', function () {
			const campo = botao.parentElement.getAttribute('data-campo');
			if (estado.ordem.campo === campo) estado.ordem.asc = !estado.ordem.asc;
			else estado.ordem = { campo: campo, asc: true };
			desenharTabela();
		});
	});
}

function campo(id, chave) {
	const select = document.getElementById(id);
	if (!select) return;
	select.addEventListener('change', function () {
		estado.menus[chave] = select.value;
		marcarPendente();
	});
	// Enter aplica sem tirar a mão do teclado
	select.addEventListener('keydown', function (evento) {
		if (evento.key === 'Enter') {
			evento.preventDefault();
			aplicarPesquisa();
		}
	});
}

function temPendencia() {
	return estado.menus.produto !== estado.filtro.produto
		|| estado.menus.periodo !== estado.filtro.periodo
		|| estado.menus.uf !== estado.filtro.uf;
}

function marcarPendente() {
	if (temPendencia()) anunciar('Seleção alterada: clique em Pesquisar para aplicar.');
	else anunciar('Recorte aplicado.');
}

/* O botão Pesquisar é o que aplica a lista na tela — e é o que troca o escopo: com uma UF
   escolhida o recorte desce ao município (média estadual, destaques e ranking por cidade). */
function aplicarPesquisa() {
	estado.filtro = Object.assign({}, estado.menus);
	desenhar();
}

/* ---------------------------------------------------------------- desenho */
function desenhar() {
	preencherFiltros();
	desenharKpis();
	desenharDestaques();
	desenharRanking();
	desenharTabela();
	desenharNoticias();
	mostrarProcedencia();
}

function preencherFiltros() {
	preencherSelect('filtro-produto', estado.dados.produtos || [], 'Todos os produtos', estado.filtro.produto);
	preencherSelect('filtro-periodo', estado.dados.periodos || [], 'Todos os meses', estado.filtro.periodo);
	const ufs = [];
	registros().forEach(function (linha) { if (ufs.indexOf(linha.estado) < 0) ufs.push(linha.estado); });
	preencherSelect('filtro-estado', ufs.sort(), 'Todos os estados', estado.filtro.uf);
}

function preencherSelect(id, valores, textoVazio, escolhido) {
	const select = document.getElementById(id);
	if (!select) return;
	trocar(select, [el('option', { value: '', texto: textoVazio })].concat(
		valores.map(function (valor) { return el('option', { value: valor, texto: valor }); })
	));
	select.value = escolhido || '';
}

function selecionados() {
	const filtro = estado.filtro;
	return registros().filter(function (linha) {
		return (!filtro.produto || linha.produto === filtro.produto)
			&& (!filtro.periodo || linha.periodo === filtro.periodo)
			&& (!filtro.uf || linha.estado === filtro.uf);
	});
}

function municipios() {
	return estado.dados.municipios || [];
}

/* Um "lugar" é o que a tela compara: o estado quando o recorte é o país, a cidade quando há
   UF escolhida. Os dois saem no mesmo formato, então KPI, destaque e ranking não precisam
   saber de onde o número veio — é o mesmo desenho em dois níveis. */
function lugaresDoRecorte() {
	const filtro = estado.filtro;
	if (!filtro.produto || !filtro.periodo) return { lugares: [], referencia: null, escopo: 'pais' };

	if (filtro.uf) {
		const cidades = municipios()
			.filter(function (linha) {
				return linha.produto === filtro.produto
					&& linha.periodo === filtro.periodo
					&& linha.estado === filtro.uf
					&& typeof linha.preco_medio === 'number';
			})
			.map(function (linha) {
				return {
					nome: linha.municipio,
					estado: linha.estado,
					preco_minimo: linha.preco_minimo,
					preco_medio: linha.preco_medio,
					preco_maximo: linha.preco_maximo,
					postos_pesquisados: linha.postos_pesquisados,
					municipios: 1
				};
			})
			.sort(function (a, b) { return a.preco_medio - b.preco_medio; });
		return { lugares: cidades, referencia: mediaPonderada(cidades), escopo: 'municipio' };
	}

	const porEstado = new Map();
	registros().forEach(function (linha) {
		if (linha.produto !== filtro.produto || linha.periodo !== filtro.periodo) return;
		if (typeof linha.preco_medio !== 'number') return;
		porEstado.set(linha.estado, linha);
	});
	const estados = Array.from(porEstado.values())
		.map(function (linha) { return Object.assign({}, linha, { nome: linha.estado }); })
		.sort(function (a, b) { return a.preco_medio - b.preco_medio; });
	return { lugares: estados, referencia: mediaPonderada(estados), escopo: 'estado' };
}

function mostrarProcedencia() {
	const dados = estado.dados;
	const destino = document.getElementById('procedencia');
	const gerado = dados.gerado_em ? momento.format(new Date(dados.gerado_em)) : '—';
	const ufs = new Set(registros().map(function (linha) { return linha.estado; }));
	destino.textContent = (dados.uf === 'BR' ? ufs.size + ' estados' : 'recorte ' + dados.uf)
		+ ' · ' + inteiro.format(registros().length) + ' linhas · atualizado em ' + gerado;
	const rodape = document.getElementById('rodape-gerado');
	if (rodape) {
		const noticias = estado.noticias.coletado_em
			? ' Manchetes coletadas em ' + momento.format(new Date(estado.noticias.coletado_em)) + '.'
			: ' Sem manchetes coletadas ainda: rode o pipeline com internet.';
		rodape.textContent = noticias;
	}
	const link = document.getElementById('link-fonte');
	if (link && dados.fonte && dados.fonte.url) link.setAttribute('href', dados.fonte.url);
}

function anunciar(texto) {
	const alvo = document.getElementById('anuncio');
	if (alvo) alvo.textContent = texto;
}

/* ---------------------------------------------------------------- kpis */
function cartaoKpi(rotulo, iconeNome, valor, nota, classe) {
	return el('article', { class: 'kpi vidro ' + (classe || '') }, [
		el('p', { class: 'kpi__rotulo' }, [icone(iconeNome), el('span', { texto: rotulo })]),
		el('p', { class: 'kpi__valor', texto: valor }),
		el('p', { class: 'kpi__nota', texto: nota })
	]);
}

function desenharKpis() {
	const destino = document.getElementById('kpis');
	const corte = lugaresDoRecorte();
	const linhas = selecionados();
	const postos = postosDe(linhas);
	const municipios = linhas.reduce(function (soma, linha) { return soma + (linha.municipios || 0); }, 0);

	if (!corte.lugares.length) {
		const media = mediaPonderada(linhas);
		const estadosUsados = new Set(linhas.map(function (linha) { return linha.estado; })).size;
		trocar(destino, [
			cartaoKpi('Média do recorte', 'ico-moeda', media === null ? '—' : moeda.format(media),
				inteiro.format(postos) + ' postos em ' + estadosUsados + ' estados', 'kpi--acento'),
			cartaoKpi('Linhas no recorte', 'ico-lista', inteiro.format(linhas.length),
				inteiro.format(municipios) + ' municípios somados', ''),
			cartaoKpi('Produtos', 'ico-bomba', String((estado.dados.produtos || []).length),
				'escolha um produto e um mês para ver o ranking', ''),
			cartaoKpi('Municípios', 'ico-mapa', inteiro.format(municipios),
				'soma das linhas do recorte', '')
		]);
		anunciar(inteiro.format(linhas.length) + ' linhas no recorte.');
		return;
	}

	const porCidade = corte.escopo === 'municipio';
	const nomeMes = mes(estado.filtro.periodo);
	const barato = corte.lugares[0];
	const caro = corte.lugares[corte.lugares.length - 1];
	const amplitude = variacao(caro.preco_medio, barato.preco_medio);
	const contra = ' vs média ' + (porCidade ? 'estadual' : 'nacional');

	trocar(destino, [
		cartaoKpi(porCidade ? 'Média estadual · ' + estado.filtro.produto : 'Média nacional · ' + estado.filtro.produto,
			'ico-moeda', moeda.format(corte.referencia),
			inteiro.format(postosDe(corte.lugares)) + ' postos em '
				+ plural(corte.lugares.length, porCidade ? 'cidade' : 'estado', porCidade ? 'cidades' : 'estados')
				+ ' · ' + nomeMes + (porCidade ? ' · ' + estado.filtro.uf : ''),
			'kpi--acento'),
		cartaoKpi('Mais barato', 'ico-seta-baixo', barato.nome + ' · ' + moeda.format(barato.preco_medio),
			textoVariacao(variacao(barato.preco_medio, corte.referencia)) + contra, 'kpi--bom'),
		cartaoKpi('Mais caro', 'ico-seta-cima', caro.nome + ' · ' + moeda.format(caro.preco_medio),
			textoVariacao(variacao(caro.preco_medio, corte.referencia)) + contra, 'kpi--ruim'),
		cartaoKpi(porCidade ? 'Amplitude entre cidades' : 'Amplitude entre estados', 'ico-barras',
			textoVariacao(amplitude),
			'de ' + moeda.format(barato.preco_medio) + ' a ' + moeda.format(caro.preco_medio), '')
	]);

	anunciar(plural(corte.lugares.length, porCidade ? 'cidade de ' + estado.filtro.uf : 'estado',
		porCidade ? 'cidades de ' + estado.filtro.uf : 'estados')
		+ ' em ' + nomeMes + ' · média ' + moeda.format(corte.referencia)
		+ ' · mais barato ' + barato.nome + ', mais caro ' + caro.nome + '.');
}

function postosDe(linhas) {
	return linhas.reduce(function (soma, linha) { return soma + (linha.postos_pesquisados || 0); }, 0);
}

function mes(periodo) {
	if (!periodo) return 'todos os meses';
	const partes = periodo.split('-');
	if (partes.length !== 2) return periodo;
	return soMes.format(new Date(Number(partes[0]), Number(partes[1]) - 1, 1));
}

/* ---------------------------------------------------------------- destaques */
function desenharDestaques() {
	const destino = document.getElementById('destaques');
	const corte = lugaresDoRecorte();

	if (!corte.lugares.length) {
		trocar(destino, [el('p', { class: 'vazio', texto: 'Escolha um produto e um mês para ver os destaques do bolso.' })]);
		return;
	}

	const porCidade = corte.escopo === 'municipio';
	// Com menos de seis lugares não dá para ter três de cada lado sem repetir o mesmo lugar
	// como "mais barato" e "mais caro" ao mesmo tempo: cada lado leva o que sobra.
	const quantos = Math.min(3, Math.floor(corte.lugares.length / 2));
	if (quantos === 0) {
		trocar(destino, [el('p', { class: 'vazio', texto: 'O recorte tem um único lugar: não há comparação para os destaques.' })]);
		return;
	}
	const baratos = corte.lugares.slice(0, quantos);
	const caros = corte.lugares.slice(-quantos).reverse();
	trocar(destino, [
		painelDestaque('barato', porCidade ? 'Cidades com menores médias' : 'Menores médias', 'ico-trofeu',
			baratos, corte.referencia, porCidade),
		painelDestaque('caro', porCidade ? 'Cidades com maiores médias' : 'Maiores médias', 'ico-joinha-baixo',
			caros, corte.referencia, porCidade)
	]);
}

function painelDestaque(tipo, titulo, iconeNome, linhas, referencia, porCidade) {
	return el('div', { class: 'destaque destaque--' + tipo + ' vidro' }, [
		el('p', { class: 'destaque__rotulo' }, [icone(iconeNome), el('span', { texto: titulo })]),
		el('div', { class: 'destaque__lista' }, linhas.map(function (linha, indice) {
			const medalha = tipo === 'barato'
				? el('span', { class: 'lugar__medalha' }, [icone('ico-trofeu'), el('span', { texto: (indice + 1) + 'º' })])
				: el('span', { class: 'lugar__medalha' }, [icone('ico-joinha-baixo'), el('span', { texto: (indice + 1) + 'º' })]);
			const nota = porCidade
				? plural(linha.postos_pesquisados || 0, 'posto', 'postos') + ' · de '
					+ moedaPrecisa.format(linha.preco_minimo) + ' a ' + moedaPrecisa.format(linha.preco_maximo)
				: plural(linha.postos_pesquisados || 0, 'posto', 'postos') + ' · '
					+ plural(linha.municipios || 0, 'município', 'municípios');
			return el('div', { class: 'lugar' }, [
				medalha,
				el('p', { class: 'lugar__uf', texto: linha.nome }),
				el('p', { class: 'lugar__nota', texto: nota }),
				el('p', { class: 'lugar__preco', texto: moedaPrecisa.format(linha.preco_medio) }),
				el('div', { class: 'lugar__delta' }, [delta(variacao(linha.preco_medio, referencia))])
			]);
		}))
	]);
}

/* ---------------------------------------------------------------- ranking */
function desenharRanking() {
	const destino = document.getElementById('ranking');
	const legenda = document.getElementById('ranking-legenda');
	const titulo = document.getElementById('ranking-titulo');
	const corte = lugaresDoRecorte();
	const porCidade = corte.escopo === 'municipio';

	if (!corte.lugares.length) {
		if (titulo) titulo.textContent = 'Ranking por estado';
		if (legenda) legenda.textContent = 'Escolha um produto e um mês para comparar os estados.';
		trocar(destino, [el('li', { class: 'vazio', texto: 'Sem ranking para "todos": escolha um produto e um mês.' })]);
		return;
	}

	if (titulo) titulo.textContent = porCidade ? 'Ranking por cidade · ' + estado.filtro.uf : 'Ranking por estado';

	const maior = corte.lugares[corte.lugares.length - 1].preco_medio;
	const menor = corte.lugares[0].preco_medio;
	if (legenda) {
		legenda.textContent = 'Média de ' + estado.filtro.produto + ' em ' + mes(estado.filtro.periodo)
			+ ', ponderada pelo número de postos. A barra é proporcional ao preço; a variação compara com a média '
			+ (porCidade ? 'do estado (' + moeda.format(corte.referencia) + ').' : 'nacional (' + moeda.format(corte.referencia) + '). Clique num estado para descer às cidades.');
	}

	trocar(destino, corte.lugares.map(function (linha, indice) {
		const variacaoReferencia = variacao(linha.preco_medio, corte.referencia);
		const fracao = maior === menor ? 1 : (linha.preco_medio - menor) / (maior - menor);
		const classeBarra = variacaoReferencia > 0.0005 ? 'rank__preenchimento--ruim'
			: (variacaoReferencia < -0.0005 ? 'rank__preenchimento--bom' : '');
		const largura = 22 + fracao * 78;
		const filhos = [
			el('span', { class: 'rank__posicao', texto: (indice + 1) + 'º' }),
			el('span', { class: 'rank__uf', texto: linha.nome }),
			el('span', { class: 'rank__barra', 'aria-hidden': 'true' }, [
				el('span', { class: 'rank__preenchimento ' + classeBarra, estilo: 'width: ' + largura.toFixed(1) + '%' })
			]),
			el('span', { class: 'rank__preco', texto: moeda.format(linha.preco_medio) }),
			delta(variacaoReferencia, 'rank__delta'),
			el('span', { class: 'rank__postos', texto: plural(linha.postos_pesquisados || 0, 'posto', 'postos') })
		];

		// Cidade já é o fim da linha: não há recorte mais fundo para clicar.
		if (porCidade) return el('li', {}, [el('div', { class: 'rank__botao rank__botao--leitura' }, filhos)]);

		return el('li', {}, [el('button', {
			type: 'button', class: 'rank__botao',
			'aria-pressed': linha.estado === estado.filtro.uf ? 'true' : 'false',
			title: 'Filtrar por ' + linha.estado,
			aoClicar: function () {
				const uf = estado.filtro.uf === linha.estado ? '' : linha.estado;
				estado.menus.uf = uf;
				estado.filtro.uf = uf;
				desenhar();
			}
		}, filhos)]);
	}));
}

/* ---------------------------------------------------------------- tabela */
function desenharTabela() {
	const corpo = document.getElementById('corpo-tabela');
	const linhas = selecionados();
	marcarOrdenacao();

	if (!linhas.length) {
		trocar(corpo, [el('tr', {}, [el('td', { colspan: '8', class: 'vazio', texto: 'Nenhuma linha para estes filtros.' })])]);
		return;
	}

	const escalas = escalaDePreco(linhas);
	const ordenadas = ordenar(linhas);
	const ufAtual = estado.filtro.uf;

	trocar(corpo, ordenadas.map(function (linha) {
		const tom = tomDaEscala(linha, escalas);
		const classe = tom.forca > 0.12 ? 'linha--' + tom.cor : '';
		const celulas = [
			el('td', { texto: linha.produto }),
			el('td', { texto: linha.estado }),
			el('td', { texto: linha.periodo }),
			el('td', { class: 'numero', texto: inteiro.format(linha.municipios || 0) }),
			el('td', { class: 'numero', texto: inteiro.format(linha.postos_pesquisados || 0) }),
			el('td', { class: 'numero', texto: moeda.format(linha.preco_minimo) }),
			el('td', { class: 'numero', texto: moedaPrecisa.format(linha.preco_medio) }),
			el('td', { class: 'numero', texto: moeda.format(linha.preco_maximo) })
		];
		return el('tr', {
			class: (linha.estado === ufAtual ? 'estado-atual ' : '') + classe,
			'--cor-linha': 'var(--cor-' + tom.cor + ')',
			'--forca': tom.forca.toFixed(3),
			title: 'Posição na escala de preço do recorte: ' + Math.round(tom.forca * 100) + '%'
		}, celulas);
	}));
}

function ordenar(linhas) {
	const campo = estado.ordem.campo;
	const sinal = estado.ordem.asc ? 1 : -1;
	return linhas.slice().sort(function (a, b) {
		const valorA = a[campo], valorB = b[campo];
		if (typeof valorA === 'number' && typeof valorB === 'number') return (valorA - valorB) * sinal;
		return String(valorA).localeCompare(String(valorB), 'pt-BR') * sinal;
	});
}

function marcarOrdenacao() {
	document.querySelectorAll('#tabela thead th[data-campo]').forEach(function (th) {
		if (th.getAttribute('data-campo') === estado.ordem.campo) {
			th.setAttribute('aria-sort', estado.ordem.asc ? 'ascending' : 'descending');
		} else {
			th.removeAttribute('aria-sort');
		}
	});
}

/* Escala do recorte: dentro de cada produto/mês o mais barato puxa o verde e o mais
   caro puxa o vermelho. Com dois meses (ou produtos) em cena, cada grupo tem a sua. */
function escalaDePreco(linhas) {
	const escalas = new Map();
	linhas.forEach(function (linha) {
		const chave = linha.produto + '|' + linha.periodo;
		const atual = escalas.get(chave) || { menor: Infinity, maior: -Infinity };
		escalas.set(chave, {
			menor: Math.min(atual.menor, linha.preco_medio),
			maior: Math.max(atual.maior, linha.preco_medio)
		});
	});
	return escalas;
}

function tomDaEscala(linha, escalas) {
	const escala = escalas.get(linha.produto + '|' + linha.periodo) || { menor: 0, maior: 0 };
	const meio = (escala.menor + escala.maior) / 2;
	const metade = Math.max((escala.maior - escala.menor) / 2, 1e-9);
	const posicao = (linha.preco_medio - meio) / metade; // -1 = o mais barato, +1 = o mais caro
	const forca = Math.min(Math.abs(posicao), 1);
	return { cor: posicao < 0 ? 'bom' : 'ruim', forca: forca };
}

/* ---------------------------------------------------------------- notícias */
const TONS = {
	beneficio: { titulo: 'Alivia o bolso', classe: 'bom', icone: 'ico-seta-baixo', rotulo: 'Alivia o bolso' },
	prejuizo: { titulo: 'Pesa no bolso', classe: 'ruim', icone: 'ico-seta-cima', rotulo: 'Pesa no bolso' },
	neutro: { titulo: 'Outras sobre o assunto', classe: 'neutro', icone: 'ico-info', rotulo: 'Acompanhar' }
};

function desenharNoticias() {
	const destino = document.getElementById('noticias');
	const itens = estado.noticias.itens || [];

	if (!itens.length) {
		trocar(destino, [el('p', {
			class: 'vazio',
			texto: 'Sem manchetes coletadas ainda. Rode o pipeline com internet (pipeline.ps1) para buscar os feeds públicos.'
		})]);
		return;
	}

	const grupos = ['beneficio', 'prejuizo', 'neutro'].map(function (tom) {
		const doTom = itens.filter(function (item) { return item.tom === tom; });
		if (!doTom.length) return null;
		const definicao = TONS[tom];
		return el('div', { class: 'noticias__grupo noticias__grupo--' + definicao.classe }, [
			el('h3', { class: 'noticias__grupo-titulo' }, [
				icone(definicao.icone),
				el('span', { texto: definicao.titulo + ' (' + doTom.length + ')' })
			]),
			el('div', { class: 'noticias__lista' }, doTom.map(cartaoNoticia))
		]);
	});

	trocar(destino, [resumoDeEstados(itens)].concat(grupos));
}

function resumoDeEstados(itens) {
	const contagem = new Map();
	itens.forEach(function (item) {
		(item.estados || []).forEach(function (uf) { contagem.set(uf, (contagem.get(uf) || 0) + 1); });
	});
	if (!contagem.size) return null;
	const partes = Array.from(contagem.entries())
		.sort(function (a, b) { return b[1] - a[1] || a[0].localeCompare(b[0]); })
		.map(function (par) { return par[0] + ' (' + par[1] + ')'; });

	return el('p', { class: 'legenda' }, [
		icone('ico-mapa'),
		el('span', { texto: ' Estados citados nas manchetes: ' + partes.join(' · ') + '.' })
	]);
}

function cartaoNoticia(item) {
	const definicao = TONS[item.tom] || TONS.neutro;
	const quando = item.publicado_em ? soData.format(new Date(item.publicado_em)) : '';
	const meta = [
		el('span', { texto: item.fonte || 'fonte não identificada' }),
		quando ? el('span', { texto: '· ' + quando }) : null,
		el('span', { class: 'chip' }, [
			icone(item.ambito === 'exterior' ? 'ico-mundo' : 'ico-mapa'),
			el('span', { texto: item.ambito === 'exterior' ? 'Exterior' : 'Nacional' })
		]),
		ehLei(item.titulo) ? el('span', { class: 'chip' }, [icone('ico-documento'), el('span', { texto: 'Lei/tributo' })]) : null
	];

	return el('article', { class: 'noticia noticia--' + item.tom }, [
		el('p', { class: 'noticia__meta' }, [
			el('span', { class: 'selo selo--' + definicao.classe }, [
				icone(definicao.icone),
				el('span', { texto: definicao.rotulo })
			])
		]),
		el('h4', { class: 'noticia__titulo' }, [
			el('a', { href: item.url, target: '_blank', rel: 'noopener noreferrer' }, [
				el('span', { texto: item.titulo + ' ' }),
				icone('ico-link')
			])
		]),
		el('p', { class: 'noticia__meta' }, meta),
		(item.estados && item.estados.length)
			? el('div', { class: 'noticia__estados' }, item.estados.map(function (uf) {
				return el('button', {
					type: 'button', class: 'chip', title: 'Ver os preços de ' + uf,
					aoClicar: function () {
						estado.menus.uf = uf;
						estado.filtro.uf = uf;
						desenhar();
						document.getElementById('ranking').scrollIntoView({ block: 'start' });
					}
				}, [icone('ico-mapa'), el('span', { texto: uf })]);
			}))
			: null,
		el('p', { class: 'noticia__peso', texto: 'Tom lido automaticamente do título; confira a matéria no veículo original.' })
	]);
}

function ehLei(titulo) {
	const alvo = String(titulo).toLowerCase();
	return /\b(lei|leis|mp|medida provisória|medida provisoria|decreto|projeto|pl|tributo|icms|imposto)\b/.test(alvo);
}

/* ---------------------------------------------------------------- estados de tela */
function mostrarEsqueleto() {
	const kpis = document.getElementById('kpis');
	if (kpis) {
		trocar(kpis, [1, 2, 3, 4].map(function () {
			return el('article', { class: 'kpi vidro' }, [el('div', { class: 'esqueleto', estilo: 'height: 4.5rem' })]);
		}));
	}
	const destaques = document.getElementById('destaques');
	if (destaques) {
		trocar(destaques, [el('div', { class: 'destaque vidro' }, [el('div', { class: 'esqueleto' })]),
			el('div', { class: 'destaque vidro' }, [el('div', { class: 'esqueleto' })])]);
	}
	const ranking = document.getElementById('ranking');
	if (ranking) {
		trocar(ranking, [1, 2, 3, 4, 5].map(function () {
			return el('li', {}, [el('div', { class: 'esqueleto', estilo: 'height: 2.6rem' })]);
		}));
	}
	anunciar('Carregando os dados…');
}

function mostrarErro(mensagem) {
	const destino = document.getElementById('kpis');
	const aviso = el('div', { class: 'aviso' }, [
		el('p', { class: 'aviso__titulo' }, [icone('ico-alerta'), el('span', { texto: 'Não foi possível carregar os dados' })]),
		el('p', { texto: 'Erro: ' + mensagem + '. Rode o pipeline (pipeline.ps1) para gerar data/dados.json.' }),
		el('button', { type: 'button', class: 'botao', texto: 'Tentar de novo', aoClicar: function () { location.reload(); } })
	]);
	trocar(destino, [aviso]);
	const destaques = document.getElementById('destaques');
	if (destaques) trocar(destaques, []);
	const ranking = document.getElementById('ranking');
	if (ranking) trocar(ranking, []);
	anunciar('Falha ao carregar os dados.');
}

/* ---------------------------------------------------------------- abas */
function ligarAbas() {
	const abas = [].slice.call(document.querySelectorAll('.abas [role="tab"]'));
	if (!abas.length) return;

	function ativar(aba, focar) {
		abas.forEach(function (outra) {
			const escolhida = outra === aba;
			outra.setAttribute('aria-selected', escolhida ? 'true' : 'false');
			outra.tabIndex = escolhida ? 0 : -1;
			const painel = document.getElementById(outra.getAttribute('aria-controls'));
			if (painel) painel.hidden = !escolhida;
		});
		if (focar) aba.focus();
	}

	abas.forEach(function (aba, indice) {
		aba.addEventListener('click', function () { ativar(aba, false); });
		aba.addEventListener('keydown', function (evento) {
			let destino = null;
			if (evento.key === 'ArrowRight' || evento.key === 'ArrowDown') destino = abas[(indice + 1) % abas.length];
			else if (evento.key === 'ArrowLeft' || evento.key === 'ArrowUp') destino = abas[(indice - 1 + abas.length) % abas.length];
			else if (evento.key === 'Home') destino = abas[0];
			else if (evento.key === 'End') destino = abas[abas.length - 1];
			if (!destino) return;
			evento.preventDefault();
			ativar(destino, true);
		});
	});

	if (location.hash === '#inteligencia') {
		const aba = document.getElementById('aba-inteligencia');
		if (aba) ativar(aba, false);
	}
}

/* ---------------------------------------------------------------- inteligência
   Lê data/inteligencia.json (fiscalização × preço). A carga é independente da aba de
   preços: se o segundo artefato faltar, "Preços" continua funcionando e esta aba avisa. */
const CAMINHO_INTELIGENCIA = 'data/inteligencia.json';

/* Nome técnico da medida no artefato → rótulo em português; o nome cru fica no title. */
const ROTULOS_CORRELACAO = {
	fiscalizacao_x_preco_pooled: 'Fiscalização × preço (dados empilhados)',
	fiscalizacao_x_preco_pooled_spearman: 'Fiscalização × preço — Spearman (dados empilhados)',
	fiscalizacao_x_preco_intra_uf: 'Fiscalização × preço (diferença dentro da UF)',
	fiscalizacao_lag1_x_preco_intra_uf: 'Fiscalização 1 mês antes × preço (dentro da UF)',
	fiscalizacao_lag2_x_preco_intra_uf: 'Fiscalização 2 meses antes × preço (dentro da UF)',
	ipf_x_dispersao_uf: 'IPF × dispersão do preço entre estados',
	ipf_x_dispersao_uf_spearman: 'IPF × dispersão do preço — Spearman (entre estados)',
	interdicao_x_preco_uf: 'Interdições × preço (entre estados)',
	interdicao_x_preco_uf_spearman: 'Interdições × preço — Spearman (entre estados)'
};

const COLUNAS_IPF = [
	{ campo: 'uf', rotulo: 'Estado' },
	{ campo: 'postos', rotulo: 'Postos', titulo: 'Postos ativos hoje na API de revendedores da ANP' },
	{ campo: 'acoes_12m', rotulo: 'Ações 12m', titulo: 'Ações de fiscalização em revendas na janela do IPF' },
	{ campo: 'interdicoes_12m', rotulo: 'Interdições 12m', titulo: 'Autos de interdição na janela do IPF' },
	{ campo: 'ipf', rotulo: 'IPF', titulo: 'Ações de fiscalização em revendas por 1.000 postos ativos' },
	{ campo: 'ipf_acumulado', rotulo: 'IPF desde 1998', titulo: 'Ações desde 1998 por 1.000 postos atuais — favorece estados com histórico longo' },
	{ campo: 'taxa_interdicao', rotulo: 'Interdições/100 ações', titulo: 'Autos de interdição a cada 100 ações na janela do IPF' },
	{ campo: 'dispersao_cv', rotulo: 'Dispersão (CV)', titulo: 'Coeficiente de variação do preço entre revendas do estado, média dos meses' },
	{ campo: 'preco_medio', rotulo: 'Preço médio', titulo: 'Preço médio do recorte de preços do estado' }
];

const CACHE_DECIMAL = {};

function decimal(valor, casas) {
	if (valor === null || valor === undefined || !isFinite(Number(valor))) return '—';
	if (!CACHE_DECIMAL[casas]) {
		CACHE_DECIMAL[casas] = new Intl.NumberFormat('pt-BR', {
			minimumFractionDigits: casas, maximumFractionDigits: casas
		});
	}
	return CACHE_DECIMAL[casas].format(Number(valor));
}

/* Postos no artefato são mediana mensal e podem ser fracionários (7,5 postos/mês). */
function postosTexto(valor) {
	if (valor === null || valor === undefined || !isFinite(Number(valor))) return '—';
	return Number.isInteger(valor) ? inteiro.format(valor) : decimal(valor, 1);
}

function plural(quantidade, singular, varios) {
	return inteiro.format(quantidade) + ' ' + (quantidade === 1 ? singular : varios);
}

/* Formata só quando o número existe: campo ausente vira travessão, nunca "NaN". */
function formatar(valor, formatador) {
	return typeof valor === 'number' && isFinite(valor) ? formatador.format(valor) : '—';
}

function porcento(fracao) {
	return formatar(fracao, percentual);
}

function itemFaixa(rotulo, valor, nota, classeExtra) {
	return el('div', { class: 'faixa__item' + (classeExtra ? ' faixa__item--' + classeExtra : '') }, [
		el('p', { class: 'faixa__rotulo', texto: rotulo }),
		el('p', { class: 'faixa__valor', texto: valor }),
		el('p', { class: 'faixa__nota', texto: nota })
	]);
}

function iniciarInteligencia() {
	fetch(CAMINHO_INTELIGENCIA, { cache: 'no-store' })
		.then(function (resposta) {
			if (!resposta.ok) throw new Error('HTTP ' + resposta.status);
			return resposta.json();
		})
		.then(function (dados) {
			estado.inteligencia = dados;
			desenharInteligencia();
		})
		.catch(function (erro) {
			estado.inteligencia = null;
			mostrarErroInteligencia((erro && erro.message) ? erro.message : String(erro));
		});
}

function mostrarErroInteligencia(mensagem) {
	const procedencia = document.getElementById('inteligencia-procedencia');
	if (procedencia) procedencia.textContent = '';
	const corpo = document.getElementById('inteligencia-corpo');
	if (corpo) corpo.hidden = true;

	const dica = location.protocol === 'file:'
		? ' Abrindo direto do arquivo, o navegador pode barrar a leitura do JSON: use o servir.ps1 ou publique a pasta site/.'
		: ' Rode python scripts/inteligencia.py para gerar site/data/inteligencia.json.';

	const destino = document.getElementById('inteligencia-aviso');
	if (!destino) return;
	trocar(destino, [el('div', { class: 'aviso' }, [
		el('p', { class: 'aviso__titulo' }, [
			icone('ico-alerta'),
			el('span', { texto: 'Não foi possível carregar a análise de inteligência' })
		]),
		el('p', { texto: 'Erro: ' + mensagem + '.' + dica }),
		el('p', { texto: 'A aba "Preços" continua funcionando normalmente.' }),
		el('button', {
			type: 'button', class: 'botao', texto: 'Tentar de novo',
			aoClicar: function () { location.reload(); }
		})
	])]);
}

function desenharInteligencia() {
	if (!estado.inteligencia) return;
	const aviso = document.getElementById('inteligencia-aviso');
	if (aviso) trocar(aviso, []);
	const corpo = document.getElementById('inteligencia-corpo');
	if (corpo) corpo.hidden = false;

	desenharProcedenciaInteligencia();
	desenharContexto();
	desenharInterdicaoPreco();
	desenharCorrelacoes();
	desenharIpf();
	desenharAnomalias();
	desenharAlvos();
	desenharInterditos();
	desenharLimitacoes();
}

function desenharProcedenciaInteligencia() {
	const destino = document.getElementById('inteligencia-procedencia');
	if (!destino) return;
	const periodos = estado.inteligencia.periodos || {};
	const gerado = estado.inteligencia.gerado_em ? momento.format(new Date(estado.inteligencia.gerado_em)) : '—';
	destino.textContent = 'Artefato gerado em ' + gerado + ' · fiscalização de ' + (periodos.fiscalizacao || '—')
		+ ' · preços de ' + (periodos.precos_uf || '—')
		+ ' · correlações desde ' + (periodos.correlacao_desde || '—') + '.';
}

function desenharContexto() {
	const dados = estado.inteligencia;
	const cobertura = dados.cobertura || {};
	const periodos = dados.periodos || {};
	const score = dados.score_evidencia || {};
	const destino = document.getElementById('int-contexto');
	if (!destino) return;

	trocar(destino, [
		itemFaixa('Fiscalização', periodos.fiscalizacao || '—',
			inteiro.format(cobertura.acoes_normalizadas || 0) + ' ações · '
			+ inteiro.format(cobertura.acoes_revenda || 0) + ' em revendas'),
		itemFaixa('Preço', periodos.precos_uf || '—',
			inteiro.format(cobertura.municipios_com_preco || 0) + ' municípios em '
			+ inteiro.format(cobertura.meses_de_preco || 0) + ' meses'),
		itemFaixa('Postos ativos', inteiro.format(cobertura.postos_ativos_api || 0),
			inteiro.format(cobertura.ufs || 0) + ' estados · API de revendedores da ANP'),
		itemFaixa('Interdições em revendas', inteiro.format(cobertura.interdicoes_revenda || 0),
			'autos de interdição desde 1998'),
		itemFaixa('Municípios fiscalizados', inteiro.format(cobertura.municipios_com_fiscalizacao || 0),
			'com pelo menos uma ação registrada'),
		itemFaixa('Score de evidência', decimal(score.score, 4),
			'média de (1 − p) × |r| × estabilidade em ' + inteiro.format(score.evidencias || 0) + ' correlações',
			'acento')
	]);

	const nota = document.getElementById('int-contexto-nota');
	if (nota) {
		nota.textContent = 'O score de evidência vai de 0 a 1 e é a média de (1 − p) × |r| × estabilidade sobre as '
			+ 'correlações medidas: ele só sobe quando o p-valor é baixo, o efeito é grande e o sinal se repete. '
			+ 'Perto de zero quer dizer que as associações testadas são fracas ou instáveis — e é isso que o número '
			+ 'abaixo dele está dizendo.';
	}
}

function desenharInterdicaoPreco() {
	const destino = document.getElementById('int-interdicao');
	if (!destino) return;
	const efeito = estado.inteligencia.interdicao_preco || {};
	if (!efeito.n) {
		trocar(destino, [el('p', { class: 'vazio', texto: 'Esta geração do artefato não traz o teste de interdição × preço.' })]);
		return;
	}

	const moedaFina = new Intl.NumberFormat('pt-BR', {
		style: 'currency', currency: 'BRL', minimumFractionDigits: 4, maximumFractionDigits: 4
	});

	const bloco = el('div', { class: 'efeito-bloco' }, [
		el('div', { class: 'efeito' }, [
			itemEfeito('Δ preço no município interditado', moedaPrecisa.format(efeito.delta_bruto_medio),
				'de antes para depois, em ' + plural(efeito.n, 'caso', 'casos')),
			itemEfeito('Δ preço no controle (mesma UF)', moedaPrecisa.format(efeito.delta_controle_medio),
				'demais municípios da UF, nos mesmos meses'),
			itemEfeito('Efeito (interditado − controle)', moedaFina.format(efeito.efeito),
				'p = ' + decimal(efeito.p, 3) + ' · Wilcoxon W = ' + decimal(efeito.estatistica, 0)
				+ ' · variação de ' + decimal(efeito.efeito_pct, 3) + '%', 'destaque')
		]),
		el('p', { class: 'efeito__leitura' }, [
			el('strong', { texto: 'Leitura do artefato: ' }),
			el('span', { texto: efeito.leitura || '—' })
		]),
		el('p', { class: 'ressalva' }, [
			el('strong', { texto: 'Como ler: ' }),
			el('span', { texto: 'o número bruto do município interditado é comparado a um controle — o mesmo cálculo nos demais municípios da UF, nos mesmos meses (diferença em diferenças). Só a diferença entre os dois é o efeito. ' }),
			el('strong', { texto: 'Este resultado não mostra efeito de preço: ' }),
			el('span', { texto: 'a interdição é ato administrativo e pode ser revertida em recurso, e a amostra de preço não cobre o país inteiro.' })
		])
	]);

	const exemplos = Array.isArray(efeito.exemplos) ? efeito.exemplos : [];
	if (exemplos.length) {
		const tabela = el('table', { class: 'tabela' }, [
			el('caption', { class: 'oculto', texto: 'Casos com o efeito mais negativo: preço antes e depois da interdição e o mesmo intervalo no controle da UF.' }),
			el('thead', {}, [el('tr', {}, [
				el('th', { scope: 'col', texto: 'Estado' }),
				el('th', { scope: 'col', texto: 'Município' }),
				el('th', { scope: 'col', texto: 'Mês' }),
				el('th', { scope: 'col', class: 'numero', texto: 'Antes' }),
				el('th', { scope: 'col', class: 'numero', texto: 'Depois' }),
				el('th', { scope: 'col', class: 'numero', texto: 'Δ' }),
				el('th', { scope: 'col', class: 'numero', texto: 'Δ controle' }),
				el('th', { scope: 'col', class: 'numero', texto: 'Efeito' })
			])]),
			el('tbody', {}, exemplos.map(function (exemplo) {
				return el('tr', {}, [
					el('td', { texto: exemplo.uf }),
					el('td', { texto: exemplo.municipio }),
					el('td', { texto: mes(exemplo.periodo) }),
					el('td', { class: 'numero', texto: moedaPrecisa.format(exemplo.antes) }),
					el('td', { class: 'numero', texto: moedaPrecisa.format(exemplo.depois) }),
					el('td', { class: 'numero', texto: moedaPrecisa.format(exemplo.delta) }),
					el('td', { class: 'numero', texto: moedaPrecisa.format(exemplo.delta_controle) }),
					el('td', { class: 'numero', texto: moedaPrecisa.format(exemplo.efeito) })
				]);
			}))
		]);
		bloco.appendChild(el('details', { class: 'exemplos' }, [
			el('summary', { texto: 'Ver os ' + inteiro.format(exemplos.length) + ' casos de efeito mais negativo' }),
			el('div', { class: 'tabela-rolagem' }, [tabela])
		]));
	}

	trocar(destino, [bloco]);
}

function itemEfeito(rotulo, valor, nota, classeExtra) {
	return el('div', { class: 'efeito__item' + (classeExtra ? ' efeito__item--' + classeExtra : '') }, [
		el('p', { class: 'efeito__rotulo', texto: rotulo }),
		el('p', { class: 'efeito__valor', texto: valor }),
		el('p', { class: 'efeito__nota', texto: nota })
	]);
}

function desenharCorrelacoes() {
	const corpo = document.getElementById('correlacoes-corpo');
	if (!corpo) return;
	const lista = estado.inteligencia.correlacoes || [];
	if (!lista.length) {
		trocar(corpo, [el('tr', {}, [el('td', { colspan: '7', class: 'vazio', texto: 'Sem correlações publicadas nesta geração.' })])]);
		return;
	}

	trocar(corpo, lista.map(function (item) {
		const relevante = typeof item.p === 'number' && item.p < 0.05;
		const rotulo = ROTULOS_CORRELACAO[item.nome] || String(item.nome).replace(/_/g, ' ');
		return el('tr', { class: relevante ? 'linha--evidencia' : '' }, [
			el('th', { scope: 'row', class: 'texto', title: 'Nome no artefato: ' + item.nome, texto: rotulo }),
			el('td', { texto: item.metodo === 'spearman' ? 'Spearman' : 'Pearson' }),
			el('td', { class: 'numero', texto: decimal(item.r, 3) }),
			el('td', { class: 'numero' }, [
				el('span', { texto: decimal(item.p, 3) }),
				relevante ? el('span', { class: 'selo selo--bom selo--miudo', texto: 'p < 0,05' }) : null
			]),
			el('td', { class: 'numero', texto: inteiro.format(item.n || 0) }),
			el('td', { class: 'numero', texto: decimal(item.estabilidade, 2) }),
			el('td', { class: 'texto texto--longo', texto: item.leitura || '—' })
		]);
	}));

	const nota = document.getElementById('int-correlacoes-nota');
	if (nota) {
		const parametros = estado.inteligencia.parametros || {};
		const comSelo = lista.filter(function (item) { return typeof item.p === 'number' && item.p < 0.05; }).length;
		const atrasos = Array.isArray(parametros.atrasos) && parametros.atrasos.length
			? ' Defasagens testadas: fiscalização de ' + parametros.atrasos.join(' e de ') + ' meses antes do preço.'
			: '';
		nota.textContent = inteiro.format(comSelo) + ' das ' + inteiro.format(lista.length)
			+ ' medidas têm p < 0,05 (selo verde): a associação tem menos de 5% de chance de ser acaso — o que não a '
			+ 'torna causa. Método do coeficiente: ' + (parametros.metodo || 'pearson') + '.' + atrasos;
	}
}

function escalaDeIpf(lista) {
	const valores = lista
		.map(function (linha) { return Number(linha.ipf); })
		.filter(function (valor) { return isFinite(valor); });
	if (!valores.length) return { menor: 0, maior: 0 };
	return { menor: Math.min.apply(null, valores), maior: Math.max.apply(null, valores) };
}

function celulaIpf(valor, escala) {
	const amplitude = escala.maior - escala.menor;
	const bruto = amplitude > 0 ? (Number(valor) - escala.menor) / amplitude : 0.5;
	const forca = Math.max(0.15, Math.min(1, bruto));
	const cor = bruto >= 0.5 ? 'bom' : 'alerta';
	return el('td', {
		class: 'numero celula--' + cor,
		'--cor-linha': 'var(--cor-' + cor + ')',
		'--forca': forca.toFixed(3),
		title: 'Cor proporcional ao IPF dentro do quadro: mais verde, IPF maior',
		texto: decimal(valor, 2)
	});
}

function desenharIpf() {
	const dados = estado.inteligencia;
	const lista = dados.ufs || [];
	const cabecalho = document.getElementById('ipf-cabecalho');
	const corpo = document.getElementById('ipf-corpo');
	if (!cabecalho || !corpo) return;

	const parametros = dados.parametros || {};
	const periodos = dados.periodos || {};
	const janela = parametros.janela_ipf || periodos.janela_ipf_meses || 12;
	const exemplo = lista.length ? lista[0] : {};
	const legenda = document.getElementById('int-ipf-legenda');
	if (legenda) {
		legenda.textContent = 'IPF = ações de fiscalização em revendas por 1.000 postos ativos, nos últimos '
			+ inteiro.format(janela) + ' meses'
			+ (exemplo.periodo_inicio ? ' (' + exemplo.periodo_inicio + ' a ' + exemplo.periodo_fim + ')' : '') + '. '
			+ 'Célula mais verde é IPF maior; mais âmbar, IPF menor. Selo "Zona cega" = IPF entre os 25% mais baixos '
			+ 'e preço disperso dentro do estado (fiscaliza pouco e o preço varia muito); "Fora da zona cega" é o '
			+ 'contrário. Clique no título de uma coluna para reordenar.';
	}

	trocar(cabecalho, [el('tr', {}, COLUNAS_IPF.map(function (coluna) {
		const numerica = coluna.campo !== 'uf';
		return el('th', {
			scope: 'col', 'data-campo': coluna.campo, title: coluna.titulo || null,
			class: numerica ? 'numero' : ''
		}, [el('button', {
			type: 'button', texto: coluna.rotulo,
			aoClicar: function () {
				if (estado.ordemIpf.campo === coluna.campo) estado.ordemIpf.asc = !estado.ordemIpf.asc;
				else estado.ordemIpf = { campo: coluna.campo, asc: coluna.campo === 'uf' };
				desenharIpf();
			}
		})]);
	}))]);

	const escala = escalaDeIpf(lista);
	const ordenadas = ordenarIpf(lista);

	if (!ordenadas.length) {
		trocar(corpo, [el('tr', {}, [el('td', { colspan: String(COLUNAS_IPF.length), class: 'vazio', texto: 'Nenhum estado publicado nesta geração.' })])]);
		marcarOrdenacaoIpf();
		return;
	}

	trocar(corpo, ordenadas.map(function (linha) {
		const taxa = typeof linha.taxa_interdicao === 'number' ? decimal(linha.taxa_interdicao, 2) + '%' : '—';
		const dispersao = typeof linha.dispersao_cv === 'number' ? percentual.format(linha.dispersao_cv) : '—';
		const preco = typeof linha.preco_medio === 'number' ? moeda.format(linha.preco_medio) : '—';
		return el('tr', {}, [
			el('td', {}, [
				el('span', { class: 'uf-forte', texto: linha.uf }),
				el('span', {
					class: 'selo selo--' + (linha.zona_cega ? 'alerta' : 'bom'),
					texto: linha.zona_cega ? 'Zona cega' : 'Fora da zona cega'
				})
			]),
			el('td', { class: 'numero', texto: inteiro.format(linha.postos || 0) }),
			el('td', { class: 'numero', texto: inteiro.format(linha.acoes_12m || 0) }),
			el('td', { class: 'numero', texto: inteiro.format(linha.interdicoes_12m || 0) }),
			celulaIpf(linha.ipf, escala),
			el('td', { class: 'numero', texto: decimal(linha.ipf_acumulado, 2) }),
			el('td', { class: 'numero', texto: taxa }),
			el('td', { class: 'numero', texto: dispersao }),
			el('td', { class: 'numero', texto: preco })
		]);
	}));

	marcarOrdenacaoIpf();
}

function ordenarIpf(lista) {
	const campo = estado.ordemIpf.campo;
	const sinal = estado.ordemIpf.asc ? 1 : -1;
	return lista.slice().sort(function (a, b) {
		if (campo === 'uf') return String(a.uf).localeCompare(String(b.uf), 'pt-BR') * sinal;
		return (Number(a[campo] || 0) - Number(b[campo] || 0)) * sinal;
	});
}

function marcarOrdenacaoIpf() {
	const tabela = document.getElementById('tabela-ipf');
	if (!tabela) return;
	tabela.querySelectorAll('thead th[data-campo]').forEach(function (th) {
		if (th.getAttribute('data-campo') === estado.ordemIpf.campo) {
			th.setAttribute('aria-sort', estado.ordemIpf.asc ? 'ascending' : 'descending');
		} else {
			th.removeAttribute('aria-sort');
		}
	});
}

function desenharAnomalias() {
	const corpo = document.getElementById('anomalias-corpo');
	if (!corpo) return;
	const lista = estado.inteligencia.anomalias || [];
	if (!lista.length) {
		trocar(corpo, [el('tr', {}, [el('td', { colspan: '10', class: 'vazio', texto: 'Nenhum município com preço mínimo colado na média nesta geração.' })])]);
		return;
	}

	trocar(corpo, lista.map(function (linha) {
		return el('tr', {}, [
			el('td', { texto: linha.uf }),
			el('td', { texto: linha.municipio }),
			el('td', { texto: inteiro.format(linha.meses_colados || 0) + ' de ' + inteiro.format(linha.meses || 0) + ' (' + porcento(linha.taxa_colada) + ')' }),
			el('td', { class: 'numero', texto: decimal(linha.folga_pct, 1) + '%' }),
			el('td', { class: 'numero', texto: postosTexto(linha.postos) }),
			el('td', { class: 'numero', texto: formatar(linha.preco_minimo, moeda) }),
			el('td', { class: 'numero', texto: formatar(linha.preco_medio, moedaPrecisa) }),
			el('td', { class: 'numero', texto: formatar(linha.preco_maximo, moeda) }),
			el('td', { class: 'numero', texto: formatar(linha.amplitude, moedaPrecisa) }),
			el('td', { texto: mes(linha.ultimo_periodo) })
		]);
	}));

	const nota = document.getElementById('int-anomalias-nota');
	if (nota) {
		const parametros = estado.inteligencia.parametros || {};
		const limite = parametros.limite_anomalia;
		const minimo = parametros.minimo_postos;
		nota.textContent = 'Conta como "colado" o mês em que o preço mínimo fica a menos de '
			+ percentual.format(typeof limite === 'number' ? limite : 0.02) + ' da média do município'
			+ (typeof minimo === 'number' ? '; só entram municípios com ' + inteiro.format(minimo) + ' postos ou mais' : '')
			+ '. Folga média é quanto o preço mínimo ficou abaixo da média, em média. Postos é a mediana mensal.';
	}
}

function desenharAlvos() {
	const destino = document.getElementById('alvos-lista');
	if (!destino) return;
	const dados = estado.inteligencia;
	const lista = dados.alvos || [];
	const pesos = dados.pesos_score_fiscal || {};

	const legenda = document.getElementById('int-alvos-legenda');
	if (legenda) {
		legenda.textContent = 'Score composto de 0 a 1 — soma das quatro componentes normalizadas e ponderadas: '
			+ 'dispersão do preço entre os postos do município (' + percentual.format(pesos.dispersao || 0) + '), '
			+ 'pouca fiscalização para o tamanho do mercado (' + percentual.format(pesos.fiscalizacao || 0) + '), '
			+ 'histórico de interdição (' + percentual.format(pesos.interdicao || 0) + ') e distância da mediana do '
			+ 'estado (' + percentual.format(pesos.variacao || 0) + '). Quanto maior, mais o município reúne os '
			+ 'sinais que um fiscal olharia primeiro — é priorização, não acusação.';
	}

	if (!lista.length) {
		trocar(destino, [el('p', { class: 'vazio', texto: 'Sem alvos publicados nesta geração.' })]);
		return;
	}

	const componentes = [
		{ chave: 'comp_dispersao', nome: 'Dispersão do preço entre postos', peso: pesos.dispersao },
		{ chave: 'comp_fiscalizacao', nome: 'Pouca fiscalização para o mercado', peso: pesos.fiscalizacao },
		{ chave: 'comp_interdicao', nome: 'Histórico de interdição', peso: pesos.interdicao },
		{ chave: 'comp_variacao', nome: 'Preço longe da mediana do estado', peso: pesos.variacao }
	];

	trocar(destino, lista.map(function (linha, indice) {
		return el('article', { class: 'alvo vidro' }, [
			el('div', { class: 'alvo__topo' }, [
				el('p', { class: 'alvo__lugar' }, [
					el('span', { texto: (indice + 1) + 'º · ' + linha.uf + ' · ' }),
					el('strong', { texto: linha.municipio })
				]),
				el('p', { class: 'alvo__score' }, [
					el('span', { class: 'oculto', texto: 'Score ' }),
					el('span', { texto: decimal(linha.score, 2) })
				])
			]),
			el('p', { class: 'alvo__meta', texto: postosTexto(linha.postos) + ' postos (mediana mensal) · '
				+ inteiro.format(linha.meses || 0) + ' meses de preço · média ' + formatar(linha.preco_medio, moedaPrecisa)
				+ ' · dispersão relativa de ' + porcento(linha.desvio_relativo) }),
			el('div', { class: 'alvo__componentes' }, componentes.map(function (item) {
				const peso = typeof item.peso === 'number' ? ' (' + percentual.format(item.peso) + ' do score)' : '';
				return medidor(item.nome + peso, linha[item.chave]);
			})),
			el('p', { class: 'alvo__rodape', texto: plural(linha.acoes_municipio || 0, 'ação de fiscalização', 'ações de fiscalização')
				+ ' e ' + plural(linha.interdicoes_municipio || 0, 'interdição', 'interdições') + ' no município · '
				+ 'preço médio a uma distância de ' + porcento(linha.variacao_uf) + ' da mediana do estado' })
		]);
	}));
}

function medidor(rotulo, valor) {
	const bruto = typeof valor === 'number' && isFinite(valor) ? valor : 0;
	const fracao = Math.max(0, Math.min(1, bruto));
	return el('div', { class: 'medidor' }, [
		el('p', { class: 'medidor__rotulo', texto: rotulo }),
		el('p', { class: 'medidor__valor', texto: percentual.format(fracao) }),
		el('span', { class: 'medidor__trilho', 'aria-hidden': 'true' }, [
			el('span', { class: 'medidor__barra', estilo: 'width: ' + (fracao * 100).toFixed(1) + '%' })
		])
	]);
}

function desenharInterditos() {
	const corpo = document.getElementById('interditos-corpo');
	if (!corpo) return;
	const lista = (estado.inteligencia.interditos || []).slice().sort(function (a, b) {
		return (Number(b.ultima) || 0) - (Number(a.ultima) || 0) || (Number(b.primeira) || 0) - (Number(a.primeira) || 0);
	});

	if (!lista.length) {
		trocar(corpo, [el('tr', {}, [el('td', { colspan: '6', class: 'vazio', texto: 'Nenhuma interdição registrada nesta geração.' })])]);
		return;
	}

	trocar(corpo, lista.map(function (linha) {
		return el('tr', {}, [
			el('td', { texto: linha.uf }),
			el('td', { texto: linha.municipio }),
			el('td', { class: 'mono', texto: formatarCnpj(linha.cnpj) }),
			el('td', { class: 'numero', texto: inteiro.format(linha.interdicoes || 0) }),
			el('td', { texto: dataDoArtefato(linha.primeira) }),
			el('td', { texto: dataDoArtefato(linha.ultima) })
		]);
	}));
}

function dataDoArtefato(milissegundos) {
	const valor = Number(milissegundos);
	if (!isFinite(valor) || valor <= 0) return '—';
	return soDataUTC.format(new Date(valor));
}

function formatarCnpj(valor) {
	const digitos = String(valor === null || valor === undefined ? '' : valor).replace(/[^0-9]/g, '');
	if (digitos.length !== 14) return String(valor === null || valor === undefined ? '—' : valor);
	return digitos.slice(0, 2) + '.' + digitos.slice(2, 5) + '.' + digitos.slice(5, 8)
		+ '/' + digitos.slice(8, 12) + '-' + digitos.slice(12);
}

function desenharLimitacoes() {
	const destino = document.getElementById('int-limitacoes');
	if (!destino) return;
	const lista = estado.inteligencia.limitacoes || [];
	if (!lista.length) {
		trocar(destino, [el('li', {}, [el('span', { texto: 'O artefato desta geração não trouxe limitações — trate os números acima com desconfiança.' })])]);
		return;
	}
	trocar(destino, lista.map(function (texto) {
		return el('li', {}, [icone('ico-alerta'), el('span', { texto: texto })]);
	}));
}