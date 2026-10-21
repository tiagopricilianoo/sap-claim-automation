# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Modo ENSAIO pelo terminal (a interface gráfica vem depois).

Abre uma janela própria no SAP, preenche a nota, seleciona e transfere as
atividades da rota escolhida. Pula o documento ZDC e NÃO grava o claim.
Ao final, confira a janela e saia com Voltar → "Não".

Uso:
    python ensaio.py            (SAP real)
    python ensaio.py --simular  (SAP simulado, para treinar)
"""

from __future__ import annotations

import sys

from config import ConfigError, load_settings
from logger_config import configurar_logs
from models import ClaimRequest
from storage import Storage


def _perguntar_tipo(settings) -> str:
    rotas = list(settings.rotas.values())
    print("Tipo de claim:")
    for i, rota in enumerate(rotas, 1):
        print(f"  {i}) {rota.rotulo}")
    while True:
        escolha = input("Número: ").strip()
        if escolha.isdigit() and 1 <= int(escolha) <= len(rotas):
            return rotas[int(escolha) - 1].chave
        print("  Opção inválida.")


def _perguntar_texto_livre() -> str:
    print("Texto livre (termine com uma linha vazia):")
    linhas = []
    while True:
        linha = input()
        if not linha.strip():
            return "\n".join(linhas)
        linhas.append(linha)


def main() -> int:
    simular = "--simular" in sys.argv
    try:
        settings = load_settings()
    except ConfigError as erro:
        print(f"[ERRO] Configuração: {erro}")
        return 2
    configurar_logs(settings.pasta_dados)

    print("=" * 60)
    print(" ENSAIO " + ("(SAP SIMULADO)" if simular else "(SAP REAL - nada será gravado)"))
    print("=" * 60)
    req = ClaimRequest.from_form(
        tipo=_perguntar_tipo(settings),
        descricao=input("Descrição: "),
        texto_livre=_perguntar_texto_livre(),
        ordem=input("Ordem do cliente: "),
        item=input("Item da ordem: "),
        arquivo=(arquivo := input("Arquivo anexo (caminho completo; vazio = sem anexo): ")),
        sem_anexo=not arquivo.strip() and input("Confirma claim SEM anexo? (s/n): ").strip().lower() == "s",
    )

    if simular:
        from sap_fake import FakeSap
        sap = FakeSap(popups_apos_enter=["O cliente TESTE tem bloqueio de registro"])
    else:
        from sap_client import SapClient
        sap = SapClient(settings)

    from claim_service import ClaimService
    db = Storage(settings.pasta_dados / "historico.db")
    try:
        resultado = ClaimService(settings, sap, db).ensaio(req)
    finally:
        db.close()

    print("\n" + "-" * 60)
    print(f"Execução {resultado.execucao_id}: {resultado.estado.value}")
    for p in resultado.problemas:
        print(f"  [{p.campo}] {p.mensagem}")
    for aviso in resultado.avisos:
        print(f"  Aviso aceito e registrado: {aviso}")
    if resultado.grade:
        print("\nGrade de atividades (antes de Transferir):")
        for i, linha in enumerate(resultado.grade, 1):
            print(f"  {i}) " + " | ".join(f"{k}={v}" for k, v in linha.items() if v))
    if resultado.conferencias:
        print("\nConferir (texto no settings.ini diferente da grade):")
        for item in resultado.conferencias:
            print(f"  - {item}")
    print(resultado.mensagem)
    return 0 if resultado.estado.value == "ENSAIO_CONCLUIDO" else 1


if __name__ == "__main__":
    sys.exit(main())
