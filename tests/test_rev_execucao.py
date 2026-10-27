# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""REVISOR TESTADOR: interrupção em cada etapa, executor (concorrência), publicação."""

import threading
from dataclasses import replace

import pytest

from claim_service import ClaimService, etapas_do_modo
from controlador import Executor
from cotacao import CotacaoRequest
from cotacao_service import CotacaoService, etapas_cotacao_do_modo
from pastas import PlanoPastas
from sap_fake import FakeSap
from state import Estado as E
from storage import Storage
from storage_cotacao import CotacaoStorage


def _cfg(settings):
    return replace(settings, automatico_habilitado=True)


# ------------------------------------------------------------------ interrupção no claim

def _casos_claim():
    casos = []
    for linha in (False, True):
        for sem_anexo in (False, True):
            for etapa, _ in etapas_do_modo("AUTOMATICO", linha):
                if etapa == "documento" and sem_anexo:
                    pass
                casos.append((etapa, linha, sem_anexo))
    return casos


@pytest.mark.parametrize("parar_apos,linha_nova,sem_anexo", _casos_claim())
def test_rev_interromper_apos_cada_etapa_do_claim(settings, tmp_path, request_valido, parar_apos, linha_nova,
                                                  sem_anexo):
    cfg = _cfg(settings)
    req = request_valido
    if linha_nova:
        req = replace(req, item="", linha_nova=True)
    if sem_anexo:
        req = replace(req, arquivo=None, sem_anexo=True)
    cancelar = threading.Event()

    def progresso(etapa, situacao, detalhe):
        if etapa == parar_apos and situacao == "ok":
            cancelar.set()
    db = Storage(tmp_path / "i.db")
    sap = FakeSap()
    r = ClaimService(cfg, sap, db, progresso=progresso, cancelar=cancelar).executar(req, "AUTOMATICO")
    db.close()
    if parar_apos == "gravacao":                   # pedido depois de gravar: nada a interromper
        assert r.estado == E.CONCLUIDO
        return
    assert "gravar_nota" not in sap.chamadas, f"claim gravado apesar da parada após '{parar_apos}'"
    if sap.gravacoes and all(g.startswith("LINHA") for g in sap.gravacoes):
        # só a linha confirmada: falha comum com a linha registrada (o claim do item pode ser criado)
        assert r.estado == E.FALHA_RECUPERAVEL and r.linha_criada, (parar_apos, r.estado, sap.gravacoes)
    elif sap.gravacoes:                            # documento já gravado
        assert r.estado == E.REVISAO_NECESSARIA, (parar_apos, r.estado, sap.gravacoes)
    else:                                          # nada gravado: nada a revisar
        assert r.estado == E.FALHA_RECUPERAVEL, (parar_apos, r.estado.value, r.mensagem)


def _creq():
    return CotacaoRequest.from_form(tipo="Nacional", regiao="Sul", cliente="Usina", projeto="P1", produto_a=True,
                                    produto_b=True)


@pytest.mark.parametrize("parar_apos", [e for e, _ in etapas_cotacao_do_modo("AUTOMATICO")])
def test_rev_interromper_apos_cada_etapa_da_cotacao(settings, tmp_path, parar_apos):
    cfg = _cfg(settings)
    cancelar = threading.Event()

    def progresso(etapa, situacao, detalhe):
        if etapa == parar_apos and situacao == "ok":
            cancelar.set()
    db = CotacaoStorage(tmp_path / "c.db")
    sap = FakeSap()
    s = CotacaoService(cfg, sap, db, progresso=progresso, cancelar=cancelar)
    pastas = []
    s.criar_pastas = lambda p, n: pastas.append(n) or p.base
    plano = PlanoPastas("TU", tmp_path / "R.0", None, tmp_path, tmp_path, 2026)
    r = s.executar_cotacao(_creq(), "AUTOMATICO", plano)
    db.close()
    if parar_apos in ("gravacao", "pastas"):
        assert r.estado == E.CONCLUIDO and pastas == ["21800001"]      # depois de gravar, não para no meio
    else:
        assert r.estado == E.FALHA_RECUPERAVEL and sap.gravacoes == [], (parar_apos, r.estado)


def test_rev_interromper_durante_a_gravacao_nao_muda_o_resultado(settings, tmp_path, request_valido):
    cancelar = threading.Event()

    class Sap(FakeSap):
        def gravar_nota(self):
            cancelar.set()
            return super().gravar_nota()
    db = Storage(tmp_path / "i.db")
    r = ClaimService(_cfg(settings), Sap(), db, cancelar=cancelar).executar(request_valido, "AUTOMATICO")
    db.close()
    assert r.estado == E.CONCLUIDO and r.numero_nota


# ------------------------------------------------------------------ executor

class _Lento(FakeSap):
    liberar: threading.Event = None

    def sessao(self):
        self.liberar.wait(5)
        return super().sessao()


def _executor_lento(settings, tmp_path):
    liberar = threading.Event()

    def fabrica(c, m):
        s = _Lento()
        s.liberar = liberar
        return s
    return Executor(settings, tmp_path / "h.db", fabrica_sap=fabrica), liberar


def test_rev_claim_em_andamento_recusa_cotacao(settings, tmp_path, request_valido):
    ex, liberar = _executor_lento(settings, tmp_path)
    ex.iniciar(request_valido, "SIMULACAO")
    try:
        with pytest.raises(RuntimeError):
            ex.iniciar_cotacao(_creq(), "SIMULACAO", None)
    finally:
        liberar.set()
        ex.aguardar()


def test_rev_cotacao_em_andamento_recusa_claim(settings, tmp_path, request_valido):
    ex, liberar = _executor_lento(settings, tmp_path)
    ex.iniciar_cotacao(_creq(), "SIMULACAO", None)
    try:
        with pytest.raises(RuntimeError):
            ex.iniciar(request_valido, "SIMULACAO")
    finally:
        liberar.set()
        ex.aguardar()


def test_rev_verificar_sap_nao_roda_junto_com_execucao(settings, tmp_path, request_valido):
    """A verificação abre o motor de scripting em outra thread enquanto a automação usa o SAP."""
    ex, liberar = _executor_lento(settings, tmp_path)
    chamadas = []
    ex._verificar = lambda: chamadas.append("diagnostico")
    ex.iniciar(request_valido, "SIMULACAO")
    try:
        try:
            ex.verificar_sap()
        except RuntimeError:
            pass
        import time
        time.sleep(0.2)
    finally:
        liberar.set()
        ex.aguardar()
    assert chamadas == [], "verificação do SAP disparada durante a execução"


def test_rev_parada_de_uma_execucao_nao_vaza_para_a_proxima(settings, tmp_path, request_valido):
    ex = Executor(settings, tmp_path / "h.db", fabrica_sap=lambda c, m: FakeSap())
    ex.interromper()                                  # sem execução: nada
    ex.iniciar(request_valido, "SIMULACAO")
    ex.aguardar()
    ex.interromper()                                  # depois do fim
    ex.iniciar(request_valido, "SIMULACAO")
    ex.aguardar()
    fins = [e.resultado.estado for e in ex.drenar() if e.tipo == "fim"]
    assert fins[-1] in (E.CONCLUIDO, E.RECEBIDO)      # 2ª pode ser bloqueada por duplicidade, nunca interrompida
    assert fins[0] == E.CONCLUIDO


def test_rev_janela_mantida_so_depois_de_sucesso(settings, tmp_path, request_valido):
    class SapComJanela(FakeSap):
        manter_janela = False
        reaproveitar = None
        janela_mantida = None

        def encerrar(self):
            super().encerrar()
            self.janela_mantida = "/app/con[0]/ses[3]" if self.manter_janela else None
    from sap_gateway import StatusMessage
    cfg = _cfg(settings)
    sap_ok = SapComJanela()
    ex = Executor(cfg, tmp_path / "h.db", fabrica_sap=lambda c, m: sap_ok)
    ex.iniciar(request_valido, "AUTOMATICO")
    ex.aguardar()
    assert ex.janela_mantida == "/app/con[0]/ses[3]"
    sap_ruim = SapComJanela(status_apos_gravar=StatusMessage("", ""))
    ex._fabrica = lambda c, m: sap_ruim
    ex.iniciar(replace(request_valido, item="20"), "AUTOMATICO")
    ex.aguardar()
    assert sap_ruim.reaproveitar == "/app/con[0]/ses[3]"
    assert ex.janela_mantida is None                   # janela com claim incerto nunca é reaproveitada


# ------------------------------------------------------------------ publicação

def _publicar():
    import importlib.util
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("publicar_rev", raiz / "publicar.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m, raiz


def test_rev_pacote_de_producao_importa_sem_o_projeto(tmp_path):
    """Cada módulo do pacote importa sozinho, sem sap_fake/ensaio e sem a pasta de desenvolvimento."""
    import os
    import subprocess
    import sys
    publicar, raiz = _publicar()
    destino = tmp_path / "app"
    publicar.montar_pacote(raiz, destino, "9.9.9")
    stubs = os.environ.get("REV_STUBS", "")
    modulos = [n[:-3] for n in publicar.ARQUIVOS_DO_PROGRAMA if n.endswith(".py") and n != "ui.py"]
    codigo = "import importlib\n" + "".join(f"importlib.import_module({m!r})\n" for m in modulos)
    r = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path[:0]=[{str(destino)!r}, {stubs!r}]\n"
                        + codigo], cwd=str(destino), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]


def test_rev_settings_de_producao_sem_espacos_e_idempotente():
    publicar, _ = _publicar()
    texto = "[execucao]\nmodo=ENSAIO\nautomatico_habilitado=nao\n[armazenamento]\npasta_dados=C:\\x\n"
    prod = publicar.settings_de_producao(texto)
    assert publicar.settings_de_producao(prod) == prod
    assert "pasta_dados =\n" in prod and "C:\\x" not in prod


def test_rev_settings_de_producao_mantem_travas(tmp_path):
    from config import load_settings
    from conftest import texto_settings_padrao
    publicar, _ = _publicar()
    caminho = tmp_path / "s.ini"
    caminho.write_text(publicar.settings_de_producao(texto_settings_padrao()), encoding="utf-8")
    s = load_settings(caminho)
    assert (s.sistema, s.mandante) == ("PRD", "100")
    assert "Entrar Condições pagamento" in s.avisos_aceitos
    assert set(s.rotas) == {"PRODUTO_A", "PRODUTO_B", "PRODUTO_B_CUSTO"}


def test_rev_falha_ao_montar_mantem_a_versao_publicada(tmp_path):
    import shutil
    publicar, raiz = _publicar()
    servidor = tmp_path / "srv"
    servidor.mkdir()
    publicar.publicar(servidor, origem=raiz)
    origem = tmp_path / "origem"
    shutil.copytree(raiz, origem, ignore=shutil.ignore_patterns("__pycache__"))
    (origem / "sap_client.py").unlink()
    with pytest.raises(OSError):
        publicar.publicar(servidor, origem=origem)
    assert (servidor / "app" / "versao.txt").read_text().strip() == "1.0.0"
    assert (servidor / "app" / "sap_client.py").exists()
