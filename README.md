# Monitoramento Inteligente de uma Máquina Industrial

Sistema em Python que recebe sensores por MQTT, utiliza um servidor MCP e um agente baseado em regras, classifica a máquina e envia alertas ao Telegram e por e-mail.

## Executar no Windows

Requisito: Python 3.12 ou superior. Abra o PowerShell na pasta do projeto e execute:

1. Instalar dependências: `.\Executar.cmd -Acao Instalar`
2. Demonstrar os três cenários: `.\Executar.cmd -Acao Demo`
3. Executar os testes: `.\Executar.cmd -Acao Testar`

`Demo` inicia MQTT e MCP reais e simula as notificações em arquivos locais. `Executar.cmd` permite iniciar o projeto com a política padrão do PowerShell; a permissão de scripts vale somente para o processo iniciado.

## Dados recebidos

Publicação no tópico `industria/maquinas/MOTOR_01/sensores`, com QoS 1 e sem retenção:

```json
{
  "id_maquina": "MOTOR_01",
  "temperatura": 86.5,
  "vibracao": 8.2,
  "tensao": 220,
  "corrente": 18.5,
  "fator_potencia": 0.62,
  "taxa_producao": 42,
  "taxa_producao_esperada": 60
}
```

Os oito campos são obrigatórios. Os sensores devem conter números finitos; a produção esperada deve ser positiva e o fator de potência deve estar entre 0 e 1. O ID da máquina deve corresponder ao tópico. Leituras inválidas são rejeitadas e o monitor continua recebendo dados.

## Classificação e decisão

| Condição | Problema |
|---|---|
| Temperatura maior que 80 °C | Temperatura elevada |
| Vibração maior que 7 | Vibração elevada |
| Fator de potência menor que 0,70 | Fator de potência baixo |
| Produção inferior a 80% da esperada | Produção abaixo do esperado |

Sem problemas, a situação é `NORMAL`. Uma ou mais condições produzem `ALERTA`, com a lista completa de problemas e uma recomendação de inspeção. Valores exatamente nos limites não acionam alertas. Tensão e corrente são recebidas e registradas.

O agente recebe a leitura por MQTT, solicita a análise ao servidor MCP, identifica os canais exigidos e apresenta o resultado. Temperatura ou vibração acionam Telegram. Produção ou fator de potência acionam Telegram e e-mail. A falha em um canal permite continuar a tentativa do outro.

O sistema registra eventos e notificações em SQLite. O UUID opcional `id_leitura` evita notificações duplicadas de uma mesma publicação. `ALERT_COOLDOWN_SECONDS` controla a repetição do mesmo conjunto de problemas por máquina, com padrão de 300 segundos.

## Servidor MCP

O cliente utiliza o SDK oficial MCP, descobre as ferramentas e comunica-se por stdio com um servidor em outro processo.

| Ferramenta | Função |
|---|---|
| `analisar_maquina` | Validar, classificar e registrar a leitura |
| `enviar_alerta_telegram` | Enviar ou simular o alerta no Telegram |
| `enviar_alerta_email` | Enviar ou simular o alerta por SMTP |
| `consultar_historico` | Consultar eventos e notificações |
| `verificar_configuracao` | Informar modo e campos pendentes sem exibir credenciais |

O agente inicia o servidor automaticamente. Para confirmar a descoberta das ferramentas, execute `.\Executar.cmd -Acao Verificar`.

## Configuração MQTT

`Instalar` cria `.env` a partir de `.env.example`. Edite com `notepad .env`.

```dotenv
MQTT_HOST=127.0.0.1
MQTT_PORT=1883
MQTT_PREFIX=industria/maquinas
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_TLS=false
```

O broker incluído escuta somente no computador local. Para exigir autenticação, escolha um usuário e uma senha, preencha os dois campos e reinicie o broker. Monitor e simulador utilizam as mesmas credenciais. Ambos vazios permitem acesso sem autenticação.

Abra três terminais na pasta do projeto:

| Terminal | Comando |
|---|---|
| 1 | `.\Executar.cmd -Acao Broker` |
| 2 | `.\Executar.cmd -Acao Monitorar` |
| 3 | `.\Executar.cmd -Acao Simular` |

Aguarde `Assinatura MQTT confirmada` no terminal 2 antes de executar o simulador. O monitor assina `industria/maquinas/+/sensores`. Ctrl+C encerra cada processo.

Para outro broker, configure host, porta, credenciais e TLS conforme o servidor e execute `Monitorar` e `Simular`. O broker local não oferece TLS.

Os arquivos de `exemplos/` podem ser editados para publicar outras leituras. Para enviar um arquivo JSON:

`powershell -NoProfile -ExecutionPolicy Bypass -Command { & .\Executar.ps1 -Acao Simular -Argumentos @('--arquivo','exemplos/normal.json') }`

## Telegram e e-mail

### Telegram

1. Abra o [BotFather](https://t.me/BotFather), envie `/newbot` e crie um bot.
2. Preencha `TELEGRAM_BOT_TOKEN` com o token fornecido.
3. Abra uma conversa com seu bot e envie `/start`.
4. No navegador, abra `https://api.telegram.org/botSEU_TOKEN/getUpdates`, substituindo `SEU_TOKEN`.
5. Preencha `TELEGRAM_CHAT_ID` com o número de `message.chat.id`.

### Gmail SMTP

Ative a verificação em duas etapas na conta remetente e gere uma [senha de app](https://myaccount.google.com/apppasswords). Use essa senha no campo `SMTP_PASSWORD`, conforme a [orientação do Google](https://support.google.com/accounts/answer/185833).

```dotenv
NOTIFICATION_MODE=real
TELEGRAM_BOT_TOKEN=TOKEN_DO_SEU_BOT
TELEGRAM_CHAT_ID=ID_DA_CONVERSA
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=seuemail@gmail.com
SMTP_PASSWORD='SUA_SENHA_DE_APP'
EMAIL_FROM=seuemail@gmail.com
EMAIL_TO=destinatario@example.com
```

Remetente e usuário SMTP devem corresponder à conta Gmail que envia. O destinatário pode ser o mesmo endereço. Consulte os [parâmetros SMTP do Gmail](https://knowledge.workspace.google.com/admin/gmail/send-email-from-a-printer-scanner-or-app). A disponibilidade de senhas de app depende da conta. Para outros provedores, esta versão aceita usuário/senha, `starttls` ou `ssl`; autenticação exclusivamente OAuth requer adaptação.

Salve o `.env` e reinicie o monitor após alterações. Para testar os envios, execute `.\Executar.cmd -Acao DemoReal`. Essa ação usa um broker temporário em uma porta disponível e deve enviar duas mensagens no Telegram e um e-mail. Para testar as credenciais MQTT configuradas, utilize os três terminais.

| Status | Significado |
|---|---|
| `SIMULADO` | Mensagem salva localmente |
| `ACEITO_PELO_SERVICO` | Serviço aceitou o envio; confira o recebimento |
| `CONFIGURACAO_PENDENTE` | Faltam dados no `.env` |
| `FALHA` | Conexão ou envio recusado |
| `INCERTO` | Sem confirmação; confira o destino antes de repetir |
| `SUPRIMIDO` | Alerta repetido dentro do intervalo configurado |
| `EM_ENVIO` | Tentativa reservada |
| `NAO_APLICAVEL` | Canal não exigido para o evento |

As credenciais reais devem ser preenchidas localmente. O arquivo `.env.example` acompanha a entrega sem dados pessoais.

## Testes e evidências

| Cenário | Temperatura | Vibração | Fator de potência | Produção/esperada | Situação | Canais |
|---|---:|---:|---:|---:|---|---|
| Normal | 65 | 3 | 0,92 | 58/60 | NORMAL | Nenhum |
| Temperatura/vibração | 86,5 | 8,2 | 0,92 | 60/60 | ALERTA | Telegram |
| Produção/fator de potência | 70 | 4 | 0,62 | 42/60 | ALERTA | Telegram e e-mail |

A demonstração real foi executada em 05/10/2026. O Telegram aceitou duas mensagens e o SMTP do Gmail aceitou um e-mail. O usuário confirmou o funcionamento dos envios.

- [Relatório da demonstração real](resultados/demonstracao_real/resultado.md)
- [Resultados estruturados](resultados/demonstracao_real/resultado.json)
- [Registro dos testes automatizados](resultados/testes-automatizados.xml)

Os 56 testes verificam as regras e limites, validação, canais, autenticação MQTT, duplicações, intervalo entre alertas e integração MQTT/MCP. Os adaptadores HTTP e SMTP também são testados com servidores locais de captura. Os temporários dos testes usam uma pasta exclusiva em `work/`, evitando conflitos com a pasta temporária do Windows.

Novas demonstrações geram relatórios em `resultados/`. O histórico da operação contínua fica em `data/historico.sqlite3` e pode ser consultado com `.\Executar.cmd -Acao Historico`.

## Organização

| Local | Conteúdo |
|---|---|
| `monitoramento/` | Agente, MQTT, servidor e cliente MCP, regras, histórico e notificações |
| `tests/` | Testes automatizados e serviços locais de captura |
| `exemplos/` | Três mensagens JSON |
| `resultados/` | Evidências da demonstração real e dos testes |
| `.env.example` | Modelo de configuração |
| `Executar.cmd` e `Executar.ps1` | Inicializadores no Windows |
| `requirements.txt` | Dependências com versões fixadas |
| `pyproject.toml` e `conftest.py` | Configuração dos testes |

Referências: [SDK MCP](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x), [Paho MQTT](https://eclipse.dev/paho/clients/python/docs/), [aMQTT](https://amqtt.readthedocs.io/en/latest/references/broker/), [Telegram Bot API](https://core.telegram.org/bots/api).

## Integrantes

| Nome | RM |
|---|---|
| `Eduardo Novaes Mollo` | RM: 561515 |
| `Mathaus Victor Souza Marcelino` | RM: 564146 |
| `Carlos Alberto Guedes Neto` | RM: 566022 |
