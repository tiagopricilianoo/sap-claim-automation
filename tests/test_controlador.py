# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
import threading

import pytest

from claim_service import etapas_do_modo
from controlador import (
    Executor,
    erros_por_campo,
    linha_historico,
    montar_request,
    pendencias,
    resumo_arquivo,
    validar_formulario,
)
from sap_fake import FakeSap
from state import Estado as E
from storage import Storage


def _campos(arquivo):
    return {"tipo": "PRODUTO_A", "descricao": "Teste", "texto_livre": "linha", "ordem": "1234567",
            "item": "10", "arquivo": str(arquivo)}


def test_formulario_valido(settings, arquivo_pdf):
    assert validar_formulario(_campos(arquivo_pdf), settings) == {}


def test_formulario_mapeia_erros_por_campo(settings, arquivo_pdf):
    erros = validar_formulario({**_campos(arquivo_pdf), "ordem": "abc", "tipo": ""}, settings)
    assert set(erros) == {"ordem", "tipo"}


def test_primeiro_erro_de_cada_campo():
    from validators import ValidationIssue
    erros = erros_por_campo([ValidationIssue("a", "1"), ValidationIssue("a", "2"), ValidationIssue("b", "3")])
    assert erros == {"a": "1", "b": "3"}


def test_resumo_arquivo(tmp_path):
    arq = tmp_path / "proposta.pdf"
    arq.write_bytes(b"x" * 1536)
    assert resumo_arquivo(str(arq)) == "proposta.pdf · 1,5 KB"
    assert resumo_arquivo(str(tmp_path / "nao_existe.pdf")) == ""


def test_montar_request_normaliza(arquivo_pdf):
    req = montar_request({**_campos(arquivo_pdf), "descricao": "  x  "})
    assert req.descricao == "x"


def _executor(settings, tmp_path, **fake):
    def fabrica(cfg, modo):
        return FakeSap(**fake)
    return Executor(settings, tmp_path / "h.db", fabrica_sap=fabrica)


def test_execucao_em_segundo_plano_emite_todas_as_etapas(settings, tmp_path, request_valido):
    ex = _executor(settings, tmp_path, popups_apos_enter=["O cliente X tem bloqueio de registro"])
    ex.iniciar_ensaio(request_valido, "SIMULACAO")
    ex.aguardar()
    eventos = ex.drenar()
    concluidas = [e.etapa for e in eventos if e.tipo == "etapa" and e.situacao == "ok"]
    assert concluidas == [chave for chave, _ in etapas_do_modo("SIMULACAO")]
    fim = eventos[-1]
    assert fim.tipo == "fim" and fim.resultado.estado == E.CONCLUIDO


def test_falha_aparece_na_etapa_certa(settings, tmp_path, request_valido):
    ex = _executor(settings, tmp_path, popups_apos_enter=["Janela estranha"])
    ex.iniciar_ensaio(request_valido, "SIMULACAO")
    ex.aguardar()
    eventos = ex.drenar()
    falhas = [e.etapa for e in eventos if e.situacao == "falha"]
    assert falhas == ["avisos"]
    assert eventos[-1].resultado.estado == E.FALHA_RECUPERAVEL


def test_interromper_entre_etapas(settings, tmp_path, request_valido):
    liberar = threading.Event()

    class SapLento(FakeSap):
        def sessao(self):
            info = super().sessao()
            liberar.wait(5)       # segura a execução na etapa "sessao"
            return info

    ex = Executor(settings, tmp_path / "h.db", fabrica_sap=lambda c, m: SapLento())
    ex.iniciar_ensaio(request_valido, "SIMULACAO")
    ex.interromper()
    liberar.set()
    ex.aguardar()
    resultado = ex.drenar()[-1].resultado
    assert resultado.estado == E.FALHA_RECUPERAVEL
    assert "Interrompido" in resultado.mensagem


def test_nao_aceita_duas_execucoes(settings, tmp_path, request_valido):
    liberar = threading.Event()

    class SapLento(FakeSap):
        def sessao(self):
            liberar.wait(5)
            return super().sessao()

    ex = Executor(settings, tmp_path / "h.db", fabrica_sap=lambda c, m: SapLento())
    ex.iniciar_ensaio(request_valido, "SIMULACAO")
    with pytest.raises(RuntimeError):
        ex.iniciar_ensaio(request_valido, "SIMULACAO")
    liberar.set()
    ex.aguardar()


def test_modo_automatico_nao_existe_na_interface(settings, tmp_path, request_valido):
    with pytest.raises(ValueError):
        _executor(settings, tmp_path).iniciar_ensaio(request_valido, "AUTOMATICO")


def test_erro_inesperado_vira_evento(settings, tmp_path, request_valido):
    def fabrica(cfg, modo):
        raise RuntimeError("quebrou")
    ex = Executor(settings, tmp_path / "h.db", fabrica_sap=fabrica)
    ex.iniciar_ensaio(request_valido, "SIMULACAO")
    ex.aguardar()
    assert ex.drenar()[-1].tipo == "erro"


def test_historico_e_pendencias(tmp_path, request_valido):
    db = Storage(tmp_path / "h.db")
    ok = db.criar_execucao(request_valido, "ENSAIO")
    for estado in (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.ENSAIO_CONCLUIDO):
        db.transitar(ok, estado)
    travada = db.criar_execucao(request_valido, "ENSAIO")
    for estado in (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO):
        db.transitar(travada, estado)
    invalida = db.criar_execucao(request_valido, "ENSAIO")   # parada em RECEBIDO: não é pendência

    linha = linha_historico(db.obter(ok))
    assert linha[1] == "Ensaio concluído" and linha[3] == "1234567/10"
    assert [e.id for e in pendencias(db)] == [travada]
    assert invalida not in [e.id for e in pendencias(db)]
    db.close()


def test_modos_com_gravacao_so_quando_habilitado(settings):
    from dataclasses import replace
    from controlador import modos_da_interface
    assert modos_da_interface(settings) == ("SIMULACAO", "ENSAIO")
    assert modos_da_interface(replace(settings, automatico_habilitado=True)) == \
        ("SIMULACAO", "ENSAIO", "ASSISTIDO", "AUTOMATICO")


def test_executor_recusa_gravar_sem_habilitar(settings, tmp_path, request_valido):
    with pytest.raises(ValueError):
        _executor(settings, tmp_path).iniciar(request_valido, "AUTOMATICO")


# ---------------------------------------------------------------- resolução de pendências

def _pendente(db, req, ate):
    eid = db.criar_execucao(req, "ASSISTIDO")
    for estado in (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO) + ate:
        db.transitar(eid, estado)
    return eid


def test_resolver_como_criado(tmp_path, request_valido):
    from controlador import resolver_pendencia
    db = Storage(tmp_path / "h.db")
    eid = _pendente(db, request_valido, (E.REVISAO_NECESSARIA,))
    resolver_pendencia(db, eid, criado=True, numero_nota="100065700")
    ex = db.obter(eid)
    assert (ex.estado, ex.numero_nota) == (E.CONCLUIDO, "100065700")
    assert pendencias(db) == []
    assert db.possiveis_duplicidades(request_valido.ordem, request_valido.item)   # continua bloqueando
    db.close()


def test_resolver_como_nao_criado_libera_a_ordem(tmp_path, request_valido):
    from controlador import resolver_pendencia
    db = Storage(tmp_path / "h.db")
    for ate in ((E.REVISAO_NECESSARIA,), (E.AGUARDANDO_CONFIRMACAO,), ()):
        _pendente(db, request_valido, ate)
    for ex in pendencias(db):
        resolver_pendencia(db, ex.id, criado=False)
    assert pendencias(db) == []
    assert db.possiveis_duplicidades(request_valido.ordem, request_valido.item) == []
    db.close()


def test_resolver_exige_numero_valido(tmp_path, request_valido):
    from controlador import resolver_pendencia
    db = Storage(tmp_path / "h.db")
    eid = _pendente(db, request_valido, (E.REVISAO_NECESSARIA,))
    for ruim in ("", "abc", "４２３"):
        with pytest.raises(ValueError):
            resolver_pendencia(db, eid, criado=True, numero_nota=ruim)
    assert db.obter(eid).estado == E.REVISAO_NECESSARIA
    db.close()


def test_nao_resolve_execucao_finalizada(tmp_path, request_valido):
    from controlador import resolver_pendencia
    db = Storage(tmp_path / "h.db")
    eid = _pendente(db, request_valido, (E.ENSAIO_CONCLUIDO,))
    with pytest.raises(ValueError, match="não está pendente"):
        resolver_pendencia(db, eid, criado=False)
    db.close()


def test_formulario_sem_anexo(settings, arquivo_pdf):
    campos = {**_campos(arquivo_pdf), "arquivo": "", "sem_anexo": True}
    assert montar_request(campos).sem_anexo is True
    assert validar_formulario(campos, settings) == {}
