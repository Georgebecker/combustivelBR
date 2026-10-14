"""Hook do agente: nega ESCRITA em data/raw/ (prova) e em .env (segredo).

Recebe o evento do hook em JSON pelo stdin e responde no contrato de hooks:
permissionDecision "deny" quando o alvo e protegido; fora disso, nao imprime nada.

Mantido em ASCII de proposito: no Windows o stdout do Python pode estar em cp1252 e
acento aqui viraria erro de codificacao no meio do hook.
"""

from __future__ import annotations

import json
import re
import sys

PROTEGIDOS = (
    re.compile(r"data[\\/]raw[\\/]", re.IGNORECASE),
    re.compile(r"[\\/]\.env($|[\\/\"'\s])", re.IGNORECASE),
)

FERRAMENTAS_DE_ESCRITA = (
    "edit",
    "create",
    "apply_patch",
    "insert_edit",
    "write",
    "str_replace",
    "multi_edit",
    "notebook_edit",
)


def main() -> int:
    """Lê o evento de hook no stdin e devolve o veredito em JSON (usado pelos ganchos do git)."""
    bruto = sys.stdin.read()

    try:
        evento = json.loads(bruto) if bruto.strip() else {}
    except (json.JSONDecodeError, ValueError):
        return 0  # evento ilegivel: nao atrapalha o trabalho

    ferramenta = str(evento.get("tool_name") or evento.get("toolName") or "").lower()
    if not any(nome in ferramenta for nome in FERRAMENTAS_DE_ESCRITA):
        return 0

    if not any(padrao.search(bruto) for padrao in PROTEGIDOS):
        return 0

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "Alvo protegido: data/raw/ guarda a prova do que a fonte publicou e .env "
                        "guarda segredo. Faca o tratamento em transformacao.py e leia o .env por "
                        "os.environ (config.py); para mudar a fonte, use pipeline.ps1 -Url."
                    ),
                }
            }
        )
    )
    return 0


raise SystemExit(main())
