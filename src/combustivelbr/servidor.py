"""Servidor opcional: serve a API com o mesmo JSON e o site estático.

O site **funciona sem servidor** (lê ``site/data/dados.json``). Este módulo existe para
consulta dinâmica por programas e para pré-visualizar tudo localmente.

As rotas de inteligência leem ``site/data/inteligencia.json`` (o mesmo arquivo da aba
Inteligência do site) — nada aqui recalcula indicador.
"""

from __future__ import annotations

import json
import os
from os import PathLike

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from . import __version__, config

app = FastAPI(
    title="combustivelBR",
    version=__version__,
    description="Preços de combustíveis no Brasil a partir de dados públicos.",
)


def _inteligencia() -> dict:
    """JSON de inteligência publicado (404 se a fase 2 ainda não rodou)."""
    if not config.ARQUIVO_INTELIGENCIA.exists():
        raise HTTPException(
            status_code=404,
            detail="Nenhuma análise de inteligência publicada: rode scripts/inteligencia.py.",
        )
    return json.loads(config.ARQUIVO_INTELIGENCIA.read_text(encoding="utf-8"))


def _lista(caminho: str) -> list:
    return _inteligencia().get(caminho, [])


@app.get("/saude")
def saude() -> dict:
    """Confirma que o servidor está no ar e de qual fonte os dados vêm."""
    return {"ok": True, "versao": __version__, "fonte": config.FONTE_NOME}


@app.get("/dados")
def dados() -> dict:
    """Devolve o JSON publicado pelo pipeline (mesmo arquivo que o site lê)."""
    if not config.ARQUIVO_PROCESSADO.exists():
        raise HTTPException(
            status_code=404,
            detail="Nenhum dado processado ainda: rode o pipeline (pipeline.ps1).",
        )
    return json.loads(config.ARQUIVO_PROCESSADO.read_text(encoding="utf-8"))


@app.get("/inteligencia")
def inteligencia() -> dict:
    """Índice da análise: score de evidência, cobertura, parâmetros e limitações."""
    corpo = _inteligencia()
    return {
        "gerado_em": corpo.get("gerado_em"),
        "periodos": corpo.get("periodos"),
        "cobertura": corpo.get("cobertura"),
        "parametros": corpo.get("parametros"),
        "limitacoes": corpo.get("limitacoes"),
        "score_evidencia": corpo.get("score_evidencia"),
    }


@app.get("/inteligencia/correlacoes")
def inteligencia_correlacoes() -> list:
    """Todas as correlações com r, p e n (associação não é causa)."""
    return _lista("correlacoes")


@app.get("/inteligencia/ufs")
def inteligencia_ufs(zona_cega: bool | None = None, uf: str | None = None) -> list:
    """IPF, interdições e dispersão por UF; filtre por UF ou só zonas cegas."""
    ufs = _lista("ufs")
    if uf:
        ufs = [item for item in ufs if item["uf"] == uf.upper()]
    if zona_cega is not None:
        ufs = [item for item in ufs if bool(item.get("zona_cega")) is zona_cega]
    return ufs


@app.get("/inteligencia/anomalias")
def inteligencia_anomalias(uf: str | None = None) -> list:
    """Municípios com preço mínimo colado na média (padrão a verificar, não prova)."""
    anomalias = _lista("anomalias")
    return [item for item in anomalias if not uf or item["uf"] == uf.upper()]


@app.get("/inteligencia/alvos")
def inteligencia_alvos(limite: int = 15) -> list:
    """Alvos de fiscalização ordenados pelo score composto."""
    return _lista("alvos")[: max(1, limite)]


@app.get("/inteligencia/interditos")
def inteligencia_interditos(uf: str | None = None) -> list:
    """Revendas que já receberam auto de interdição."""
    interditados = _lista("interditos")
    return [item for item in interditados if not uf or item["uf"] == uf.upper()]


@app.get("/inteligencia/interdicao-preco")
def inteligencia_interdicao_preco() -> dict:
    """Efeito da interdição sobre o preço, medido contra o controle da mesma UF."""
    return _inteligencia().get("interdicao_preco", {})


class SiteSemCache(StaticFiles):
    """Serve o site exigindo revalidação a cada uso.

    Sem o cabeçalho, o navegador reaproveita CSS e JS antigos por heurística e a tela
    continua com o layout anterior mesmo depois de o arquivo ter sido corrigido. A
    revalidação não custa banda: com ETag e Last-Modified iguais a resposta é 304.
    """

    def file_response(
        self,
        full_path: PathLike,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        """Serve o arquivo e marca a resposta para o navegador revalidar antes de reusar."""
        resposta = super().file_response(full_path, stat_result, scope, status_code)
        resposta.headers["Cache-Control"] = "no-cache"
        return resposta


# O site estático fica na raiz; por isso este mount é o último (senão engole as rotas acima).
app.mount("/", SiteSemCache(directory=str(config.SITE), html=True), name="site")
