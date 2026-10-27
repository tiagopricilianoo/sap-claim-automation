# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""2ª banca (27/10/2026): resolução de pendência coerente com a linha e com o número informado."""

import pytest

from controlador import resolver_pendencia
from state import Estado as E
from storage import Storage


def _pendente(db, req, linha=None, incerta=False):
    eid = db.criar_execucao(req, "AUTOMATICO")
    for e in (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.REVISAO_NECESSARIA):
        db.transitar(eid, e)
    if linha and incerta:
        db.registrar_linha_incerta(eid, linha)
    elif linha:
        db.registrar_linha(eid, linha)
    return eid


def test_rev2_numero_da_ordem_nao_vale_como_nota(tmp_path, request_valido):
    db = Storage(tmp_path / "h.db")
    eid = _pendente(db, request_valido)
    with pytest.raises(ValueError, match="NOTA"):
        resolver_pendencia(db, eid, criado=True, numero_nota=request_valido.ordem)
    assert db.obter(eid).estado == E.REVISAO_NECESSARIA and db.obter(eid).numero_nota is None
    db.close()


def test_rev2_claim_criado_com_linha_incerta_confirma_a_linha(tmp_path, request_valido):
    from dataclasses import replace
    db = Storage(tmp_path / "h.db")
    req = replace(request_valido, item="", linha_nova=True)
    eid = _pendente(db, req, "20", incerta=True)
    with pytest.raises(ValueError, match="linha 20 também existe"):
        resolver_pendencia(db, eid, criado=True, numero_nota="100065700", linha_existe=False)
    resolver_pendencia(db, eid, criado=True, numero_nota="100065700")
    ex = db.obter(eid)
    assert (ex.estado, ex.item, ex.linha_criada) == (E.CONCLUIDO, "20", "20")
    assert [e.id for e in db.possiveis_duplicidades(req.ordem, "20")] == [eid]   # item 20 protegido
    db.close()


def test_rev2_reserva_confere_de_novo_na_mesma_transacao(settings, tmp_path, request_valido):
    """Outro programa começou a mesma ordem/item entre a 1ª conferência e a reserva: nada é gravado."""
    from dataclasses import replace
    from claim_service import ClaimService
    from sap_fake import FakeSap
    cfg = replace(settings, automatico_habilitado=True)
    db = Storage(tmp_path / "h.db")
    original = db.possiveis_duplicidades
    chamadas = []

    def conferencia(*a, **k):
        chamadas.append(1)
        if len(chamadas) == 1:                      # 1ª conferência: livre; logo depois o "outro" começa
            outro = db.criar_execucao(request_valido, "AUTOMATICO")
            for e in (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO):
                db.transitar(outro, e)
            return []
        return original(*a, **k)
    db.possiveis_duplicidades = conferencia
    sap = FakeSap()
    r = ClaimService(cfg, sap, db).executar(request_valido, "AUTOMATICO")
    db.close()
    assert r.estado == E.RECEBIDO and "ao mesmo tempo" in r.mensagem
    assert not getattr(sap, "chamadas", [])
