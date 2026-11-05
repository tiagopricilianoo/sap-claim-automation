# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Aviso de atualização do Python do programa (05/11/2026): detectar, baixar com progresso, trocar."""

from pathlib import Path
import atualizacao_python as ap


def _cenario(tmp_path, runtime_local="3.15 | publicado 1", runtime_servidor="3.15 | publicado 2"):
    servidor = tmp_path / "srv"
    (servidor / "app").mkdir(parents=True)
    py_srv = servidor / "python"
    (py_srv / "Lib" / "site-packages" / "PySide6").mkdir(parents=True)
    (py_srv / "pythonw.exe").write_bytes(b"MZ" * 10)
    (py_srv / "Lib" / "site-packages" / "PySide6" / "QtCore.pyd").write_bytes(b"x" * 5000)
    (py_srv / "runtime.txt").write_text(runtime_servidor + "\n", encoding="utf-8")
    local = tmp_path / "AutomacaoClaims"
    (local / "app").mkdir(parents=True)
    (local / "python").mkdir()
    (local / "python" / "pythonw.exe").write_bytes(b"MZ")
    (local / "python" / "runtime.txt").write_text(runtime_local + "\n", encoding="utf-8")
    (local / "atualizacao.ini").write_text(f"[atualizacao]\norigem = {servidor / 'app'}\n", encoding="utf-8")
    return ap.locais(str(local / "python" / "pythonw.exe"), local / "app")


def test_desenvolvimento_nao_oferece(tmp_path):
    assert ap.locais(str(tmp_path / "outro" / "python.exe"), tmp_path / "app") is None
    assert not ap.disponivel(None)


def test_detecta_python_novo_no_servidor(tmp_path):
    l = _cenario(tmp_path)
    assert l.servidor == tmp_path / "srv" / "python"
    assert ap.disponivel(l)
    assert not ap.disponivel(_cenario(tmp_path / "igual", "x", "x"))      # mesmo Python: nada a fazer


def test_baixar_com_progresso_e_marcar_completo(tmp_path):
    l = _cenario(tmp_path)
    passos = []
    assert ap.baixar(l, lambda f, t: passos.append((f, t)))
    assert passos[-1][0] == passos[-1][1] > 0                               # chegou a 100%
    assert (l.novo / "Lib" / "site-packages" / "PySide6" / "QtCore.pyd").exists()
    assert ap.pronto_para_trocar(l)
    assert not ap.disponivel(l)                    # já baixado: não pergunta de novo, só falta reiniciar
    assert (l.python / "runtime.txt").read_text().strip() == "3.15 | publicado 1"   # o atual não mudou


def test_cancelar_nao_deixa_meia_copia(tmp_path):
    l = _cenario(tmp_path)
    assert not ap.baixar(l, cancelar=lambda: True)
    assert not l.novo.exists() and not ap.pronto_para_trocar(l)


def test_servidor_sem_python_completo_nao_oferece(tmp_path):
    l = _cenario(tmp_path)
    (l.servidor / "pythonw.exe").unlink()
    assert not ap.disponivel(l)


def test_script_de_troca_espera_o_programa_e_devolve_se_falhar(tmp_path):
    l = _cenario(tmp_path)
    script = ap.preparar_troca(l, pid=4321).read_text(encoding="cp1252")
    assert 'PID eq 4321' in script
    assert 'move "%LOCAL%\\python" "%LOCAL%\\python_antigo"' in script
    assert 'move "%LOCAL%\\python_antigo" "%LOCAL%\\python"' in script          # rollback
    assert str(l.local) in script and "iniciar.py" in script


def test_script_de_troca_nao_fica_em_laco_e_registra(tmp_path):
    """Troca que falha não pode reabrir o programa já pedindo a troca de novo (bug do 1.0.11)."""
    l = _cenario(tmp_path)
    script = ap.preparar_troca(l, pid=4321)
    texto = script.read_text(encoding="cp1252")
    assert script.name == "trocar_python_4321.cmd"                       # um script por processo
    assert script.read_bytes().count(b"\r\n") >= 30                      # CRLF: o cmd lê o .cmd certo
    assert "troca_python.log" in texto and "tentativa" in texto          # registro e novas tentativas
    desistir = texto.split(":desistir", 1)[1]
    assert 'del "%LOCAL%\\python_novo\\copia_completa.txt"' in desistir  # sem marca, não repete sozinho
    assert "timeout /t" not in texto                                     # timeout falha sem console
    assert "(\n" not in texto.split(":espera", 1)[1]                    # sem blocos: %n%/%t% atualizam


class _Troca:
    """Troca atributos e devolve no fim (sem depender do monkeypatch)."""

    def __init__(self, *trocas):
        self.trocas, self.antes = trocas, []

    def __enter__(self):
        for alvo, nome, valor in self.trocas:
            self.antes.append((alvo, nome, getattr(alvo, nome, _Troca)))
            setattr(alvo, nome, valor)

    def __exit__(self, *_):
        for alvo, nome, valor in reversed(self.antes):
            if valor is _Troca:
                delattr(alvo, nome)
            else:
                setattr(alvo, nome, valor)


def test_disparo_sem_janela_piscando_e_com_marca(tmp_path):
    import subprocess
    l = _cenario(tmp_path)
    chamadas = []
    with _Troca((subprocess, "Popen", lambda *a, **k: chamadas.append((a, k))),
                (subprocess, "DETACHED_PROCESS", 0x8), (subprocess, "CREATE_NO_WINDOW", 0x8000000)):
        ap.reiniciar_com_python_novo(l)
    flags = chamadas[0][1]["creationflags"]
    assert flags & 0x8000000 and not flags & 0x8          # console oculto, nunca desanexado
    assert ap.troca_recente(l) and not ap.troca_recente(l, segundos=-1)


def test_iniciar_nao_dispara_troca_repetida(tmp_path):
    import importlib.util
    import os
    import sys
    raiz = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("iniciar_teste_troca", raiz / "distribuicao" / "iniciar.py")
    ini = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ini)
    l = _cenario(tmp_path)
    assert ap.baixar(l)
    disparos = []
    with _Troca((ap, "locais", lambda **k: l), (ap, "reiniciar_com_python_novo", lambda x: disparos.append(x))):
        sys.modules["atualizacao_python"] = ap
        (l.local / ap.TENTATIVA).write_text("1")              # disparada agora há pouco
        assert ini._trocar_python_se_pronto() is False and not disparos
        os.utime(l.local / ap.TENTATIVA, (1, 1))              # antiga
        assert ini._trocar_python_se_pronto() is True and disparos
