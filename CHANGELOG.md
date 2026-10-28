# Changelog

## [1.3.0] — 2026-10-27

### Adicionado
- feat: `sair_conta()` — tira a conta do aparelho (Definições e atividade → Terminar sessão, sem guardar o login): espera a folha do menu assentar, confere que abriu as Definições, tenta até 3x e confere no seletor que a conta sumiu
- feat: `reabrir_ig()` — saída de emergência (fecha e abre o app); o `garantir_perfil` usa na "tela presa"

### Corrigido
- fix: o login não trava mais em tela desconhecida — mais de 1 min parado numa tela que ele não conhece → reabre o IG e desiste (antes segurava a fila 6 min)
- fix: "É esta a tua conta?" (o @ não existe) vira conta inexistente, sem tocar em "Continuar"
- fix: pula a tela "acesso aos teus contactos" que vem depois do login entrar
- fix: pede a aprovação no outro aparelho UMA vez só (pedido repetido derrubava o anterior → "rejeitado") e entende o "pedido de acesso foi rejeitado"
- fix: `desafio_humano` lê o @ também em "...usares o teu perfil, <conta>"; senha recusada loga a mensagem exata do IG

### Documentação
- docs: README com sair da conta e o login mais esperto

## [1.2.0] — 2026-10-24

### Corrigido
- fix: criar/trocar conta pelo seletor novo do IG 451 — botões renomeados ("Adicionar Instagram"/"Inicia sessão"), rola a folha quando tem muita conta e reconhece "Usar outro perfil"

## [1.1.0] — 2026-10-22

### Adicionado
- feat: login em aparelho novo (aprovação no celular ou código, tela de login direta, senha incorreta do IG em pt-PT)
- feat: conta em verificação humana sai do emulador sozinha e avisa (gancho `AO_DESAFIO`)
- feat: modo simulação (percorre sem seguir nem marcar)

### Corrigido
- fix: permissão do Android e telas de passagem não travam a troca de conta

### Documentação
- docs: README com login em aparelho novo, desafio e simulação

## [1.0.0] — 2026-10-20

### Adicionado
- feat: segue os curtidores dos posts de um chat tocando no app real do Instagram no emulador
- feat: modelo da fronteira — sobe até o último post feito (reação ou registro da frota) e processa pra baixo, em ordem de envio
- feat: reação ❤ marca o post como feito (uma conta por post), registro persistente `posts_feitos.json`
- feat: lote de contas com abort em 2 soft-blocks seguidos e parada na hora em bloqueio de ação
- feat: contas no app — listar, trocar, logar conta nova pelo formulário (código pelo app) e sair do desafio "confirma que és uma pessoa"
- feat: suporte ao layout novo do IG (Compose, sem resource-id) e a contas restritas de DM
