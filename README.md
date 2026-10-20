# Auto Follow (emulador)

Bot do **Quase Nada Bots** que segue os curtidores dos posts compartilhados num chat do Instagram,
**tocando no app real** dentro de um emulador Android (MuMu Player) via `uiautomator2`. Como a conta
fica logada no app de verdade, a sessão não cai.

## Como funciona

1. Abre o chat do grupo (ex: `vaitomanoquasenada`).
2. Vai ao fim da conversa e **sobe até a fronteira**: o último post já feito (com reação ❤ ou no
   registro da frota, `posts_feitos.json`). Nunca começa num post qualquer do meio.
3. Processa pra baixo, em ordem de envio: abre o post → lista de curtidas → segue todo mundo.
4. Reage ❤ no post pra marcar como feito (uma conta por post, coordenando a frota).
5. Para na hora se o Instagram mostrar bloqueio de ação; o lote aborta depois de 2 soft-blocks seguidos.

Também tem as funções de **conta** que o agente usa: listar as contas logadas (seletor do IG),
trocar de conta, **logar conta nova pelo formulário** (com código de verificação pelo app) e sair do
desafio "confirma que és uma pessoa".

## Onde roda

Este repo é uma pasta da base [`quase-nada-bots-device`](https://github.com/ViniciusMateos) (agente
do PC + supervisor + `device.py`/`emulador.py`): fica em `bots/auto_follow/` e é importado como

```python
from bots.auto_follow import auto_follow as af
```

O estado (`posts_feitos.json`) fica na raiz da base. Teste pela linha de comando com
`python run_follow.py --test` (1 post, teto de 6 follows, não marca).
