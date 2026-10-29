# Configuração

Python 3.10 ou mais recente. No PowerShell, na raiz do projeto:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

`requirements.txt` e `pyproject.toml` listam as mesmas dependências. O `pip install -r requirements.txt` basta para rodar da pasta. `pip install -e .` é opcional e cria o comando `social-debt`.

## Credenciais

`.env`:

```text
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_BOT_TOKEN=
TELEGRAM_REPORT_CHAT_ID=
```

| Variável | Onde nasce | Para quê |
| --- | --- | --- |
| `TELEGRAM_API_ID` | [my.telegram.org](https://my.telegram.org) | sessão da sua conta |
| `TELEGRAM_API_HASH` | [my.telegram.org](https://my.telegram.org) | sessão da sua conta |
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) | só o relatório |
| `TELEGRAM_REPORT_CHAT_ID` | opcional | destino do relatório |

Sem `TELEGRAM_REPORT_CHAT_ID`, abra uma conversa privada com o bot e envie `/start`. O chat fica em `state.json`.

## Círculos

`config.json` na raiz:

```json
{
  "user_settings": {
    "daily_report_hour": "10:00",
    "privacy_mode": true,
    "timezone": "America/Sao_Paulo",
    "report_interval_days": 1
  },
  "circles": [
    {
      "name": "Círculo Íntimo",
      "target_days": 3,
      "contacts": ["Mãe", "Vovó Teresa"]
    },
    {
      "name": "Amigos Próximos",
      "target_days": 10,
      "contacts": ["Grupo do Futebol", "Ana Clara"]
    }
  ]
}
```

| Campo | Regra |
| --- | --- |
| `daily_report_hour` | `HH:MM`, 24 horas. Padrão `10:00`. |
| `privacy_mode` | precisa ser `true`. |
| `timezone` | nome IANA. Padrão `America/Sao_Paulo`. |
| `report_interval_days` | inteiro ≥ 1. `7` vira relatório semanal. Padrão `1`. |
| `circles[].target_days` | inteiro ≥ 1. |
| `circles[].contacts` | títulos das conversas, ou um prefixo que só exista numa delas. |

O arquivo que vem no repositório usa os nomes da especificação. Substitua pelos títulos que aparecem no Telegram.

## Comandos

```powershell
python main.py run --demo
python main.py login
python main.py run
python main.py run --notify
python main.py serve
```

Os mesmos subcomandos funcionam com `python -m social_debt_tracker`.

`run --demo` não fala com o Telegram. Usa conversas fictícias e os círculos do seu `config.json`, então os nomes do exemplo precisam continuar no arquivo para a tabela de demonstração encher.

`login` pede telefone e código uma vez e grava `social_debt.session` na raiz.

`run` coleta metadados e imprime a tabela. `--notify` também manda o relatório.

`serve` fica em execução: envia no horário e escuta os botões. Não rode `serve` junto com um agendador que chama `run --notify`.

## Botões do relatório

Cada contato em atraso ou quase na meta ganha uma linha:

- `falei` grava um contato manual agora
- `1d` adia o lembrete um dia
- `7d` adia sete dias

O status `adiado` some do relatório e continua na tabela do terminal, com os dias calculados.

## Testes

```powershell
python -m unittest discover -s tests -t . -v
```
