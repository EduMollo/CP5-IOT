from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import Config, PROJECT_ROOT

REQUIRED_TOOLS = {"analisar_maquina", "enviar_alerta_telegram", "enviar_alerta_email"}


class ErroMCP(RuntimeError):
    pass


class ClienteMCP:
    def __init__(self, session: ClientSession, tools: list[str]):
        self.session, self.tools = session, tools

    async def chamar(self, name: str, arguments: dict) -> dict:
        result = await self.session.call_tool(name, arguments)
        if result.isError:
            details = " ".join(item.text for item in result.content if item.type == "text")
            raise ErroMCP(details or "A ferramenta MCP retornou um erro.")
        if result.structuredContent is not None:
            return result.structuredContent
        for item in result.content:
            if item.type == "text":
                return json.loads(item.text)
        raise ErroMCP("Resposta MCP sem resultado estruturado.")


@asynccontextmanager
async def conectar(config: Config):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "monitoramento.servidor_mcp"],
        cwd=str(PROJECT_ROOT), env={**os.environ, **config.mcp_environment()}, encoding="utf-8",
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=config.timeout + 5)) as session:
            await session.initialize()
            tools = [tool.name for tool in (await session.list_tools()).tools]
            if not REQUIRED_TOOLS.issubset(tools):
                raise ErroMCP("O servidor não disponibilizou as três ferramentas obrigatórias.")
            yield ClienteMCP(session, tools)
