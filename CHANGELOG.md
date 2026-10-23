# Changelog

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
