# Privacy & Ethics

O Social Debt Tracker roda na sua máquina. Este repositório não opera um servidor, não recebe as suas conversas e não tem para onde enviá-las.

## O que o programa copia

De cada diálogo entram quatro dados, e só estes, no objeto `ChatMetadata`:

- identificador do chat
- título
- data da última atividade
- se é grupo

`telegram_client.py` percorre `iter_dialogs` e constrói esse objeto em `metadata_from_dialog`. A função não lê o corpo da mensagem. O cliente é criado com `receive_updates=False`, então o processo não fica inscrito no que chega depois.

Bots e canais de broadcast ficam de fora. Grupos e supergrupos entram pela data da última atividade do grupo, sem registrar quem escreveu.

## O que a API entrega mesmo assim

A listagem de diálogos do Telegram inclui a última mensagem no payload. A biblioteca monta esse objeto na memória. Este código não acessa o texto, não grava em disco, não escreve em log e não coloca no relatório. O teste `test_extractor_never_reads_the_message_payload` falha se a extração passar a tocar nesse payload. Outro teste lê a árvore sintática de `telegram_client.py` e recusa atributos de corpo de mensagem.

Os logs de Telethon, do bot e de HTTP ficam em nível de aviso pelo mesmo motivo: um payload não deve aparecer no console.

## O que sai da máquina

`python main.py run` e `python main.py run --demo` ficam no terminal.

`run --notify` e `serve` enviam um relatório para o bot que você criou. A mensagem leva nomes, dias, o índice e um gancho genérico. Quem transporta isso é o Telegram. O gancho não é um trecho da conversa: são frases prontas, separadas para pessoas e para grupos.

O bot recebe `/start`, `/report` e o clique nos botões. Ele não tem acesso à lista de conversas da sua conta. Quem lê essa lista é a sessão Telethon, com `api_id` e `api_hash`.

## `privacy_mode`

O `config.json` precisa de `"privacy_mode": true`. Qualquer outro valor faz o programa recusar a configuração. O modo não é um interruptor para passar a ler mensagens: esta versão só opera em metadados.

## O que não entra no Git

`.gitignore` deixa de fora:

- `.env`
- `*.session` e `*.session-journal`
- `state.json`
- `cache/`

O `config.json` versionado é o exemplo, com nomes de demonstração. Troque pelos títulos reais das suas conversas antes de publicar um fork, se esses nomes forem pessoais.

## Limite honesto

O índice mede intervalo de silêncio. Não mede qualidade de vínculo, não sabe o assunto da conversa e não distingue quem falou por último num grupo.
