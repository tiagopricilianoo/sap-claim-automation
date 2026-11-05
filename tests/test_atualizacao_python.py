# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Aviso de atualização do Python do programa (05/11/2026): detectar, baixar com progresso, trocar."""

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
