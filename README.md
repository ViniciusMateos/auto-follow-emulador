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
5. Para na hora se o Instagram mostrar bloqueio de ação; o agente aborta o lote depois de N
   soft-blocks seguidos e deixa a conta que tomou soft-block descansando (tudo pelo modo).

Com `simular=True` ele percorre tudo igual (chat, curtidores), mas não segue ninguém nem marca o post.

Também tem as funções de **conta** que o agente usa: listar as contas logadas (seletor do IG),
trocar de conta (reabre o IG se sair dele e ignora telas de passagem), **logar conta nova pelo
formulário** (com código pelo app, ou aprovação no seu celular quando o aparelho é novo) e
responder os pedidos de permissão do Android. No login: pede a aprovação no outro aparelho **uma
vez só** (pedido repetido derruba o anterior) e entende o "pedido rejeitado"; "É esta a tua conta?"
vira conta inexistente (sem tocar em "Continuar"); pula a tela de contatos; e se ficar mais de 1 min
numa tela que não conhece, reabre o IG e desiste em vez de segurar a fila.

**Sair do aparelho** — `sair_conta(d, nome)`: Definições e atividade → "Terminar sessão" →
confirma, sem guardar o login, e confere no seletor que a conta sumiu (base do bot Remover Contas).
**Saída de emergência** — `reabrir_ig(d)`: fecha e abre o app do zero (as contas continuam logadas).

**Verificação humana** ("confirma que és uma pessoa"): `resolver_desafio()` encerra a sessão da
conta presa (senão o IG do emulador trava pra todas) e chama `AO_DESAFIO(conta)` — o agente usa
esse gancho pra marcar a conta como bloqueada e mandar um push.

## Onde roda

Este repo é uma pasta da base [`quase-nada-bots-device`](https://github.com/ViniciusMateos) (agente
do PC + supervisor + `device.py`/`emulador.py`): fica em `bots/auto_follow/` e é importado como

```python
from bots.auto_follow import auto_follow as af
```

O estado (`posts_feitos.json`) fica na raiz da base. Teste pela linha de comando com
`python run_follow.py --test` (1 post, teto de 6 follows, não marca).
