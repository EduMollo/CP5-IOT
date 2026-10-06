from __future__ import annotations
from typing import Any
from mcp.server.fastmcp import FastMCP
from .config import Config
from .historico import Historico
from .notificacoes import Notificador
from .regras import analisar

def criar_servidor(config: Config) -> FastMCP:
    history = Historico(config.db_path)
    notifier = Notificador(config, history)
    server = FastMCP('Monitoramento Industrial', log_level='WARNING', instructions='Analise leituras e notifique somente os canais exigidos pelas regras.')

    @server.tool(description='Valida os oito campos, verifica as quatro regras e registra a análise. id_evento é um UUID opcional.')
    def analisar_maquina(dados: dict[str, Any], id_evento: str | None=None) -> dict[str, Any]:
        return history.salvar(analisar(dados), id_evento)

    @server.tool(description='Envia um alerta existente ao Telegram, respeitando a política, o modo e a deduplicação.')
    async def enviar_alerta_telegram(id_evento: str) -> dict[str, Any]:
        return await notifier.enviar(id_evento, 'telegram')

    @server.tool(description='Envia um alerta existente por e-mail somente quando há produção baixa ou fator de potência baixo.')
    async def enviar_alerta_email(id_evento: str) -> dict[str, Any]:
        return await notifier.enviar(id_evento, 'email')

    @server.tool(description='Consulta até 100 eventos e seus resultados de notificação.')
    def consultar_historico(limite: int=10, id_maquina: str | None=None, id_evento: str | None=None) -> dict[str, Any]:
        return {'eventos': history.listar(limite, id_maquina, id_evento)}

    @server.tool(description='Informa o modo e os nomes de variáveis pendentes, sem retornar credenciais.')
    def verificar_configuracao() -> dict[str, Any]:
        return {'modo': config.mode, 'telegram_pendente': config.missing('telegram'), 'email_pendente': config.missing('email'), 'intervalo_alertas_segundos': config.cooldown}
    return server

def main() -> None:
    criar_servidor(Config.load()).run(transport='stdio')
if __name__ == '__main__':
    main()
