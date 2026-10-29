# Social Debt Tracker

Assistente local que mede o tempo desde o último contato com as pessoas e grupos que você escolhe acompanhar. O **índice de saudade** é quantos dias se passaram dividido pela meta do círculo. Quando o índice passa de 1, o silêncio já atravessou o limite que você definiu.

O programa roda na sua máquina. Ele lê metadados das conversas do Telegram — identificador, título e data da última atividade — e pode enviar um relatório privado, com um gancho genérico e botões para dizer "já falei" ou adiar o lembrete.

## Documentação

| Guia | Conteúdo |
| --- | --- |
| [Arquitetura](docs/arquitetura.md) | módulos, índice, arquivos locais, fluxo do `serve` |
| [Privacy & Ethics](docs/privacidade.md) | o que é copiado, o que a API entrega, o que sai da máquina |
| [Configuração](docs/configuracao.md) | `.env`, círculos, comandos, botões, testes |

## Começar

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python main.py run --demo
```

O demo não fala com o Telegram. Para a conta real, preencha o `.env` como em [Configuração](docs/configuracao.md) e rode `python main.py login`.

## Estrutura

```text
social-debt-tracker/
  README.md
  pyproject.toml
  requirements.txt
  config.json              círculos e metas
  .env.example
  main.py                  atalho para o pacote
  docs/
    arquitetura.md
    privacidade.md
    configuracao.md
  social_debt_tracker/
    cli.py                 login, run, serve
    telegram_client.py     metadados via Telethon
    analyzer.py            índice de saudade
    notifier.py            relatório e botões
    config_store.py        config, estado e cache
    display.py             tabela no terminal
    report.py              texto do relatório
    models.py
    names.py
    schedule.py
  tests/
```

Sessão (`.session`), `.env`, `state.json` e `cache/` ficam fora do Git.

## Privacy & Ethics

A análise é self-hosted. De cada conversa o código copia identificador, título e data da última atividade. A listagem de diálogos do Telegram traz a última mensagem no payload; esse texto não é lido, não vai para disco, não aparece em log e não entra no relatório. O cliente não assina mensagens novas (`receive_updates=False`).

`privacy_mode` precisa ser `true`. Sem isso o programa não inicia.

O detalhe do que permanece na máquina e do que o bot envia está em [docs/privacidade.md](docs/privacidade.md).

## Licença

MIT. Veja [LICENSE](LICENSE).
