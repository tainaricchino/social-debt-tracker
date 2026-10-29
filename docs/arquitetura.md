# Arquitetura

O Social Debt Tracker é um programa local. Não há serviço deste projeto na nuvem. Cada execução lê o `config.json`, coleta metadados das conversas e calcula o índice de saudade. O relatório pode ficar só no terminal ou ir para um bot seu.

```text
config.json ──┐
              ├── analyzer.py ── display.py     (tabela no terminal)
Telegram ─────┤                └─ notifier.py   (relatório + botões)
state.json ───┘
```

O Telethon entra só na coleta. O bot (`python-telegram-bot`) só envia o relatório e recebe `/start`, `/report` e os cliques nos botões. São duas credenciais diferentes de propósito: a da sua conta lê a lista de conversas; a do bot fala com você.

## Pacote

O código fica em `social_debt_tracker/`.

| Módulo | Função |
| --- | --- |
| `cli.py` | Comandos `login`, `run` e `serve`. Dono dos caminhos locais (`.env`, sessão, cache, estado). |
| `telegram_client.py` | Abre a sessão Telethon e devolve uma lista de `ChatMetadata`. |
| `analyzer.py` | Casa cada nome do círculo com uma conversa e calcula o índice. |
| `names.py` | Normaliza nomes e gera a chave curta usada nos botões. |
| `models.py` | Tipos do projeto. `ChatMetadata` não tem campo de texto. |
| `config_store.py` | Lê e grava `config.json`, `state.json` e o cache. |
| `schedule.py` | Decide o próximo horário de envio. |
| `report.py` | Monta o texto do relatório. |
| `notifier.py` | Envia a mensagem e aplica o feedback dos botões. |
| `display.py` | Tabela Rich no terminal. |

`main.py`, na raiz, só chama `social_debt_tracker.cli.main`. O mesmo vale para `python -m social_debt_tracker`.

## Índice de saudade

Para cada contato do `config.json`:

```text
Δt     = agora − data da última atividade
índice = Δt / meta do círculo
```

| Índice | Status |
| --- | --- |
| abaixo de 0,80 | em dia |
| de 0,80 até 1 | quase |
| 1 ou mais | em atraso |

A correspondência do nome acontece nesta ordem:

1. Título igual, ignorando acento, maiúsculas e espaços repetidos.
2. Extensão única por palavra. "Ana Clara" encontra "Ana Clara Souza" se não houver outra conversa compatível.
3. Mais de um candidato vira status `ambíguo`. O programa não escolhe.
4. Nenhum candidato vira `sem registro`.

"Mãe" não casa com "Maestro": o restante do título precisa começar depois de um espaço, não no meio da palavra.

Um contato manual ("já falei") entra na conta quando é mais recente que a data do Telegram. Um adiamento ativo troca o status para `adiado` e tira a pessoa do relatório, mas os dias continuam visíveis na tabela.

Os ganchos são frases fixas, uma lista para pessoas e outra para grupos, escolhidas pelo nome e pelo dia. O texto da conversa não participa dessa escolha.

## Arquivos locais

| Arquivo | O que guarda | No Git |
| --- | --- | --- |
| `config.json` | Círculos, metas, horário, fuso | sim, é o exemplo editável |
| `.env` | `api_id`, `api_hash`, token do bot | não |
| `social_debt.session` | sessão Telethon da sua conta | não |
| `state.json` | chat do relatório, adiamentos, contatos manuais | não |
| `cache/metadata.json` | última coleta: id, título, data, se é grupo | não |

## Fluxo do `serve`

1. Sobe o bot e fica ouvindo comandos.
2. Dorme até o horário de `daily_report_hour`, no fuso configurado.
3. Coleta os metadados, calcula o índice, mostra a tabela e envia o relatório.
4. Grava `last_report_sent_at`. O próximo envio espera `report_interval_days`.
5. Se a coleta ou o envio falhar, tenta de novo em 15 minutos.

Se o processo sobe depois do horário e ainda não houve envio neste intervalo, o relatório sai na hora. `/report` gera um relatório extra e não consome o horário agendado.

`run --notify` e `serve` ao mesmo tempo mandam a mensagem duas vezes. Use um dos dois.
