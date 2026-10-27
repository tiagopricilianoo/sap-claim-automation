# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
import sqlite3

import pytest

from state import TERMINAIS, TRANSICOES, Estado as E, TransicaoInvalida, pode_transitar
from storage import Storage


# ------------------------------------------------------------ máquina de estados

def test_todos_os_estados_tem_regra():
    assert set(TRANSICOES) == set(E)


def test_terminais():
    assert TERMINAIS == {E.CONCLUIDO, E.ENSAIO_CONCLUIDO, E.FALHA_DEFINITIVA}


@pytest.mark.parametrize("de,para", [
    (E.AGUARDANDO_CONFIRMACAO, E.EXECUTANDO),
    (E.AGUARDANDO_CONFIRMACAO, E.PRONTO_PARA_EXECUCAO),
    (E.REVISAO_NECESSARIA, E.EXECUTANDO),
    (E.REVISAO_NECESSARIA, E.PRONTO_PARA_EXECUCAO),
    (E.CONCLUIDO, E.EXECUTANDO),
])
def test_nada_volta_a_gravar_depois_do_envio(de, para):
    assert not pode_transitar(de, para)


def test_nenhum_caminho_de_aguardando_chega_em_executando():
    """Busca em todo o grafo: a partir do envio, EXECUTANDO é inalcançável."""
    alcancados, fila = set(), [E.AGUARDANDO_CONFIRMACAO]
    while fila:
        atual = fila.pop()
        for proximo in TRANSICOES[atual]:
            if proximo not in alcancados:
                alcancados.add(proximo)
                fila.append(proximo)
    assert E.EXECUTANDO not in alcancados
    assert E.PRONTO_PARA_EXECUCAO not in alcancados


# ------------------------------------------------------------ histórico

@pytest.fixture
def db(tmp_path):
    s = Storage(tmp_path / "dados" / "historico.db")
    yield s
    s.close()


def _caminho_feliz(db, eid):
    for estado in (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.AGUARDANDO_CONFIRMACAO, E.CONCLUIDO):
        db.transitar(eid, estado)


def test_ciclo_completo(db, request_valido):
    eid = db.criar_execucao(request_valido, "SIMULACAO")
    db.registrar_sessao(eid, "USUARIO1", "PRD", "100")
    _caminho_feliz(db, eid)
    db.registrar_documento(eid, "20000263669")
    db.registrar_nota(eid, "100063949")

    ex = db.obter(eid)
    assert ex.estado == E.CONCLUIDO
    assert (ex.documento_dms, ex.numero_nota) == ("20000263669", "100063949")
    assert ex.arquivo_nome == "Proposta_teste.pdf" and ex.arquivo_bytes > 0
    assert ex.fim_em is not None and ex.duracao_segundos >= 0

    tipos = [e.tipo for e in db.eventos(eid)]
    assert tipos[0] == "CRIACAO" and tipos.count("TRANSICAO") == 5
    assert "DOCUMENTO_ZDC" in tipos and "NOTA" in tipos


def test_transicao_invalida_nao_altera_nada(db, request_valido):
    eid = db.criar_execucao(request_valido, "SIMULACAO")
    eventos_antes = len(db.eventos(eid))
    with pytest.raises(TransicaoInvalida):
        db.transitar(eid, E.CONCLUIDO)
    assert db.obter(eid).estado == E.RECEBIDO
    assert len(db.eventos(eid)) == eventos_antes


def test_execucao_inexistente(db):
    with pytest.raises(KeyError):
        db.transitar("NAOEXISTE", E.VALIDANDO)
    with pytest.raises(KeyError):
        db.registrar_nota("NAOEXISTE", "1")


def test_duplicidade_por_ordem_item(db, request_valido):
    primeira = db.criar_execucao(request_valido, "AUTOMATICO")
    assert db.possiveis_duplicidades("1234567", "10") == []   # só RECEBIDO: não bloqueia
    _caminho_feliz(db, primeira)

    assert [e.id for e in db.possiveis_duplicidades("1234567", "10")] == [primeira]
    assert db.possiveis_duplicidades("1234567", "20") == []
    assert db.possiveis_duplicidades("1234567", "10", ignorar_id=primeira) == []


def test_simulacao_so_bloqueia_outra_simulacao(db, request_valido):
    # Revisão de 27/10/2026: uma simulação nunca gravou no SAP e não pode barrar o claim real.
    sim = db.criar_execucao(request_valido, "SIMULACAO")
    _caminho_feliz(db, sim)
    assert db.possiveis_duplicidades("1234567", "10", modo="AUTOMATICO") == []
    assert [e.id for e in db.possiveis_duplicidades("1234567", "10", modo="SIMULACAO")] == [sim]


def test_ensaio_nao_conta_como_duplicidade(db, request_valido):
    eid = db.criar_execucao(request_valido, "ENSAIO")
    for estado in (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.ENSAIO_CONCLUIDO):
        db.transitar(eid, estado)
    assert db.possiveis_duplicidades("1234567", "10") == []


def test_pendentes_e_nao_finalizadas(db, request_valido):
    interrompida = db.criar_execucao(request_valido, "SIMULACAO")
    db.transitar(interrompida, E.VALIDANDO)

    incerta = db.criar_execucao(request_valido, "SIMULACAO")
    for estado in (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.AGUARDANDO_CONFIRMACAO):
        db.transitar(incerta, estado)

    assert [e.id for e in db.pendentes()] == [incerta]
    assert {e.id for e in db.nao_finalizadas()} == {interrompida, incerta}


def test_nao_guarda_texto_livre(tmp_path, request_valido):
    caminho = tmp_path / "h.db"
    s = Storage(caminho)
    s.criar_execucao(request_valido, "SIMULACAO")
    s.close()
    bruto = caminho.read_bytes() + (tmp_path / "h.db-wal").read_bytes() if (tmp_path / "h.db-wal").exists() else caminho.read_bytes()
    assert b"Linha 1" not in bruto
    colunas = [c[1] for c in sqlite3.connect(caminho).execute("PRAGMA table_info(execucoes)")]
    assert "texto_livre" not in colunas and "descricao" not in colunas


def test_falha_registrada(db, request_valido):
    eid = db.criar_execucao(request_valido, "SIMULACAO")
    db.registrar_falha(eid, "criar_documento", "btnY1 não encontrado")
    ex = db.obter(eid)
    assert (ex.etapa_falha, ex.mensagem_tecnica) == ("criar_documento", "btnY1 não encontrado")
