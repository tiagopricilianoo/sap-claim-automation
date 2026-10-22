# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""SAP simulado: mesma interface do SAP real, sem tocar em nada.

Usado no modo SIMULACAO e nos testes. Permite provocar falhas em
qualquer etapa para testar o tratamento de erros.

Exemplo:
    sap = FakeSap(popups_apos_enter=["O cliente X tem bloqueio de registro"])
    sap = FakeSap(falhar_em={"criar_documento": ElementoNaoEncontrado("btnY1")})
    sap = FakeSap(falhar_em={"gravar_nota": ResultadoIncerto("conexão caiu")})
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from sap_gateway import (
    AtividadeSelecionada,
    Popup,
    SessaoIndisponivel,
    SessionInfo,
    StatusMessage,
)


@dataclass
class FakeSap:
    sessao_info: SessionInfo | None = field(default_factory=lambda: SessionInfo(
        sistema="PRD", mandante="100", usuario="USUARIO1", idioma="PT", transacao="SESSION_MANAGER", ocupada=False,
    ))
    popups_apos_enter: list[str] = field(default_factory=list)
    status_apos_enter: StatusMessage = field(default_factory=lambda: StatusMessage("", ""))
    falhar_em: dict[str, Exception] = field(default_factory=dict)
    proximo_documento: str = "20000263669"
    proxima_nota: str = "100063949"
    notas_existentes: set[str] = field(default_factory=set)
    grade: list[dict[str, str]] | None = None   # força o conteúdo devolvido pela grade
    status_apos_gravar: StatusMessage | None = None   # força a resposta da gravação
    atraso_s: float = 0.0                         # pausa por etapa (demonstração na interface)

    chamadas: list[str] = field(default_factory=list, init=False)
    gravacoes: list[str] = field(default_factory=list, init=False)
    atividades_recebidas: list[AtividadeSelecionada] = field(default_factory=list, init=False)
    _popups: list[Popup] = field(default_factory=list, init=False)

    # ---------------------------------------------------------------- interno

    def _passo(self, nome: str) -> None:
        self.chamadas.append(nome)
        if self.atraso_s:
            time.sleep(self.atraso_s)
        erro = self.falhar_em.get(nome)
        if erro is not None:
            raise erro

    # ---------------------------------------------------------------- contrato

    def sessao(self) -> SessionInfo:
        self._passo("sessao")
        if self.sessao_info is None:
            raise SessaoIndisponivel("SAP GUI não encontrado (simulado).", etapa="sessao")
        return self.sessao_info

    def abrir_criacao(self, tipo_nota: str) -> None:
        self._passo("abrir_criacao")

    def preencher_nota(self, **campos: str) -> None:
        self._passo("preencher_nota")

    def enter(self) -> StatusMessage:
        self._passo("enter")
        self._popups = [Popup("Informação", t) for t in self.popups_apos_enter]
        return self.status_apos_enter

    def popup_aberto(self) -> Popup | None:
        self.chamadas.append("popup_aberto")
        return self._popups[0] if self._popups else None

    def confirmar_popup(self) -> None:
        self._passo("confirmar_popup")
        if self._popups:
            self._popups.pop(0)

    def criar_documento(self, *, tipo: str, descricao: str, laboratorio: str,
                        arquivo: Path, aplicacao: str) -> str:
        self._passo("criar_documento")
        self.aplicacao_recebida = aplicacao
        self.gravacoes.append(f"DOCUMENTO {tipo} {self.proximo_documento}")
        return self.proximo_documento

    def selecionar_atividades(self, atividades: list[AtividadeSelecionada], raiz: str) -> list[dict[str, str]]:
        self._passo("selecionar_atividades")
        self.atividades_recebidas = list(atividades)
        if self.grade is not None:
            return [dict(l) for l in self.grade]
        return [{"GRUPO": "GRP", "SUB_GRUPO": a.subgrupo, "DS_ATIVIDADE": a.descricao, "RESP": a.responsavel}
                for a in atividades]

    def por_em_processamento(self) -> StatusMessage:
        self._passo("por_em_processamento")
        return StatusMessage("", "")

    def gravar_nota(self) -> StatusMessage:
        self._passo("gravar_nota")
        if self.status_apos_gravar is not None:
            return self.status_apos_gravar
        self.gravacoes.append(f"NOTA {self.proxima_nota}")
        self.notas_existentes.add(self.proxima_nota)
        return StatusMessage(
            "S", f"Nota {self.proxima_nota} gravada", parametros=(self.proxima_nota,),
        )

    def nota_existe(self, numero: str) -> bool:
        self._passo("nota_existe")
        return numero in self.notas_existentes

    def sair_sem_gravar(self) -> None:
        self._passo("sair_sem_gravar")

    def encerrar(self) -> None:
        self._passo("encerrar")
