# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Contrato entre a orquestração e o SAP.

O SAP real (sap_client.py, Entrega 2 em diante) e o SAP simulado
(sap_fake.py) implementam a mesma interface. Assim, toda a lógica de
negócio pode ser testada sem tocar no SAP.

Somente as implementações conhecem IDs técnicos de tela.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


# ---------------------------------------------------------------- dados

@dataclass(frozen=True)
class SessionInfo:
    sistema: str
    mandante: str
    usuario: str
    idioma: str
    transacao: str
    ocupada: bool


@dataclass(frozen=True)
class StatusMessage:
    """Barra de status do SAP. tipo: S=sucesso, W=aviso, E=erro, A=cancelamento, I=info, ''=vazia."""
    tipo: str
    texto: str
    id_mensagem: str = ""
    numero_mensagem: str = ""
    parametros: tuple[str, ...] = ()

    @property
    def e_erro(self) -> bool:
        return self.tipo in ("E", "A")


@dataclass(frozen=True)
class Popup:
    """Janela modal (wnd[1]) aberta sobre a tela principal."""
    titulo: str
    texto: str


@dataclass(frozen=True)
class AtividadeSelecionada:
    """Atividade já resolvida para execução (responsável final calculado)."""
    descricao: str
    subgrupo: str
    pasta: str
    no: str
    responsavel: str  # "" = deixar o SAP preencher


@dataclass(frozen=True)
class LinhaPreenchida:
    """Linha nova da cotação, lida da tela DEPOIS do Enter (ainda não gravada)."""
    item: str
    material: str
    centro: str
    status: StatusMessage


# ---------------------------------------------------------------- erros

class SapError(Exception):
    """Erro de interação com o SAP. `etapa` indica onde aconteceu."""

    def __init__(self, mensagem: str, etapa: str = ""):
        super().__init__(mensagem)
        self.etapa = etapa


class SessaoIndisponivel(SapError):
    """SAP fechado, sem sessão, sessão ocupada ou expirada. Nada foi feito."""


class SistemaIncorreto(SapError):
    """Sessão em sistema ou mandante diferente do configurado. Nada foi feito."""


class ElementoNaoEncontrado(SapError):
    """Campo, botão ou nó esperado não existe na tela."""


class ValorRejeitado(SapError):
    """O SAP recusou um valor (mensagem de erro na barra de status). Nada foi gravado."""


class PopupInesperado(SapError):
    """Janela não prevista na lista de avisos aceitos."""


class ResultadoIncerto(SapError):
    """O comando de gravação pode ter sido executado, mas não há confirmação.

    Nunca tratar como sucesso nem repetir a gravação automaticamente.
    """


# ---------------------------------------------------------------- contrato

class SapGateway(Protocol):
    def sessao(self) -> SessionInfo: ...

    # ---- cotação (VA22): linha nova antes do claim
    def abrir_cotacao(self, cotacao: str) -> None:
        """VA22 -> número da cotação -> Enter (abre a lista de itens). Não grava."""

    def preencher_linha(self, *, material: str, centro: str, quantidade: str) -> LinhaPreenchida:
        """Acrescenta a linha no próximo item livre, confirma com Enter e confere. Não grava."""

    def gravar_cotacao(self, cotacao: str) -> StatusMessage:
        """GRAVA a cotação ("Gravar documento incompleto" -> Gravar). Pode levantar ResultadoIncerto."""

    # ---- cotação nova (VA21)
    def iniciar_cotacao(self, *, tipo_documento: str, organizacao: str, canal: str, setor: str,
                        escritorio: str, equipe: str) -> None: ...

    def preencher_cliente(self, *, emissor: str, titulo: str, nome: str, cidade: str,
                          codigo_postal: str) -> Popup | None: ...

    def preencher_validade(self, *, validade: str, referencia: str) -> StatusMessage: ...

    def preencher_linhas_novas(self, linhas: list[tuple[str, str, str]]) -> list[LinhaPreenchida]: ...

    def preencher_cabecalho(self, *, utilizacao: str, data: str, hora: str) -> StatusMessage: ...

    def gravar_cotacao_nova(self) -> StatusMessage:
        """GRAVA a cotação nova. Pode levantar ResultadoIncerto."""

    # ---- claim (CLM1)
    def abrir_criacao(self, tipo_nota: str) -> None:
        """CLM1 -> tipo de nota -> Enter (abre a tela principal da nota)."""

    def preencher_nota(
        self,
        *,
        descricao: str,
        texto_livre: str,
        causa_grupo: str,
        causa_codigo: str,
        prioridade: str,
        ordem: str,
        item: str,
    ) -> None: ...

    def enter(self) -> StatusMessage: ...

    def popup_aberto(self) -> Popup | None: ...

    def confirmar_popup(self) -> None: ...

    def criar_documento(
        self,
        *,
        tipo: str,
        descricao: str,
        laboratorio: str,
        arquivo: Path,
        aplicacao: str,
    ) -> str:
        """Cria, arquiva e GRAVA o documento. Retorna o número do documento."""

    def selecionar_atividades(
        self, atividades: list[AtividadeSelecionada], raiz: str
    ) -> list[dict[str, str]]:
        """Seleciona as atividades na ordem, preenche responsáveis e transfere.

        Retorna a grade lida antes de transferir (uma linha por atividade,
        coluna técnica -> valor), para conferência e registro.
        Nada é gravado: as atividades só vão ao banco junto com o claim.
        """

    def por_em_processamento(self) -> StatusMessage:
        """Bandeira verde "Pôr em processamento". Não grava: só muda o status da nota na tela."""

    def gravar_nota(self) -> StatusMessage:
        """GRAVA o claim. Pode levantar ResultadoIncerto."""

    def nota_existe(self, numero: str) -> bool:
        """Consulta somente leitura (CLM3)."""

    def sair_sem_gravar(self) -> None: ...

    def encerrar(self) -> None:
        """Fecha a janela da automação (nunca as do usuário)."""
