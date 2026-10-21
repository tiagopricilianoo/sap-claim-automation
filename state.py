# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Máquina de estados de uma execução.

Regra central: depois que um comando de gravação foi enviado ao SAP,
nenhuma transição leva de volta a uma nova gravação automática.
"""

from __future__ import annotations

from enum import Enum


class Estado(str, Enum):
    RECEBIDO = "RECEBIDO"
    VALIDANDO = "VALIDANDO"
    PRONTO_PARA_EXECUCAO = "PRONTO_PARA_EXECUCAO"
    EXECUTANDO = "EXECUTANDO"
    AGUARDANDO_CONFIRMACAO = "AGUARDANDO_CONFIRMACAO"
    CONCLUIDO = "CONCLUIDO"
    ENSAIO_CONCLUIDO = "ENSAIO_CONCLUIDO"
    FALHA_RECUPERAVEL = "FALHA_RECUPERAVEL"
    FALHA_DEFINITIVA = "FALHA_DEFINITIVA"
    REVISAO_NECESSARIA = "REVISAO_NECESSARIA"


E = Estado

TRANSICOES: dict[Estado, frozenset[Estado]] = {
    E.RECEBIDO: frozenset({E.VALIDANDO}),
    # dados inválidos: volta para correção
    E.VALIDANDO: frozenset({E.PRONTO_PARA_EXECUCAO, E.RECEBIDO}),
    E.PRONTO_PARA_EXECUCAO: frozenset({E.EXECUTANDO}),
    E.EXECUTANDO: frozenset({
        E.AGUARDANDO_CONFIRMACAO,  # gravação do claim enviada
        E.FALHA_RECUPERAVEL,       # falha antes de qualquer gravação
        E.FALHA_DEFINITIVA,        # erro não recuperável antes de qualquer gravação
        E.REVISAO_NECESSARIA,      # falha depois de o documento ZDC ser gravado
        E.ENSAIO_CONCLUIDO,        # modo ensaio terminou sem gravar
    }),
    # nova tentativa (limitada) ou desistência
    E.FALHA_RECUPERAVEL: frozenset({E.PRONTO_PARA_EXECUCAO, E.FALHA_DEFINITIVA}),
    E.AGUARDANDO_CONFIRMACAO: frozenset({E.CONCLUIDO, E.REVISAO_NECESSARIA}),
    # decisão humana após conferir no SAP
    E.REVISAO_NECESSARIA: frozenset({E.CONCLUIDO, E.FALHA_DEFINITIVA}),
    E.CONCLUIDO: frozenset(),
    E.ENSAIO_CONCLUIDO: frozenset(),
    E.FALHA_DEFINITIVA: frozenset(),
}

TERMINAIS = frozenset(e for e, saidas in TRANSICOES.items() if not saidas)

# Estados que indicam que já existe (ou pode existir) um claim para a ordem/item.
BLOQUEIAM_DUPLICIDADE = frozenset({
    E.EXECUTANDO,
    E.AGUARDANDO_CONFIRMACAO,
    E.REVISAO_NECESSARIA,
    E.CONCLUIDO,
})

# Estados que exigem atenção de uma pessoa.
PENDENTES = frozenset({E.AGUARDANDO_CONFIRMACAO, E.REVISAO_NECESSARIA})


class TransicaoInvalida(Exception):
    """Tentativa de transição não prevista na máquina de estados."""


def pode_transitar(de: Estado, para: Estado) -> bool:
    return para in TRANSICOES[de]


def validar_transicao(de: Estado, para: Estado) -> None:
    if not pode_transitar(de, para):
        raise TransicaoInvalida(f"Transição não permitida: {de.value} -> {para.value}")
