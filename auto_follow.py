"""
Auto-follow por DEVICE (emulador Android) — dirige o app REAL do Instagram tocando na tela.

Replica o fluxo dos bots do servidor (worker auto-follow-instagram), mas por toques no app,
então a sessão NÃO cai e o IG pede muito menos verificação:

  abre a DM "vaitomanoquasenada" → acha o próximo post compartilhado SEM reação →
  abre o post → abre "quem curtiu" → segue TODOS os curtidores (pula quem já segue) →
  volta e reage ❤️ no post pra marcar como feito (coordena com a frota: post reagido = qualquer
  conta pula) → próximo post. Para NA HORA se o IG bloquear (kill-switch).

Seletores do IG mapeados ao vivo (app pt-PT/pt-BR, build out/2026):
  - card de post compartilhado:  xma_bubble_container  (mídia = media_container)
  - post já reagido:             message_reactions_pill_container  (logo abaixo da bolha)
  - abrir quem curtiu:           like_count  ("Ver Gostos")
  - botão seguir na folha:       row_follow_button (text "Seguir"); @ em row_user_primary_name
  - barra de reação:             long-press na mídia → 1º emoji (ImageView desc "Reação") = ❤️
"""
import re
import os
import time
import json
import random

IG_PKG = "com.instagram.android"

# ── seletores ──
DIRECT_TAB = "direct_tab"
PROFILE_TAB = "profile_tab"
ACC_SWITCHER = "action_bar_username_container"   # topo do perfil: nome da conta + seta
ACC_TITLE = "action_bar_title"                    # texto do nome da conta atual
XMA_BUBBLE = "xma_bubble_container"
MEDIA_CONTAINER = "media_container"
REACT_PILL = "message_reactions_pill_container"
LIKE_COUNT = "like_count"
ROW_FOLLOW = "row_follow_button"
ROW_NAME = "row_user_primary_name"

# ── textos (pt-PT/pt-BR) ──
TXT_SEGUIR = "Seguir"
# SÓ sinais claros de bloqueio/limite de AÇÃO. NÃO usar "limitámos" sozinho (o aviso
# "Limitámos o número de seguidores apresentados..." é inofensivo e começa igual).
BLOQUEIO = (
    "ação bloqueada", "acção bloqueada", "action blocked",
    "tente novamente mais tarde", "tenta novamente mais tarde", "try again later",
    "bloqueámos", "bloqueamos", "we've blocked", "we blocked",
    "limitámos a frequência", "limitamos a frequência", "limite a frequência",
    "restringimos", "we restrict", "we limit how often",
)
BLOQUEIO_FORTE = ("ação bloqueada", "acção bloqueada", "action blocked",
                  "bloqueámos", "bloqueamos", "we've blocked", "we blocked")


def rid(name):
    return f"{IG_PKG}:id/{name}"


# ─────────────────────────── infra ───────────────────────────
def _log(fn, msg):
    """Loga sem quebrar por encoding do console do Windows."""
    try:
        fn(msg)
    except Exception:
        try:
            fn(msg.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass


def _sleep(a, b):
    time.sleep(random.uniform(a, b))


def _scroll(d, para="cima", forca=1.0):
    """Flick HUMANO (desliza com inércia), usado na navegação da thread. para='cima' revela
    posts mais ANTIGOS; 'baixo' revela mais NOVOS. forca ALTA = duração MENOR = fling FORTE
    (mais inércia → cobre várias telas de uma vez), igual a gente joga o dedo na mão."""
    x = random.randint(495, 585)
    if para == "cima":
        y1 = random.randint(430, 520)
        y2 = random.randint(1560, 1660)
    else:
        y1 = random.randint(1460, 1600)
        y2 = random.randint(320, 440)
    dur = max(0.015, random.uniform(0.09, 0.14) / forca)   # força↑ = inércia↑
    d.swipe(x, y1, x, y2, dur)


def _scroll_folha(d):
    """Scroll na folha de curtidores: humano mas CONTROLADO (~meia tela), pra NÃO pular ninguém
    da lista. Coords RELATIVAS à tela real (antes eram fixas p/ ~1920 → caíam fora num device
    900x1600 e a lista mal rolava)."""
    try:
        W, H = d.window_size()
    except Exception:
        W, H = 900, 1600
    x = random.randint(int(W * 0.45), int(W * 0.60))
    y1 = random.randint(int(H * 0.78), int(H * 0.86))
    y2 = random.randint(int(H * 0.30), int(H * 0.42))
    d.swipe(x, y1, x, y2, random.uniform(0.12, 0.22))


def _autores_vis(d):
    """Fingerprint ESTÁVEL da posição: os autores dos cards visíveis (ignora timestamp/loading
    que mudam sozinhos). Progresso real = essa tupla muda."""
    posts, _ = posts_na_tela(d)
    return tuple(p["autor"] for p in posts)


def _pos_vis(d):
    """Fingerprint de POSIÇÃO: y bucketizado de TODAS as linhas com texto visíveis. MUDA com rolagem
    pequena e NÃO muda com timestamp (ao contrário da assinatura). É o sinal certo pra saber se o
    scroll CONTROLADO andou de fato."""
    # TODAS as linhas com texto/descrição (não só cards de post): numa faixa só de "Mensagem
    # indisponível" não há card → só-post dava ()==() e cravava "topo"/"fim" FALSO (segue12, run-366).
    # Usa só o Y (o texto de timestamp muda sozinho); ignora status bar/cabeçalho/composer.
    xml = _dump(d)
    try:
        _w, H = d.window_size()
    except Exception:
        H = 1600
    ys = []
    for m in re.finditer(r"<node[^>]*/?>", xml):
        t = m.group(0)
        if not (_attr(t, "text") or _attr(t, "content-desc")):
            continue
        bb = _bounds(t)
        if bb and int(H * 0.08) < bb[1] < int(H * 0.92):
            ys.append(bb[1] // 30)
    return tuple(sorted(set(ys)))


def _subir_insistindo(d, forca=2.4):
    """Fling forte pra CIMA. Progresso medido pelos AUTORES visíveis (não pelo hash, que falseia
    com timestamp). Se não progride (IG carregando histórico), INSISTE com pausa. True se andou."""
    antes = _autores_vis(d)
    for tent in range(7):
        _scroll(d, "cima", forca=forca)
        _assentar(d)       # espera o momentum do flick parar antes de ler (senão autor/reação falseia)
        if _autores_vis(d) != antes:
            return True
        _sleep(1.6, 2.6)   # o IG do DM carrega o histórico quando você INSISTE
    return False


def _scroll_ctrl(d, para="cima"):
    """Scroll CONTROLADO: ~36% da tela e RÁPIDO. Swipe LENTO escorrega / vira long-press e NÃO rola
    (bug que fez 'não subir nada'); rápido+curto rola de verdade e ainda tem overlap (não pula post).
    'cima' = revela posts mais ANTIGOS; 'baixo' = mais NOVOS. Coords relativas ao tamanho real."""
    try:
        W, H = d.window_size()
    except Exception:
        W, H = 900, 1600
    x = random.randint(int(W * 0.50), int(W * 0.62))
    if para == "cima":
        y1, y2 = int(H * 0.44), int(H * 0.80)
    else:
        y1, y2 = int(H * 0.80), int(H * 0.44)
    d.swipe(x, y1, x, y2, random.uniform(0.11, 0.17))   # rápido = rola de verdade; curto = controlado


def _subir_ctrl(d):
    """Sobe UM passo controlado (sem arremesso), insistindo se o IG estiver recarregando histórico.
    True se andou (autores mudaram), False se é topo de verdade."""
    antes = _pos_vis(d)
    for _tent in range(5):
        _scroll_ctrl(d, "cima")
        _assentar(d)
        if _pos_vis(d) != antes:
            return True
        _sleep(1.2, 2.0)   # pode estar carregando histórico — insiste antes de cravar "topo"
    return False


def _descer_ctrl(d):
    """Desce UM passo controlado (rumo ao post mais NOVO). True se andou, False se é o FIM (fundo).
    Espelho do _subir_ctrl — usado pra processar da fronteira pra baixo (ordem de envio)."""
    antes = _pos_vis(d)
    for _tent in range(5):
        _scroll_ctrl(d, "baixo")
        _assentar(d)
        if _pos_vis(d) != antes:
            return True
        _sleep(1.0, 1.6)
    return False


def _assentar(d, timeout=3.5):
    """Espera a tela PARAR de mexer (momentum do flick acabar) antes de ler. Essencial pra
    não perder o post reagido enquanto a thread ainda tá rolando."""
    prev = None
    fim = time.time() + timeout
    while time.time() < fim:
        sig = _assinatura_thread(d)
        if sig == prev:
            return
        prev = sig
        time.sleep(0.45)


def _dump(d):
    try:
        return d.dump_hierarchy()
    except Exception:
        return ""


def _attr(tag, a):
    m = re.search(a + r'="([^"]*)"', tag)
    return m.group(1) if m else ""


def _bounds(tag):
    m = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
    return tuple(map(int, m.groups())) if m else None


def _bloqueio(xml):
    low = xml.lower()
    return next((h for h in BLOQUEIO if h in low), None)


# ─────────────── garantir o app/perfil (navega sozinho) ───────
PERM_PKG = "com.android.permissioncontroller"


def fechar_permissao_android(d, log=None):
    """Pedido de permissão do ANDROID na frente do IG (1º uso num aparelho novo — ex: a instância do
    brechó, 21/10: "Permitir que a app Instagram lhe envie notificações?" travou o story). Notificação,
    contatos e localização → NÃO PERMITIR; fotos/vídeos/câmera/microfone → PERMITIR (o story precisa
    da galeria). Devolve True se tratou um pedido."""
    try:
        if (d.app_current() or {}).get("package") != PERM_PKG:
            return False
        msg = d(resourceId=PERM_PKG + ":id/permission_message")
        txt = ((msg.info.get("text") or "") if msg.exists else "").lower()
        negar = any(k in txt for k in ("notifica", "notification", "contact", "localiza", "location"))
        ids = (("permission_deny_button", "permission_deny_and_dont_ask_again_button") if negar else
               ("permission_allow_button", "permission_allow_all_button",
                "permission_allow_foreground_only_button", "permission_allow_one_time_button"))
        for i in ids:
            b = d(resourceId=f"{PERM_PKG}:id/{i}")
            if b.exists:
                b.click()
                _log(log, f"pedido do Android ({txt[:60] or 'permissão'}): {'não permitir' if negar else 'permitir'}")
                _sleep(1.0, 1.6)
                return True
    except Exception:
        pass
    return False


def garantir_app(d, log=None):
    """Garante o Instagram em PRIMEIRO PLANO — abre se estiver fechado/minimizado (ex: emulador
    parado na home do Android). Devolve True se o IG está em foreground."""
    for _ in range(3):   # pedido de permissão do Android por cima do IG → responde antes
        if not fechar_permissao_android(d, log):
            break
    try:
        cur = (d.app_current() or {}).get("package")
    except Exception:
        cur = None
    if cur == IG_PKG:
        resolver_desafio(d, log)   # conta presa em verificação humana → sai dela antes de seguir
    if cur != IG_PKG:
        try:
            d.app_start(IG_PKG, use_monkey=True)   # abre/traz pro foreground sem saber a activity
            _log(log, "abrindo o Instagram…")
            _sleep(2.5, 4.0)
        except Exception as e:
            _log(log, f"não consegui abrir o IG: {e}")
            return False
    try:
        return (d.app_current() or {}).get("package") == IG_PKG
    except Exception:
        return True


def garantir_perfil(d, log=None):
    """Deixa o IG na aba de PERFIL de forma AUTOMÁTICA: abre o app se preciso e navega pelas abas
    (toca em profile_tab; se cair numa tela interna/diálogo, volta) até o cabeçalho do perfil
    aparecer. Se ficar PRESO numa tela (diálogo, feed travado, tela estranha) e não achar o perfil,
    REINICIA o IG do zero (app_stop+app_start) e tenta de novo — pra 'saber sair de lá' sozinho.
    (Uma parede de challenge REAL do IG pode voltar após o reinício — aí a conta está em análise e
    não há como o agente sair sozinho; o chamador cai no fallback.) Devolve True se o perfil abriu."""
    if not garantir_app(d, log):
        return False
    for tentativa in range(2):
        for _ in range(6):
            try:
                # SEMPRE toca a aba Perfil antes de conferir: action_bar_title também existe em outras
                # telas (título "Notificações", perfil de OUTRA pessoa) → antes ele achava que já
                # estava no perfil e a verificação de contas dava "0 ok" (19/10, run-376)
                if d(resourceId=rid(PROFILE_TAB)).exists:
                    d(resourceId=rid(PROFILE_TAB)).click()
                    _sleep(1.5, 2.2)
                    if d(resourceId=rid(ACC_SWITCHER)).exists or d(resourceId=rid(ACC_TITLE)).exists:
                        return True
                else:
                    d.press("back")   # tela interna/dialog sem barra de abas → volta e tenta de novo
            except Exception:
                pass
            _sleep(1.2, 2.0)
        # não chegou no perfil → na 1ª rodada, reinicia o IG do zero pra sair da tela presa e retenta
        if tentativa == 0:
            try:
                _log(log, "tela presa — reiniciando o IG pra sair…")
                d.app_stop(IG_PKG)
                _sleep(1.0, 2.0)
                d.app_start(IG_PKG, use_monkey=True)
                _sleep(3.0, 5.0)
            except Exception:
                pass
    try:
        return d(resourceId=rid(ACC_TITLE)).exists
    except Exception:
        return False


# sinais de BLOQUEIO/challenge REAL do IG (conta retida) — pra NÃO confundir "não consegui trocar"
# (transiente: troca lenta, UI não assentou, stop no meio) com "conta bloqueada".
BLOQUEIO_KW = (
    "recurso em análise", "recurso em analise", "em análise", "em analise",
    "não está visível", "nao esta visivel", "conta não está", "conta nao esta",
    "suspendemos", "suspenso", "suspensa", "desativ", "suspended", "disabled",
    "we removed", "removemos", "confirme que é você", "confirme que e voce",
    "revise", "revisar", "ajudar a manter", "help us confirm",
)


def tela_bloqueio(d):
    """True se a tela atual é um BLOQUEIO/challenge REAL do IG (ChallengeActivity ou texto de
    conta em análise/suspensa). Serve pra marcar 'bloqueada' SÓ quando há sinal de verdade —
    senão (só não deu pra trocar) a gente marca 'desconhecida', não 'bloqueada'."""
    try:
        act = ((d.app_current() or {}).get("activity") or "").lower()
    except Exception:
        act = ""
    if "challenge" in act:
        return True
    try:
        xml = (_dump(d) or "").lower()
    except Exception:
        xml = ""
    return any(k in xml for k in BLOQUEIO_KW)


# ─────────────────────── troca de conta (seletor nativo) ──────
def conta_atual(d):
    el = d(resourceId=rid(ACC_TITLE))
    try:
        return (el.info.get("text") or "") if el.exists else ""
    except Exception:
        return ""


def trocar_conta(d, nome, log):
    """Troca pra conta `nome` pelo seletor nativo do IG (perfil → nome → lista → conta).
    Todas as contas têm que estar logadas no device. Devolve True se ficou nela."""
    nome = nome.strip()
    resolver_desafio(d, log)   # uma conta presa em verificação humana trava o seletor pra todas
    # garante o perfil aberto (onde fica o seletor no topo). O "voltar" pode TIRAR do IG (ex: depois
    # de postar um story) → aí reabre o app em vez de seguir voltando na tela inicial do Android
    # (story em lote 20/10: segue6/8/9 puladas com "não achei o seletor")
    for _ in range(6):
        if d(resourceId=rid(ACC_SWITCHER)).exists:
            break
        if d(resourceId=rid(PROFILE_TAB)).exists:
            d(resourceId=rid(PROFILE_TAB)).click()
        else:
            try:
                fora = (d.app_current() or {}).get("package") != IG_PKG
            except Exception:
                fora = False
            if fora:
                garantir_app(d, log)
            else:
                d.press("back")
        _sleep(1.2, 2.0)
    if conta_atual(d) == nome:
        _log(log, f"já está na {nome}")
        return True
    if not d(resourceId=rid(ACC_SWITCHER)).exists:
        _log(log, "não achei o seletor de contas")
        return False
    d(resourceId=rid(ACC_SWITCHER)).click()
    _sleep(2.0, 3.0)
    alvo = d(descriptionStartsWith=nome)
    # o seletor pode demorar pra carregar a lista (1 olhada só dava "não está logada" com a conta
    # logada — segue13, run-379 19/10) → ESPERA; e, se não apareceu, rola a lista uma vez
    if not alvo.wait(timeout=6):
        try:
            W, H = d.window_size()
            d.swipe(int(W * 0.5), int(H * 0.8), int(W * 0.5), int(H * 0.45), 0.3)
            _sleep(1.2, 1.8)
        except Exception:
            pass
    if not alvo.exists:
        # a conta pode estar COLAPSADA sob "Utilizador do Instagram" (sessão caída/indisponível) —
        # um toque nessa linha reativa e revela as escondidas (ex: 13 e 14). Resolve e reabre.
        util = d(descriptionContains="Utilizador do Instagram")
        if util.exists:
            _log(log, "conta colapsada em 'Utilizador do Instagram' — tocando pra revelar…")
            util.click(); _sleep(3.5, 5.5)
            if d(resourceId=rid(PROFILE_TAB)).exists:
                d(resourceId=rid(PROFILE_TAB)).click(); _sleep(1.2, 2.0)
            if conta_atual(d) == nome:
                _log(log, f"ficou na {nome} ao revelar")
                return True
            if d(resourceId=rid(ACC_SWITCHER)).exists:
                d(resourceId=rid(ACC_SWITCHER)).click(); _sleep(2.0, 3.0)
            alvo = d(descriptionStartsWith=nome)
        if not alvo.exists:
            _log(log, f"conta '{nome}' não está logada no device")
            d.press("back")
            return False
    alvo.click()
    _sleep(2.5, 3.5)
    # ESPERA a conta assentar por ~14s (poll), em vez de 1 check: contas com muita conversa
    # (ex: 9/10, "9 conversas e mais…") demoram pra carregar o perfil → checar cedo dava falso
    # "desconhecida" no verify. A cada volta reforça o perfil e relê o conta_atual.
    agora = ""
    for _ in range(8):
        if d(resourceId=rid(PROFILE_TAB)).exists:
            try:
                d(resourceId=rid(PROFILE_TAB)).click()
            except Exception:
                pass
        agora = conta_atual(d)
        if agora == nome:
            break
        if agora and not re.fullmatch(r"[a-z0-9._]{1,30}", agora):
            # título que NÃO é um @ ("O que aconteceu", tela de passagem do IG por cima do perfil —
            # segue14 run-405, 21/10) → fecha e lê de novo, em vez de achar que é outra conta
            try:
                d.press("back")
            except Exception:
                pass
        _sleep(1.3, 1.9)
    ok = (agora == nome)
    _log(log, f"troca pra {nome}: {'OK' if ok else 'ficou em ' + (agora or '?')}")
    return ok


# ───────────── enumeração das contas logadas (seletor multi-conta) ─────────────
# Estrutura REAL de uma LINHA de conta no seletor (confirmada ao vivo, build out/2026):
#   <ViewGroup clickable=true long-clickable=true selected=<é a ativa?>
#              content-desc="<user>"  |  "<user>, N conversas e mais M">
#       <ImageView/>                          (avatar)
#       <View text="<user>"/>                 (username — presente em TODA linha, até na ativa)
#       <View text="N conversas e mais M"/>   (subtítulo; a linha ATIVA não tem)
#   </ViewGroup>
# Pegadinhas que esta leitura trata (as que escondiam contas, ex: 13 e 14):
#   1) a linha ATIVA tem content-desc só com o @username, SEM vírgula → a regex antiga (que exigia
#      vírgula) a perdia; agora o username sai do desc (antes da vírgula OU o desc inteiro) e, em
#      fallback, do texto-filho dentro das bounds da linha.
#   2) o seletor pode ter MAIS contas do que cabe (em landscape é um RecyclerView rolável) → rolamos
#      DENTRO do painel, mas SÓ quando existe um nó scrollable; em portrait a folha cabe inteira e
#      NÃO rolamos (ali um swipe fecharia a folha / dispararia o gesto "home" do Android).
#   3) LINHA "indisponível" (a sessão caiu): aparece como uma linha de conta SEM username legível, ou
#      com texto tipo "conta indisponível"/"toque para entrar". Em vez de IGNORAR (o que escondia as
#      contas por trás dela), TOCAMOS nela pra reativar, lemos a conta que ficou ativa e voltamos pro
#      seletor — foi o que o usuário fazia na mão. Se cair em login/código/challenge, RECUAMOS sem
#      submeter nada e marcamos a linha como presente-mas-indisponível.

_RE_CONTA_SELETOR = re.compile(r"^@?([A-Za-z0-9._]{1,30}),")   # linha INATIVA: "user, ..." (mantido)
_RE_USERNAME = re.compile(r"^[A-Za-z0-9._]{1,30}$")

# rótulos do rodapé do seletor que NÃO são contas (não devem virar "conta" nem "indisponível")
_SELETOR_NAO_CONTA = ("adicionar conta", "add account", "abrir centro de contas",
                      "open accounts center", "centro de contas", "criar conta nova",
                      "criar nova conta", "ignorar", "dispensar")
# marcas de LINHA de conta em estado anormal (sessão caiu / precisa reautenticar)
_INDISP_KW = ("indispon", "toque para entrar", "toca para entrar", "entrar novamente",
              "entra novamente", "sessão expir", "sessao expir", "expirou", "não foi possível",
              "nao foi possivel", "iniciar sessão novamente", "inicia sessão novamente",
              "voltar a iniciar sessão", "log back in", "logged out", "erro ao carregar",
              "tenta novamente", "tente novamente")


def _ordkey_conta(s):
    """Chave de ordenação NATURAL: separa dígitos pra "segue2" vir antes de "segue10"."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s or "")]


def _dentro(bb, caixa, folga=6):
    """O CENTRO de bb cai dentro de caixa (com folga)? Usado p/ casar texto-filho ↔ linha."""
    if not bb or not caixa:
        return False
    cx, cy = (bb[0] + bb[2]) // 2, (bb[1] + bb[3]) // 2
    return (caixa[0] - folga) <= cx <= (caixa[2] + folga) and \
           (caixa[1] - folga) <= cy <= (caixa[3] + folga)


def _eh_subtitulo(txt):
    """Texto de subtítulo da linha ('5 conversas e mais 6', '1 conversa'…) — não é username."""
    low = (txt or "").strip().lower()
    return (not low) or ("conversa" in low) or ("a seguir" in low) or \
           ("mais" in low and any(c.isdigit() for c in low))


def _username_de_desc(desc):
    """Username a partir do content-desc da linha: trecho antes da 1ª vírgula (linha INATIVA) OU o
    desc inteiro quando é só o @username (linha ATIVA, sem vírgula). None se não parecer username."""
    desc = (desc or "").strip()
    if not desc:
        return None
    cab = desc.split(",", 1)[0].strip().lstrip("@")
    return cab if _RE_USERNAME.match(cab) else None


def _nodes_seletor(xml):
    """Tupla por node: (bounds, classe, content-desc, text, clickable, long-clickable, selected,
    scrollable). Base da leitura por LINHA (robusta à hierarquia do bottom sheet)."""
    out = []
    for m in re.finditer(r"<node[^>]*/?>", xml or ""):
        t = m.group(0)
        out.append((_bounds(t), _attr(t, "class"), _attr(t, "content-desc"), _attr(t, "text"),
                    _attr(t, "clickable") == "true", _attr(t, "long-clickable") == "true",
                    _attr(t, "selected") == "true", _attr(t, "scrollable") == "true"))
    return out


def _linhas_seletor(xml):
    """LINHAS de conta do seletor, de cima pra baixo. Cada item:
       {bounds, desc, selected, username|None, suspeita, rotulo, tap}.
    É linha de conta todo node clicável+long-clicável que seja ViewGroup (o template da linha) OU
    que bata uma marca de 'indisponível'; os botões do rodapé (adicionar conta / centro de contas /
    ignorar) são excluídos. username sai do desc e, em fallback, do texto-filho dentro das bounds.
    suspeita=True quando é linha de conta mas SEM username legível, ou com marca de indisponível."""
    nodes = _nodes_seletor(xml)
    textos = [(bb, tx) for (bb, _c, _d, tx, _cl, _lc, _s, _sc) in nodes if bb and tx]
    linhas = []
    for (bb, cls, desc, text, clk, lck, sel, _sc) in nodes:
        if not bb or not clk or not lck:
            continue
        rotulo_low = (desc or text or "").strip().lower()
        if any(k in rotulo_low for k in _SELETOR_NAO_CONTA):
            continue   # botão do rodapé, não é conta
        bate_indisp = any(k in rotulo_low for k in _INDISP_KW)
        if ("ViewGroup" not in cls) and not bate_indisp:
            continue   # só o template de linha (ViewGroup) ou algo claramente "indisponível"
        user = _username_de_desc(desc)
        if not user:
            # fallback: username num texto-filho dentro das bounds da linha (ignora subtítulos)
            for (tbb, tx) in textos:
                cand = (tx or "").strip().lstrip("@")
                if cand and _dentro(tbb, bb) and not _eh_subtitulo(tx) and _RE_USERNAME.match(cand):
                    user = cand
                    break
        rotulo = (desc or text or "").strip()
        if not rotulo:
            filhos = [tx.strip() for (tbb, tx) in textos if _dentro(tbb, bb) and tx.strip()]
            rotulo = " / ".join(filhos[:3]) if filhos else "(linha sem rótulo)"
        linhas.append({
            "bounds": bb, "desc": desc, "selected": sel, "username": user,
            "suspeita": (user is None) or bate_indisp, "rotulo": rotulo,
            "tap": ((bb[0] + bb[2]) // 2, (bb[1] + bb[3]) // 2),
        })
    linhas.sort(key=lambda r: r["bounds"][1])
    return linhas


def _parse_contas_seletor(xml):
    """Usernames LEGÍVEIS das linhas do seletor (AGORA inclui a conta ATIVA, cujo content-desc não
    tem vírgula). Mantido por compatibilidade. Dedupe case-insensitive, na ordem de leitura."""
    achados, vistos = [], set()
    for ln in _linhas_seletor(xml):
        u = ln["username"]
        if u and u.lower() not in vistos:
            vistos.add(u.lower())
            achados.append(u)
    return achados


def _no_seletor(d):
    """A folha do seletor multi-conta está ABERTA? (o cabeçalho ACC_SWITCHER sumiu atrás dela E há
    linha de conta OU o botão 'adicionar conta'). Usado p/ abrir/fechar com segurança."""
    try:
        if d(resourceId=rid(ACC_SWITCHER)).exists:
            return False
    except Exception:
        pass
    xml = _dump(d)
    if _linhas_seletor(xml):
        return True
    return any(k in xml.lower() for k in ("adicionar conta", "add account"))


def _abrir_seletor(d):
    """Abre a folha de contas a partir do perfil (toca ACC_SWITCHER). True se a folha abriu."""
    try:
        if _no_seletor(d):
            return True
        if not d(resourceId=rid(ACC_SWITCHER)).exists:
            return False
        d(resourceId=rid(ACC_SWITCHER)).click()
    except Exception:
        return False
    for _ in range(5):
        _sleep(0.6, 1.0)
        if _no_seletor(d):
            return True
    return _no_seletor(d)


def _fechar_seletor(d):
    """Fecha a folha (back) até o cabeçalho do perfil reaparecer. Reversível; no máx 3 backs pra
    não sair do app/perfil."""
    for _ in range(3):
        try:
            if d(resourceId=rid(ACC_SWITCHER)).exists:
                return
            d.press("back")
            time.sleep(0.7)
        except Exception:
            return


def _coletar_linhas(d):
    """Lê as linhas do seletor ROLANDO o painel — mas SÓ quando há um nó scrollable (ex: landscape =
    RecyclerView). Em portrait a folha cabe inteira e NÃO rolamos (um swipe ali fecharia a folha ou
    dispararia o gesto 'home'). Junta por username/rótulo preservando a ordem de leitura."""
    xml = _dump(d)
    por_chave, ordem = {}, []

    def _merge(lst):
        for ln in lst:
            chave = (ln["username"] or ln["rotulo"]).lower()
            if chave not in por_chave:
                por_chave[chave] = ln
                ordem.append(chave)

    _merge(_linhas_seletor(xml))
    sb = next((bb for (bb, _c, _d, _tx, _cl, _lc, _s, sc) in _nodes_seletor(xml) if sc and bb), None)
    if sb:
        try:
            _w, h = d.window_size()
        except Exception:
            h = 1920
        x = (sb[0] + sb[2]) // 2
        y1 = min(int(sb[1] + 0.65 * (sb[3] - sb[1])), int(h * 0.82))   # longe da borda de baixo
        y2 = int(sb[1] + 0.28 * (sb[3] - sb[1]))
        estavel = 0
        for _ in range(12):
            antes = len(por_chave)
            try:
                d.swipe(x, y1, x, y2, 0.35)
            except Exception:
                break
            _sleep(0.9, 1.3)
            _merge(_linhas_seletor(_dump(d)))
            if len(por_chave) == antes:
                estavel += 1
                if estavel >= 2:
                    break
            else:
                estavel = 0
    return [por_chave[c] for c in ordem]


def _resolver_indisponivel(d, linha, log=None):
    """Toca numa linha de conta 'indisponível' pra REATIVÁ-LA (o que o usuário fazia na mão): isso
    normalmente reloga a conta e revela as que estavam escondidas por trás dela. Lê a conta que ficou
    ativa e devolve o username. Se cair em tela de login/código/challenge, RECUA sem submeter nada e
    devolve None (a linha fica marcada presente-mas-indisponível). Sempre tenta deixar o app num
    perfil (garantir_perfil) pra o seletor poder reabrir. NUNCA levanta."""
    try:
        d.click(*linha["tap"])
    except Exception:
        return None
    _sleep(2.5, 3.8)
    try:
        xml = _dump(d)
        if _tem_form_login(xml) or _tela_de_codigo(xml):
            _log(log, "  (linha abriu login/verificação — recuando SEM submeter)")
            _back_out(d, 3)
            try:
                garantir_perfil(d, log)
            except Exception:
                pass
            return None
    except Exception:
        pass
    try:
        garantir_perfil(d, log)
        u = (conta_atual(d) or "").strip().lstrip("@")
        return u or None
    except Exception:
        return None


def listar_contas_logadas(d, log=None, com_indisponiveis=False, resolver=True):
    """Lista TODAS as contas logadas no device pelo seletor multi-conta do IG (a partir do perfil):
    abre a folha, lê os usernames (ROLANDO quando há conteúdo rolável) e RESOLVE as linhas
    'indisponíveis' tocando nelas — reativa a sessão e revela as contas escondidas por trás (ex: 13
    e 14). SEMPRE fecha a folha no fim (reversível) e tenta restaurar a conta ativa original se um
    resolver a trocou. NUNCA levanta — devolve vazio em qualquer falha. Ordem natural, sem duplicar.

    com_indisponiveis=False (default, COMPATÍVEL com quem chama hoje): devolve a lista de usernames.
    com_indisponiveis=True: devolve (contas, indisponiveis) — indisponiveis = rótulos das linhas que
        NÃO deu pra reativar (caíram em login/challenge).
    resolver=True: toca nas linhas indisponíveis pra reativar; False só lê (comportamento antigo)."""
    def _saida(ok, indis):
        vist, out = set(), []
        for u in ok:
            u = (u or "").strip().lstrip("@")
            if u and u.lower() not in vist:
                vist.add(u.lower())
                out.append(u)
        out.sort(key=_ordkey_conta)
        if not com_indisponiveis:
            return out
        ind, vist_i = [], set(u.lower() for u in out)
        for r in indis:
            r = (r or "").strip()
            if r and r.lower() not in vist_i and r not in ind:
                ind.append(r)
        return out, ind

    try:
        if not d(resourceId=rid(ACC_SWITCHER)).exists:
            # auto-suficiente: se o seletor não está na tela (IG fechado / fora do perfil), abre o
            # IG e navega pro perfil, e re-checa. Assim não depende do chamador ter feito isso.
            try:
                garantir_perfil(d, log)
            except Exception:
                pass
            if not d(resourceId=rid(ACC_SWITCHER)).exists:
                _log(log, "não achei o seletor de contas pra enumerar (IG fora do perfil?)")
                return _saida([], [])
    except Exception:
        return _saida([], [])

    ok, indis = [], []
    ativa_ini = (conta_atual(d) or "").strip().lstrip("@")
    aberto = False
    resolvidas = 0
    try:
        aberto = _abrir_seletor(d)
        if not aberto:
            _log(log, "não consegui abrir o seletor de contas")
            return _saida([], [])
        tratadas = set()
        MAX_RESOLVER = 4
        for _ in range(MAX_RESOLVER + 2):
            linhas = _coletar_linhas(d)
            for ln in linhas:
                if ln["username"]:
                    ok.append(ln["username"])
            susp = next((ln for ln in linhas
                         if ln["suspeita"] and ln["rotulo"].lower() not in tratadas), None)
            if not susp or not resolver or resolvidas >= MAX_RESOLVER:
                if susp:
                    indis.append(susp["rotulo"])   # suspeita que não vamos (ou não dá pra) resolver
                break
            tratadas.add(susp["rotulo"].lower())
            resolvidas += 1
            _log(log, f"conta indisponível no seletor ('{susp['rotulo']}') — tocando pra reativar…")
            u = _resolver_indisponivel(d, susp, log)
            if u:
                ok.append(u)
                _log(log, f"  reativada: @{u}")
            else:
                indis.append(susp["rotulo"])
            if not _no_seletor(d):        # o toque fechou a folha → reabre p/ a próxima passada
                if not _abrir_seletor(d):
                    break
    except Exception as e:
        _log(log, f"falha enumerando o seletor de contas: {e}")
    finally:
        try:
            if aberto:
                _fechar_seletor(d)
        except Exception:
            pass
        # melhor esforço: se um resolver trocou a conta ativa, volta pra original (reversível)
        if resolvidas and ativa_ini:
            try:
                if _no_seletor(d):
                    _fechar_seletor(d)
                atual = (conta_atual(d) or "").strip().lstrip("@")
                if atual and atual.lower() != ativa_ini.lower():
                    trocar_conta(d, ativa_ini, log)
            except Exception:
                pass
    return _saida(ok, indis)


# ─────────────────────── LOGIN / reconectar conta ─────────────
# A tela de login do IG (build ~452) é renderizada via `bloks_container` (UI dirigida por
# servidor): os CAMPOS normalmente NÃO têm resource-id estável. Por isso aqui identificamos tudo
# por CLASSE (android.widget.EditText), ATRIBUTO (password="true") e TEXTO/content-desc — nunca
# por resourceId. O ÚNICO resource-id confiável no fluxo é ACC_SWITCHER (abre o seletor de contas
# a partir do perfil); o botão "Adicionar conta do Instagram" vive DENTRO desse seletor como um
# android.widget.Button com content-desc/texto (confirmado em switcher_dump.xml ao vivo).
ADD_ACCOUNT_TXT = ("Adicionar conta do Instagram", "Adicionar conta existente",
                   "Adicionar conta", "Add account", "Iniciar sessão numa conta existente")
# botão de submeter o login
LOGIN_BTN_TXT = ("Iniciar sessão", "Iniciar sessao", "Iniciar sessão.", "Entrar", "Log in",
                 "Log In", "Iniciar sessão numa conta")
# ir pra forma de login a partir de um menu "adicionar conta" (quando não cai direto no form)
EXISTENTE_TXT = ("Iniciar sessão numa conta existente", "Já tens uma conta",
                 "Ja tens uma conta", "Já tem uma conta", "Iniciar sessão", "Entrar", "Log in")
# diálogo "Guardar/Salvar dados de início de sessão?" — preferimos GUARDAR (mantém a conta logada
# no device, que é o objetivo do reconectar). Fallback = "Agora não".
SALVAR_LOGIN_FRASES = ("guardar as tuas informações", "guardar as informações", "guardar os dados de acesso",
                       "salvar suas informações", "salvar informações de login", "save your login info")
SALVAR_LOGIN_TXT = ("Guardar informações", "Guardar", "Salvar informações", "Salvar", "Save")
AGORA_NAO_TXT = ("Agora não", "Agora nao", "Não agora", "Nao agora", "Not now", "Not Now")
# botões de confirmar código
CONFIRMA_TXT = ("Continuar", "Confirmar", "Seguinte", "Avançar", "Avancar", "Next", "Continue",
                "Submeter", "Confirm", "Verificar")
# palavras que indicam uma tela de CÓDIGO (2FA / verificação por email/SMS)
CODIGO_KW = ("código", "codigo", "code", "confirma", "verifica", "dois fatores",
             "two-factor", "autentica", "6 dígitos", "6 digitos", "segurança")
# erro de credencial
CRED_ERRO_KW = ("palavra-passe estava incorreta", "palavra-passe que introduziste",
                "palavra-passe incorreta", "palavra-passe que inseriste",   # IG 451 (pt-PT), 20/10
                "senha incorreta", "senha que você inseriu", "incorrect password",
                "password you entered", "não foi possível encontrar a tua conta",
                "nao foi possivel encontrar", "couldn't find your account",
                "não encontrámos nenhuma conta", "user not found")
# conta bloqueada/suspensa (não adianta insistir)
BLOQ_LOGIN_KW = ("suspendemos", "suspended", "foi desativada", "desativámos", "conta desativada",
                 "ação bloqueada", "acção bloqueada", "action blocked",
                 "conta não está visível", "conta nao esta visivel")
# desafio "Confirma que és uma pessoa" (captcha do IG, ChallengeActivity) — o bot NÃO resolve; e se a
# conta ficar logada nele, toda abertura do IG cai nessa tela e trava os outros bots (segue15, 20/10)
# login em APARELHO NOVO: "Escolhe uma forma de confirmar que és tu" (notificação no outro aparelho /
# código por e-mail ou SMS) — visto no 1º login do brechó na instância própria (20/10/2026)
ESCOLHER_METODO_KW = ("forma de confirmar", "métodos de confirmação", "metodos de confirmacao",
                      "choose a way to confirm", "confirm it's you", "confirmar que é você",
                      "confirmar que és tu")
NOTIF_OUTRO_KW = ("noutro dispositivo", "em outro dispositivo", "outro dispositivo",
                  "on another device", "another device")
METODO_CODIGO_KW = ("e-mail", "email", "sms", "mensagem de texto", "text message", "whatsapp")
# tela de ESPERA da aprovação (não importa quem escolheu o método): só esperar o toque no celular
AGUARDA_APROV_FORTE = ("a aguardar aprova", "aguardando aprova", "verifica as tuas notifica",
                       "verifique suas notifica", "verifique as notifica", "check your notifications",
                       "waiting for approval")
# depois de pedir a aprovação: "verifica as notificações noutro dispositivo" (espera o toque no celular)
AGUARDA_APROV_KW = ("verifica as notifica", "verifique as notifica", "check your notifications",
                    "aguardando aprova", "a aguardar aprova", "waiting for approval",
                    "aprova o início de sessão", "aprove o login", "approve the login",
                    "noutro dispositivo", "em outro dispositivo", "another device")
DESAFIO_HUMANO_KW = ("confirma que és uma pessoa", "confirme que você é uma pessoa",
                     "confirme que voce e uma pessoa", "confirm you're a human", "confirm that you're a human",
                     "confirm you are a human")


# o agente define: callback(conta) → push "conta com bloqueio" + marca "bloqueada" no backend
AO_DESAFIO = None


def desafio_humano(d):
    """Alguma conta presa em "Confirma que és uma pessoa"? Devolve o @ dela ("?" se não deu pra
    ler) ou None. Essa tela fica na frente do IG inteiro e trava o emulador pra TODAS as contas."""
    try:
        low = _dump(d).lower()
        if not any(k in low for k in DESAFIO_HUMANO_KW):
            return None
        m = re.search(r"(?:tua conta|sua conta|your account),?\s+@?([a-z0-9._]{1,30})", low)
        return m.group(1) if m else "?"
    except Exception:
        return None


def resolver_desafio(d, log=None):
    """Se uma conta caiu em verificação humana: encerra a sessão dela (destrava as outras), avisa via
    AO_DESAFIO e devolve True — quem chamou segue com as contas livres (22/10, segue13)."""
    conta = desafio_humano(d)
    if not conta:
        return False
    _log(log, f"!! @{conta} caiu em verificação humana (\"confirma que és uma pessoa\") — tirando do "
              f"emulador e seguindo com as contas livres")
    sair_do_desafio(d, log)
    if AO_DESAFIO and conta != "?":
        try:
            AO_DESAFIO(conta)
        except Exception:
            pass
    return True


def sair_do_desafio(d, log=None):
    """Na tela "Confirma que és uma pessoa": Menu → "Terminar sessão de <conta>" → "Terminar sessão".
    Tira a conta do aparelho pra o IG voltar pra outra conta logada. True se saiu."""
    try:
        if not d(description="Menu").exists:
            return False
        d(description="Menu").click(); _sleep(1.8, 2.6)
        el = d(textStartsWith="Terminar sessão de")
        if not el.exists:
            el = d(descriptionStartsWith="Terminar sessão de")
        if not el.exists:
            _back_out(d, 1)
            return False
        el.click(); _sleep(1.8, 2.6)
        ok = d(text="Terminar sessão")
        if not ok.exists:
            ok = d(description="Terminar sessão")
        if ok.exists:
            ok.click(); _sleep(4.0, 6.0)
        _log(log, "tirei a conta do aparelho (sessão encerrada) pra não travar os outros bots")
        return True
    except Exception:
        return False


def _edittexts(xml):
    """Lista os campos de texto da tela (ordem vertical). Cada item:
    {bounds, xy=(cx,cy), password:bool, text, desc, hint}. Base da detecção de login (sem rid)."""
    out = []
    for m in re.finditer(r"<node[^>]*/?>", xml or ""):
        t = m.group(0)
        if "EditText" not in _attr(t, "class"):
            continue
        bb = _bounds(t)
        if not bb:
            continue
        out.append({
            "bounds": bb,
            "xy": ((bb[0] + bb[2]) // 2, (bb[1] + bb[3]) // 2),
            "password": _attr(t, "password") == "true",
            "text": _attr(t, "text"),
            "desc": _attr(t, "content-desc"),
            "hint": _attr(t, "hint"),
        })
    out.sort(key=lambda e: e["bounds"][1])
    return out


def _tem_form_login(xml):
    """Heurística: a tela tem um formulário de login? (>=2 campos OU um campo de senha)."""
    eds = _edittexts(xml)
    return len(eds) >= 2 or any(e["password"] for e in eds)


def _tela_de_codigo(xml):
    """A tela pede um CÓDIGO de verificação/2FA? (keyword de código + 1 campo + sem senha)."""
    low = (xml or "").lower()
    if not any(k in low for k in CODIGO_KW):
        return False
    eds = _edittexts(xml)
    return len(eds) >= 1 and not any(e["password"] for e in eds)


def _tocar_botao(d, textos, exato=True, y_min=0, preferir="baixo"):
    """Toca (por coordenada) o elemento cujo text/content-desc casa um de `textos`. `exato`=match
    exato (case-insensitive) vs substring. `preferir`='baixo' pega o candidato mais ABAIXO (botões
    de ação ficam no rodapé), 'cima' o mais acima. Devolve True se tocou."""
    xml = _dump(d)
    cands = []
    for m in re.finditer(r"<node[^>]*/?>", xml):
        t = m.group(0)
        alvo = (_attr(t, "text").strip() or _attr(t, "content-desc").strip())
        if not alvo:
            continue
        al = alvo.lower()
        bate = any(al == c.lower() for c in textos) if exato \
            else any(c.lower() in al for c in textos)
        if not bate:
            continue
        bb = _bounds(t)
        if not bb or bb[3] < y_min:
            continue
        cands.append(bb)
    if not cands:
        return False
    bb = (max if preferir == "baixo" else min)(cands, key=lambda b: b[1])
    try:
        d.click((bb[0] + bb[2]) // 2, (bb[1] + bb[3]) // 2)
        return True
    except Exception:
        return False


def _digitar_humano(d, xy, texto, log=None, rotulo="texto"):
    """Foca o campo (toque nas coords) e digita `texto` em pedaços curtos com micro-pausas, pra
    parecer humano. NUNCA loga o conteúdo — só o rótulo. Usa o IME do uiautomator2 (send_keys),
    que normalmente NÃO abre teclado visível (não cobre os botões); fallback set_text."""
    texto = str(texto or "")
    x, y = xy
    try:
        d.click(x, y)
    except Exception:
        pass
    _sleep(0.6, 1.2)
    i, primeiro, digitou = 0, True, False
    while i < len(texto):
        n = random.randint(2, 4)
        pedaco = texto[i:i + n]
        i += n
        try:
            d.send_keys(pedaco, clear=primeiro)   # 1º pedaço limpa o campo; resto concatena
            primeiro, digitou = False, True
        except Exception:
            break
        _sleep(0.15, 0.45)
    if not digitou and texto:
        # fallback robusto: joga tudo de uma vez no campo focado
        try:
            d.send_keys(texto, clear=True)
        except Exception:
            try:
                d(focused=True).set_text(texto)
            except Exception:
                try:
                    el = d(className="android.widget.EditText")
                    if el.exists:
                        el.set_text(texto)
                except Exception:
                    pass
    _log(log, f"{rotulo} preenchido")


def _back_out(d, n=4):
    """Volta `n` vezes pra estabilizar a tela (deixar o app num estado não-quebrado)."""
    for _ in range(n):
        try:
            d.press("back")
            _sleep(0.8, 1.4)
        except Exception:
            pass


def _tocar_adicionar_conta(d, log):
    """Dentro do seletor de contas: toca 'Adicionar conta do Instagram'. True se tocou."""
    for cand in ADD_ACCOUNT_TXT:
        for sel in (d(descriptionContains=cand), d(textContains=cand)):
            try:
                if sel.exists:
                    sel.click()
                    _log(log, "toquei 'adicionar conta'")
                    return True
            except Exception:
                pass
    return False


def _entrar_form_existente(d, log):
    """Se depois de 'adicionar conta' aparecer um menu (iniciar sessão vs criar conta) em vez do
    formulário, toca na opção de ENTRAR numa conta existente até o formulário aparecer."""
    if _tem_form_login(_dump(d)):
        return True
    for cand in EXISTENTE_TXT:
        el = d(textContains=cand)
        try:
            if el.exists:
                el.click()
                _sleep(2.0, 3.0)
                if _tem_form_login(_dump(d)):
                    return True
        except Exception:
            pass
    return _tem_form_login(_dump(d))


def _abrir_tela_login(d, user, log):
    """Leva o app a um formulário de login da conta `user`. Devolve:
       'form'   → há um formulário de login/re-senha na tela (preencher a seguir);
       'trocou' → a conta já estava logada e só trocamos pra ela (nada a digitar);
       None     → não consegui chegar num login (ex: conta ativa numa parede de bloqueio)."""
    # (a) já tem formulário na tela? (caso comum do "reconectar": a sessão caiu e o IG já abriu
    #     deslogado numa tela de login) — nem precisa do seletor.
    if _tem_form_login(_dump(d)):
        return "form"
    # (b) caminho pelo perfil → seletor de contas
    if garantir_perfil(d, log):
        try:
            tem_sw = d(resourceId=rid(ACC_SWITCHER)).exists
        except Exception:
            tem_sw = False
        if tem_sw:
            try:
                d(resourceId=rid(ACC_SWITCHER)).click()
            except Exception:
                pass
            _sleep(1.8, 2.8)
            # a conta aparece como linha no seletor? (content-desc começa pelo username)
            try:
                linha = d(descriptionStartsWith=user)
                existe_linha = linha.exists
            except Exception:
                existe_linha, linha = False, None
            if existe_linha:
                try:
                    linha.click()
                except Exception:
                    pass
                _sleep(3.0, 4.5)
                # trocou direto (sessão ainda viva)?
                try:
                    if garantir_perfil(d, log) and conta_atual(d) == user:
                        return "trocou"
                except Exception:
                    pass
                # senão deve ter caído numa tela de re-senha/login
                if _tem_form_login(_dump(d)):
                    return "form"
            # (c) não estava logada → adicionar conta e ir pro formulário
            if _tocar_adicionar_conta(d, log):
                _sleep(2.5, 4.0)
                if _entrar_form_existente(d, log):
                    return "form"
    # (d) último recurso
    if _tem_form_login(_dump(d)):
        return "form"
    return None


def _preencher_login(d, user, senha, log):
    """Preenche o formulário de login. Detecta re-senha (só campo de senha) vs form completo
    (usuário + senha). NUNCA loga a senha. Devolve True se preencheu a senha."""
    eds = _edittexts(_dump(d))
    if not eds:
        return False
    campos_user = [e for e in eds if not e["password"]]
    tem_pw = any(e["password"] for e in eds)
    # RE-SENHA: um único campo e ele é de senha (usuário já identificado pelo IG)
    if tem_pw and not campos_user:
        _log(log, "tela de re-senha (usuário já reconhecido) — digitando senha…")
        _digitar_humano(d, next(e for e in eds if e["password"])["xy"], senha, log, "senha")
        return True
    # FORM COMPLETO: usuário no 1º campo não-senha
    if campos_user:
        _log(log, "digitando usuário…")
        _digitar_humano(d, campos_user[0]["xy"], user, log, "usuário")
        _sleep(0.8, 1.6)
    # relê a tela (digitar pode ter reflowado o layout) pra achar o campo de senha certo
    eds2 = _edittexts(_dump(d))
    pw = next((e for e in eds2 if e["password"]), None)
    if pw is None and len(eds2) >= 2:
        pw = eds2[1]       # sem flag de senha legível → assume o 2º campo
    if pw is None:
        _log(log, "não achei o campo de senha")
        return False
    _log(log, "digitando senha…")
    _digitar_humano(d, pw["xy"], senha, log, "senha")
    return True


def _fechar_dialogos_pos(d, log):
    """Fecha diálogos pós-login conhecidos (salvar dados de login; ativar notificações).
    Devolve True se fechou algum."""
    fez = False
    xml = _dump(d)
    low = xml.lower()
    # "Guardar/Salvar as informações de início de sessão?" → GUARDAR (mantém logado no device).
    # guardar: "A AGUARDAR aprovação" (tela de aprovar no outro aparelho) NÃO é esse diálogo — o
    # substring casava e o bot ficava tocando na tela de espera a cada 3s (brechó 20/10)
    # frase COMPLETA do diálogo primeiro ("Guardar as tuas informações de acesso?", brechó 21/10) —
    # ela não depende de nada mais na tela (antes o bot ficou 3 min parado nela)
    if any(k in low for k in SALVAR_LOGIN_FRASES):
        if _tocar_botao(d, ("Guardar", "Salvar", "Save"), exato=True) or                 _tocar_botao(d, AGORA_NAO_TXT, exato=True):
            _log(log, "diálogo salvar-login tratado")
            _sleep(1.2, 2.0)
            return True
    if any(k in low for k in AGUARDA_APROV_FORTE):
        return False
    if ((re.search(r"guardar", low) or "salvar" in low or "save your login" in low) and
            ("início de sessão" in low or "inicio de sessao" in low or "dados de login" in low or
             "login info" in low or "informações de" in low or "informacoes de" in low)):
        if (_tocar_botao(d, SALVAR_LOGIN_TXT, exato=False) or
                _tocar_botao(d, AGORA_NAO_TXT, exato=True)):
            _log(log, "diálogo salvar-login tratado")
            fez = True
            _sleep(1.2, 2.0)
            xml = _dump(d)
            low = xml.lower()
    # "Ativar notificações" → Agora não
    if "notifica" in low and ("ativar" in low or "ative" in low or "ativa as" in low or
                              "turn on" in low or "receber notifica" in low):
        if (_tocar_botao(d, AGORA_NAO_TXT, exato=True) or
                _tocar_botao(d, AGORA_NAO_TXT, exato=False)):
            _log(log, "notificações: agora não")
            fez = True
            _sleep(1.0, 1.8)
    return fez


def _tocar_entrar(d, log):
    """Toca o botão de iniciar sessão. Fallback: tecla enter (submete do campo de senha)."""
    if _tocar_botao(d, LOGIN_BTN_TXT, exato=True) or _tocar_botao(d, LOGIN_BTN_TXT, exato=False):
        _log(log, "toquei 'Entrar'")
        return True
    try:
        d.press("enter")
        _log(log, "submeti com enter (botão não localizado)")
        return True
    except Exception:
        return False


def _resolver_pos_login(d, user, get_codigo, log):
    """Depois de tocar Entrar: resolve diálogos, 2FA/código e confirma sucesso. Teto global ~6min
    (por causa do 2FA). Devolve {ok, motivo}. NUNCA loga o código."""
    fim = time.time() + 360
    pediu_codigo = False
    cod_deadline = None
    aprov_pedida = False     # já escolheu "notificação noutro dispositivo"?
    metodo_tentou = 0
    while time.time() < fim:
        xml = _dump(d)
        low = xml.lower()

        # 1) erro de credencial → aborta
        if any(k in low for k in CRED_ERRO_KW):
            _log(log, "falhou: o Instagram disse que a senha está incorreta — confere a senha salva em Contas")
            _back_out(d, 3)
            return {"ok": False, "motivo": "credenciais_invalidas"}

        # 2) 2FA / código de verificação
        if _tela_de_codigo(xml):
            if get_codigo is None:
                _log(log, "falhou: 2FA pedido mas não há canal de código")
                _back_out(d, 3)
                return {"ok": False, "motivo": "sem_codigo"}
            if not pediu_codigo:
                _log(log, "aguardando código… (digite o código no app)")
                pediu_codigo = True
                cod_deadline = time.time() + 300   # ~5min pro usuário informar
            cod = None
            try:
                cod = get_codigo(user)
            except Exception:
                cod = None
            if cod:
                _log(log, "código recebido — digitando…")
                eds = _edittexts(_dump(d))
                if eds:
                    _digitar_humano(d, eds[0]["xy"], str(cod).strip(), log, "código")
                    _sleep(0.8, 1.6)
                    if not _tocar_botao(d, CONFIRMA_TXT, exato=False):
                        try:
                            d.press("enter")
                        except Exception:
                            pass
                    _sleep(3.5, 5.0)
                continue
            if cod_deadline and time.time() > cod_deadline:
                _log(log, "falhou: código não chegou em ~5min")
                _back_out(d, 3)
                return {"ok": False, "motivo": "sem_codigo"}
            time.sleep(5)   # polling ~5s
            continue

        # 2b) aparelho novo → "Escolhe uma forma de confirmar que és tu": pede a NOTIFICAÇÃO no outro
        #     aparelho (o celular aprova com um toque); sem ela, "Mostrar mais" → código por e-mail/SMS
        #     (cai no fluxo de código do passo 2, que o app manda pela chave da conta)
        if any(k in low for k in ESCOLHER_METODO_KW) and not _tela_de_codigo(xml) and metodo_tentou < 4:
            metodo_tentou += 1
            if any(k in low for k in NOTIF_OUTRO_KW) and _tocar_botao(d, NOTIF_OUTRO_KW, exato=False, preferir="cima"):
                _sleep(0.8, 1.4)
                _tocar_botao(d, CONFIRMA_TXT)
                _log(log, f"o Instagram pediu pra confirmar o login: abre o Instagram no celular (na conta "
                          f"@{user}) e toca em aprovar — espero até 5 min")
                aprov_pedida = True
                fim = max(fim, time.time() + 330)
                _sleep(3.0, 4.5)
                continue
            if _tocar_botao(d, ("Mostrar mais", "Ver mais", "Show more", "Mais opções"), exato=False):
                _sleep(1.2, 2.0)
                xml2 = _dump(d).lower()
                if any(k in xml2 for k in METODO_CODIGO_KW) and _tocar_botao(d, METODO_CODIGO_KW, exato=False, preferir="cima"):
                    _sleep(0.8, 1.4)
                    _tocar_botao(d, CONFIRMA_TXT)
                    _log(log, "o Instagram vai mandar um código (e-mail/SMS) — quando chegar, toque na "
                              f"chave da @{user} em Contas e digite")
                    fim = max(fim, time.time() + 330)
                    _sleep(3.0, 4.5)
                    continue
            _sleep(2.0, 3.0)
            continue

        # 2c) esperando a aprovação no outro aparelho → só espera o toque no celular (a tela some
        #     sozinha quando aprova). Vale também se o método foi escolhido por fora do bot.
        if (any(k in low for k in AGUARDA_APROV_FORTE)
                or (aprov_pedida and any(k in low for k in AGUARDA_APROV_KW)))                 and not d(resourceId=rid(PROFILE_TAB)).exists:
            if _fechar_dialogos_pos(d, log):   # aprovou e já veio o "guardar informações"
                continue
            if not aprov_pedida:
                _log(log, f"esperando você aprovar o login no celular (conta @{user}) — até 5 min")
                aprov_pedida = True
                fim = max(fim, time.time() + 330)
            time.sleep(5)
            continue

        # 3a) "Confirma que és uma pessoa" (captcha) → não dá pra resolver sozinho: avisa, tira a conta
        #     do aparelho (senão trava os outros bots) e segue — sem esperar os 6 min do teto
        if any(k in low for k in DESAFIO_HUMANO_KW):
            _log(log, "falhou: o Instagram pediu pra confirmar que é uma pessoa (captcha) — "
                      "isso só dá pra fazer na mão")
            sair_do_desafio(d, log)
            return {"ok": False, "motivo": "desafio_humano"}

        # 3) conta bloqueada/suspensa (parede do IG) → aborta
        if any(k in low for k in BLOQ_LOGIN_KW):
            _log(log, "falhou: conta bloqueada/suspensa pelo IG")
            _back_out(d, 2)
            return {"ok": False, "motivo": "conta_bloqueada"}

        # 4) diálogos pós-login (salvar login / notificações)
        if _fechar_dialogos_pos(d, log):
            _sleep(1.0, 2.0)
            continue

        # 5) logado? (barra com perfil/direct presente) → confirma a conta
        try:
            logado = d(resourceId=rid(PROFILE_TAB)).exists or d(resourceId=rid(DIRECT_TAB)).exists
        except Exception:
            logado = False
        if logado:
            _fechar_dialogos_pos(d, log)
            try:
                if conta_atual(d) == user or trocar_conta(d, user, log):
                    _log(log, f"logado: @{user}")
                    return {"ok": True, "motivo": "ok"}
            except Exception:
                pass

        _sleep(2.0, 3.0)

    _log(log, "falhou: tempo esgotado no pós-login")
    _back_out(d, 3)
    return {"ok": False, "motivo": "timeout_pos_login"}


def _login_conta_salva(d, user, get_codigo, log, senha=None):
    """Loga @user pela lista de CONTAS SALVAS do device: abre o seletor → 'Adicionar conta do
    Instagram' → 'Iniciar sessão numa conta existente' → TOCA a conta na lista (o device loga com a
    credencial guardada; foi o que o Vinicius fez na mão). Se a conta NÃO estiver na lista salva e
    veio `senha`, preenche o formulário user/senha (legível no MuMu; no LDPlayer era GL/ilegível) —
    senão devolve nao_na_lista_salva pra logar na mão. Pós-login tratado por _resolver_pos_login
    (diálogos, 2FA via get_codigo, confirma conta_atual==user). NUNCA levanta sem back-out."""
    try:
        garantir_perfil(d, log)
    except Exception:
        pass
    try:
        if d(resourceId=rid(ACC_SWITCHER)).exists:
            d(resourceId=rid(ACC_SWITCHER)).click(); _sleep(1.6, 2.4)
    except Exception:
        pass
    add = d(descriptionContains="Adicionar conta")
    if not add.exists:
        add = d(textContains="Adicionar conta")
    if not add.exists:
        _log(log, "falhou: não achei 'Adicionar conta' no seletor")
        _back_out(d, 2)
        return {"ok": False, "motivo": "sem_adicionar_conta"}
    add.click(); _sleep(2.2, 3.2)
    ex = d(descriptionContains="conta existente")
    if not ex.exists:
        ex = d(textContains="conta existente")
    if not ex.exists:
        ex = d(descriptionContains="Iniciar sess")
    if not ex.exists:
        ex = d(textContains="Iniciar sess")
    if not ex.exists:
        _log(log, "falhou: não achei 'Iniciar sessão numa conta existente'")
        _back_out(d, 3)
        return {"ok": False, "motivo": "sem_iniciar_sessao"}
    ex.click()

    def _salva():
        # a conta `user` na lista de contas salvas (content-desc = username, às vezes "user, ...")
        for sel in (d(description=user), d(descriptionStartsWith=user + ","), d(descriptionStartsWith=user)):
            if sel.exists:
                return sel
        return None

    def _outro():
        for sel in (d(descriptionContains="outro perfil"), d(textContains="outro perfil")):
            if sel.exists:
                return sel
        return None

    # a tela seguinte demora a montar (mais ainda logo depois de reiniciar o IG — 19/10 a segue14
    # falhou por ler cedo demais): espera a conta salva, o 'Usar outro perfil' ou o formulário
    alvo = None
    for _ in range(14):
        _sleep(0.9, 1.3)
        alvo = _salva()
        if alvo is not None or _outro() is not None or _tem_form_login(_dump(d)):
            break
    if alvo is None and senha:
        # conta nova no device: no MuMu o formulário user/senha é LEGÍVEL (no LDPlayer era GL e não
        # dava) → preenche com a senha que veio no job. Com contas salvas no device, o IG mostra
        # antes o perfil salvo ('Continuar') — 'Usar outro perfil' leva pro formulário.
        if not _tem_form_login(_dump(d)):
            outro = _outro()
            if outro is not None:
                outro.click()
                for _ in range(10):
                    _sleep(0.9, 1.3)
                    if _tem_form_login(_dump(d)):
                        break
        if _tem_form_login(_dump(d)) and _preencher_login(d, user, senha, log):
            _sleep(0.8, 1.6)
            _tocar_entrar(d, log)
            _sleep(4.0, 6.0)
            return _resolver_pos_login(d, user, get_codigo, log)
        _log(log, "formulário de login não apareceu")
    if alvo is None:
        _log(log, f"@{user} não está na lista de contas salvas do device e não deu pelo "
                  f"formulário — precisa logar NA MÃO.")
        _back_out(d, 4)
        return {"ok": False, "motivo": "nao_na_lista_salva"}
    _log(log, f"tocando @{user} na lista de contas salvas…")
    alvo.click(); _sleep(3.5, 5.5)
    return _resolver_pos_login(d, user, get_codigo, log)


def login_conta(d, user, senha, get_codigo=None, log=None):
    """Reconecta/loga a conta `user` no app do IG do device (uiautomator2), de forma HUMANA e
    conservadora (toques, digitação em pedaços com pausas). Detecta o estado pela tela:
      - já logado nessa conta        → nada a fazer;
      - conta no seletor, sessão viva → só troca pra ela;
      - re-senha (só senha)           → digita a senha;
      - adicionar conta (user+senha)  → digita os dois.
    Trata 2FA/verificação via get_codigo(user) em polling (~5min) e os diálogos pós-login
    (salvar dados de login; ativar notificações). NUNCA loga a senha nem o código.

    get_codigo: callable(user) -> str | None  (código que o usuário digitou no app; None = ainda
                não veio). Opcional: sem ele, uma tela de 2FA aborta com motivo 'sem_codigo'.
    Devolve {"ok": bool, "motivo": str}. Blindado: qualquer exceção → {ok:False,...} + back-out
    pra não deixar o app num estado quebrado."""
    user = (user or "").strip().lstrip("@")
    try:
        if not user:
            return {"ok": False, "motivo": "sem_usuario"}

        _log(log, f"reconectando @{user} no device…")
        if not garantir_app(d, log):
            _log(log, "falhou: não consegui abrir o Instagram")
            return {"ok": False, "motivo": "app_nao_abriu"}
        _sleep(1.2, 2.0)

        # 0) o IG já abriu NA TELA DE LOGIN (aparelho sem conta nenhuma — ex: a instância própria
        #    do brechó): preenche direto, não tem seletor de contas pra abrir. Numa instância que
        #    ACABOU de ligar o IG demora a montar a tela → espera até ~15s (olhar cedo levou o login
        #    pro caminho do seletor e falhou — run-401, 20/10)
        if senha:
            for _ in range(6):
                if d(resourceId=rid(PROFILE_TAB)).exists:
                    break
                if _tem_form_login(_dump(d)):
                    _log(log, "o Instagram está na tela de login — preenchendo")
                    if _preencher_login(d, user, senha, log):
                        _sleep(0.8, 1.6)
                        _tocar_entrar(d, log)
                        _sleep(4.0, 6.0)
                        return _resolver_pos_login(d, user, get_codigo, log)
                    break
                _sleep(2.0, 3.0)

        # já está ativo nessa conta?
        try:
            if conta_atual(d) == user:
                _log(log, f"logado: @{user} (já estava ativo)")
                return {"ok": True, "motivo": "ja_logado"}
        except Exception:
            pass

        # 1) conta já logada no device (no seletor) com sessão viva → só troca pra ela
        try:
            if trocar_conta(d, user, log):
                _log(log, f"logado: @{user} (troquei pela conta já logada)")
                return {"ok": True, "motivo": "trocou"}
        except Exception:
            pass

        # 2) lista de contas salvas (toca a conta, sem digitar); conta NOVA no device → formulário
        #    user/senha com a `senha` do job (MuMu; no LDPlayer o form era ilegível).
        return _login_conta_salva(d, user, get_codigo, log, senha=senha)
    except Exception as e:
        _log(log, f"falhou: erro inesperado ({e})")
        try:
            _back_out(d, 5)
        except Exception:
            pass
        return {"ok": False, "motivo": f"erro:{e}"}


# ─────────────────────── navegação da thread ──────────────────
def em_thread(d, nome_chat=None):
    """True se estamos DENTRO da conversa certa (caixa de escrever presente + título bate).
    O título da thread é 'thread_title' (header_title é da inbox). Tolerante a atraso do título.
    Conta RESTRITA (segue13): o chat abre SEM caixa de escrever (no lugar vem o aviso), mas os posts
    aparecem e dá pra seguir normal — aí vale o aviso + título/nome do chat no cabeçalho."""
    if not d(resourceId=rid("row_thread_composer_edittext")).exists:
        if not conta_restrita(d):
            return False
        th = d(resourceId=rid("thread_title"))
        return th.exists or (bool(nome_chat) and d(textContains=nome_chat[:12]).exists)
    if nome_chat:
        th = d(resourceId=rid("thread_title"))
        try:
            if th.exists:
                return nome_chat[:12] in (th.info.get("text") or "")
        except Exception:
            pass
        return True   # composer presente mas título não lido ainda → assume que é a certa
    return True


RESTRITA_KW = (
    "podes enviar mensagens", "pode enviar mensagens", "padrões da comunidade",
    "padroes da comunidade", "ações limitadas", "acoes limitadas", "limitámos", "limitamos",
)


def conta_restrita(d):
    """True se o IG restringiu a conta: o chat abre mas SEM caixa de mensagem, com aviso tipo
    'Não podes enviar mensagens… Padrões da Comunidade'. (segue13) — saúde da conta, não bug."""
    try:
        xml = (_dump(d) or "").lower()
    except Exception:
        return False
    return any(k in xml for k in RESTRITA_KW)


def abrir_thread(d, nome_chat, log):
    """Abre a aba Direct e entra no chat pelo nome. Devolve True se entrou."""
    _log(log, f"abrindo chat '{nome_chat}'…")
    # se já estamos NESSA thread, não precisa navegar
    if em_thread(d, nome_chat):
        _log(log, "já estava na thread")
        return True
    # garante que a aba Direct está acessível (sai de telas internas com back)
    for _ in range(4):
        if d(resourceId=rid(DIRECT_TAB)).exists:
            break
        d.press("back")
        _sleep(1.0, 1.6)
    if not d(resourceId=rid(DIRECT_TAB)).exists:
        _log(log, "não achei a aba Direct")
        return False
    d(resourceId=rid(DIRECT_TAB)).click()
    _sleep(2.0, 3.0)

    def _achar():
        a = d(textStartsWith=nome_chat)
        if not a.exists:
            a = d(textContains=nome_chat[:14])
        return a

    def _abriu():
        return em_thread(d, nome_chat)   # aceita chat de conta restrita (sem caixa de escrever)

    # tenta na lista; se não achar, ATUALIZA (pull-to-refresh) e tenta de novo.
    # (ao trocar de conta a inbox vem com cache e o grupo pode não aparecer na hora.)
    for tent in range(3):
        alvo = _achar()
        if alvo.exists:
            alvo.click()
            _sleep(2.5, 3.5)
            if _abriu():
                if conta_restrita(d):
                    _log(log, "thread aberta (conta RESTRITA de DM — vê os posts e segue normal)")
                else:
                    _log(log, "thread aberta")
                return True
            _sleep(1.0, 1.5)
            if d(resourceId=rid(DIRECT_TAB)).exists:
                d(resourceId=rid(DIRECT_TAB)).click()
            else:
                d.press("back")
            _sleep(1.5, 2.5)
        if tent < 2:
            _log(log, "chat não visível — atualizando a inbox…")
            d.swipe(540, 700, 540, 1500, 0.3)   # pull-to-refresh
            _sleep(3.0, 4.0)

    # fallback: busca das DMs
    if _abrir_por_busca(d, nome_chat, log) and _abriu():
        _log(log, "thread aberta (via busca)")
        return True
    _log(log, "chat não encontrado (lista + refresh + busca)")
    return False


def _abrir_por_busca(d, nome_chat, log):
    """Fallback: usa a barra de busca da inbox pra achar e abrir o chat."""
    _log(log, "procurando o chat na busca das DMs…")
    sr = d(resourceId=rid("search_row"))
    if not sr.exists:
        sr = d(text="Pesquisar")
    if not sr.exists:
        return False
    sr.click()
    _sleep(1.2, 2.0)
    ed = d(className="android.widget.EditText")
    try:
        if ed.exists:
            ed.set_text(nome_chat[:14])
        else:
            d.send_keys(nome_chat[:14], clear=True)
    except Exception:
        return False
    _sleep(2.5, 3.5)
    alvo = d(textStartsWith=nome_chat)
    if not alvo.exists:
        alvo = d(textContains=nome_chat[:14])
    if not alvo.exists:
        return False
    alvo.click()
    _sleep(2.5, 3.5)
    return True


def posts_na_tela(d):
    """Lê a thread e devolve os cards compartilhados visíveis:
    [{'tap','y1','y2','reagido','autor','ehpost'}] de cima pra baixo.
    ehpost=True = post/reel COM mídia (tem curtidas pra seguir); False = perfil/nota/texto."""
    xml = _dump(d)
    blk = _bloqueio(xml)
    # conta RESTRITA de DM: o aviso fixo do chat pode ter "restringimos"/"limitamos" — isso NÃO é
    # bloqueio de ação (a conta segue normal). Com o aviso na tela, só vale bloqueio FORTE.
    if blk and blk not in BLOQUEIO_FORTE and any(k in xml.lower() for k in RESTRITA_KW):
        blk = None
    pills = []       # (bounds) das REAÇÕES de verdade = emoji_image (NÃO o botão "toca p/ reagir",
                     # que é reaction_add_icon dentro do mesmo message_reactions_pill_container)
    medias = []      # (bounds) dos media_container (indica POST com mídia)
    autores = []     # (y_topo, texto) de title/username (nome do autor)
    caps = []        # (y_topo, texto) de caption_title (legenda — distingue posts do mesmo autor)
    for m in re.finditer(r"<node[^>]*/?>", xml):
        t = m.group(0)
        rid_ = _attr(t, "resource-id")
        if rid_.endswith("/emoji_image"):
            bb = _bounds(t)
            if bb:
                pills.append(bb)
        elif rid_.endswith("/media_container"):
            bb = _bounds(t)
            if bb:
                medias.append(bb)
        elif (rid_.endswith("/title") or rid_.endswith("/username")) and _attr(t, "text"):
            bb = _bounds(t)
            if bb:
                autores.append((bb[1], _attr(t, "text")))
        elif rid_.endswith("/caption_title") and _attr(t, "text"):
            bb = _bounds(t)
            if bb:
                caps.append((bb[1], _attr(t, "text")))
    posts = []
    for m in re.finditer(r"<node[^>]*/?>", xml):
        t = m.group(0)
        if not _attr(t, "resource-id").endswith(XMA_BUBBLE):
            continue
        bb = _bounds(t)
        if not bb:
            continue
        x1, y1, x2, y2 = bb
        tap = ((x1 + x2) // 2, int(y1 + 0.55 * (y2 - y1)))
        reagido = any((y2 - 80) <= p[1] <= (y2 + 80) and p[0] < x1 + 300 for p in pills)
        cand = [a for a in autores if y1 - 10 <= a[0] <= y1 + 110]
        autor = min(cand, key=lambda a: abs(a[0] - (y1 + 45)))[1] if cand else "?"
        # POST = tem um media_container DENTRO da bolha e é alto (mídia de verdade).
        # perfil/nota compartilhada não tem media_container (ou é baixinha).
        tem_media = any(x1 - 5 <= md[0] and md[3] <= y2 + 5 and md[1] >= y1 - 5 for md in medias)
        ehpost = tem_media and (y2 - y1) > 320
        legs = [(c[0], c[1]) for c in caps if y1 <= c[0] <= y2]
        legenda = min(legs)[1] if legs else ""
        autor = _autor_da_legenda(autor, legenda)
        posts.append({"tap": tap, "y1": y1, "y2": y2, "reagido": reagido, "autor": autor,
                      "chave": _chave_post(autor, legenda), "ehpost": ehpost})
    if not posts:
        # layout NOVO do IG (Compose, sem resource-id na lista: xma_bubble/media_container/
        # emoji_image não existem — visto na segue12 em 19/10). Lê pela geometria.
        posts = _posts_compose(xml)
    # INTEIRO = o rodapé do card (onde fica a PÍLULA de reação, ~70px abaixo) está visível acima da
    # caixa de escrever. Card cortado embaixo esconde o ❤ → parecia "sem reação": virava pendente
    # falso e o marcar_post reagia de NOVO (o 2º toque TIRA a reação) — print do Vinicius 19/10.
    corte = _fim_lista(xml)
    for p in posts:
        p["inteiro"] = p["y2"] + 70 <= corte
    posts.sort(key=lambda p: p["y1"])
    return posts, blk


def _fim_lista(xml):
    """Y do fim da área visível da conversa: o MENOR entre o fim da lista, o topo da caixa de
    escrever (que fica POR CIMA da lista) e o topo do aviso de conta restrita."""
    cands = []
    for m in re.finditer(r"<node[^>]*/?>", xml):
        t = m.group(0)
        rid_ = _attr(t, "resource-id")
        bb = _bounds(t)
        if not bb:
            continue
        if rid_.endswith("/message_list"):
            cands.append(bb[3])
        elif rid_.endswith("/message_composer_bar") or rid_.endswith("/row_thread_composer_container"):
            cands.append(bb[1])
        elif "podes enviar mensagens" in _attr(t, "text").lower():
            cands.append(bb[1])
    if cands:
        return min(cands)
    ys = [b[3] for b in (_bounds(m.group(0)) for m in re.finditer(r"<node[^>]*/?>", xml)) if b]
    return int(max(ys) * 0.92) if ys else 1450


def _autor_da_legenda(autor, legenda):
    """Card com o TOPO fora da tela vem sem nome ('?'), mas a legenda começa com o @ do autor
    ('gui_lomonaco Tudo que eu faço…') → recupera dali. Sem isso o post não era registrado e o
    marcar_post reagia no 'primeiro pendente visível' (podia ser outro)."""
    if autor and autor != "?":
        return autor
    m = re.match(r"\s*@?([A-Za-z0-9._]{2,30})\s", (legenda or "") + " ")
    return m.group(1) if m else autor


def _chave_post(autor, legenda=""):
    """Chave do post no REGISTRO / feitos_run: autor + começo da legenda (o card não expõe shortcode).
    Só autor juntava 2 posts do mesmo perfil num só → o 2º era pulado como 'feito'. Sem legenda
    (layout antigo / card sem texto) cai pro autor puro."""
    leg = re.sub(r"\s+", " ", (legenda or "")).strip()[:50]
    return f"{autor}|{leg}" if leg and autor and autor != "?" else autor


def _so_emoji(txt):
    """Texto de PÍLULA DE REAÇÃO: só emoji (+ contagem opcional). Sem letra, e com pelo menos um
    símbolo fora do ASCII (descarta timestamp tipo '2/10, 11:53')."""
    t = (txt or "").strip()
    return (0 < len(t) <= 12 and not any(c.isalpha() for c in t)
            and any(ord(c) > 0x2000 for c in t))


def _posts_compose(xml):
    """Cards no layout Compose (sem ids). Cada mensagem é uma linha MetaComposeView; o card de post
    é a View larga (~360px) que começa na coluna das bolhas, com o NOME do autor no topo e uma
    MÍDIA alta dentro. Reação = TextView só-emoji logo ABAIXO do card, na mesma linha."""
    nos = []
    for m in re.finditer(r"<node[^>]*/?>", xml):
        t = m.group(0)
        bb = _bounds(t)
        if bb:
            nos.append((_attr(t, "class"), bb, _attr(t, "text"), _attr(t, "content-desc")))
    linhas = [bb for cls, bb, _t, _d in nos if cls.endswith("MetaComposeView")]
    posts = []
    for (lx1, ly1, lx2, ly2) in linhas:
        dentro = [(c, b, t, ds) for c, b, t, ds in nos
                  if b[1] >= ly1 and b[3] <= ly2 + 2 and b != (lx1, ly1, lx2, ly2)]
        # card = View na coluna das bolhas (x1 60–130), largura de card, alta
        cards = [b for c, b, t, ds in dentro if c.endswith(".View") and 60 <= b[0] <= 130
                 and 280 <= (b[2] - b[0]) <= 520 and (b[3] - b[1]) > 200]
        if not cards:
            continue
        x1, y1, x2, y2 = max(cards, key=lambda b: b[3] - b[1])
        midias = [b for c, b, t, ds in dentro if x1 - 5 <= b[0] and b[2] <= x2 + 5
                  and y1 <= b[1] and b[3] <= y2 + 5 and (b[3] - b[1]) > 250 and b != (x1, y1, x2, y2)]
        nomes = [(b[1], t) for c, b, t, ds in dentro if c.endswith("TextView") and t
                 and x1 <= b[0] <= x2 and y1 - 5 <= b[1] <= y1 + 110]
        autor = min(nomes)[1] if nomes else "?"
        reagido = any(c.endswith("TextView") and _so_emoji(t) and b[1] >= y2 - 15
                      and b[0] < x1 + 300 for c, b, t, ds in dentro)
        if midias:
            mx1, my1, mx2, my2 = max(midias, key=lambda b: b[3] - b[1])
            tap = ((mx1 + mx2) // 2, (my1 + my2) // 2)
        else:
            my2 = y1 + 110
            tap = ((x1 + x2) // 2, int(y1 + 0.55 * (y2 - y1)))
        # legenda (texto abaixo da mídia) distingue 2 posts do MESMO autor (gui_lomonaco x2, 19/10)
        legs = [(b[1], t) for c, b, t, ds in dentro if c.endswith("TextView") and t
                and x1 <= b[0] <= x2 and b[1] >= my2 - 5 and b[3] <= y2 + 5 and not _so_emoji(t)]
        legenda = min(legs)[1] if legs else ""
        autor = _autor_da_legenda(autor, legenda)
        posts.append({"tap": tap, "y1": y1, "y2": y2, "reagido": reagido, "autor": autor,
                      "chave": _chave_post(autor, legenda),
                      "ehpost": bool(midias) and (y2 - y1) > 320})
    return posts


# ─────────────────────── seguir curtidores ────────────────────
# área útil da folha de curtidores (ignora botões cortados no topo/rodapé)
SHEET_TOP, SHEET_BOTTOM = 840, 1850


def _ler_folha(xml, top=SHEET_TOP, bot=SHEET_BOTTOM):
    """Da folha de curtidores: (nomes_visiveis[], botoes[(username,(cx,cy))]) — só botões
    'Seguir' TOTALMENTE visíveis, de cima pra baixo. nomes = todos os @ visíveis (ordem y).
    top/bot = faixa Y válida (calculada da tela real pelo chamador; o default fixo era de uma
    tela ~1920 e cortava quase tudo num device 900x1600)."""
    nomes = []
    for m in re.finditer(r"<node[^>]*/?>", xml):
        t = m.group(0)
        if _attr(t, "resource-id").endswith(ROW_NAME) and _attr(t, "text"):
            bb = _bounds(t)
            if bb:
                nomes.append(((bb[1] + bb[3]) // 2, _attr(t, "text")))
    nomes.sort()
    botoes = []
    for m in re.finditer(r"<node[^>]*/?>", xml):
        t = m.group(0)
        if _attr(t, "resource-id").endswith(ROW_FOLLOW) and _attr(t, "text").strip() == TXT_SEGUIR:
            bb = _bounds(t)
            if not bb:
                continue
            cy = (bb[1] + bb[3]) // 2
            if not (top <= cy <= bot):   # cortado na borda → não clica
                continue
            cx = (bb[0] + bb[2]) // 2
            uname = min(nomes, key=lambda u: abs(u[0] - cy))[1] if nomes else f"{cx},{cy}"
            botoes.append((cy, uname, (cx, cy)))
    botoes.sort()
    return [n for _, n in nomes], [(u, xy) for _, u, xy in botoes]


def _na_folha(xml):
    return (("/" + ROW_FOLLOW) in xml) or ("row_user_container_base" in xml) or \
           ("layout_container_bottom_sheet" in xml)


def _dialogo_revisao(xml):
    """O IG abre 'Revê esta conta antes de seguires' p/ contas recém-criadas. Detecta."""
    low = xml.lower()
    return ("antes de seguir" in low or "antes de a seguir" in low or
            "esta conta antes" in low or "review this account" in low)


def _confirmar_revisao(d, xml):
    """Toca o 'Seguir' do rodapé do popup (confirma o follow). O botão do popup é
    CENTRALIZADO (centro x ~540) e fica embaixo; os botões da lista ficam à direita (~954).
    True se tocou."""
    try:
        _w, _h = d.window_size()
    except Exception:
        _w, _h = 900, 1600
    for m in re.finditer(r"<node[^>]*/?>", xml):
        t = m.group(0)
        if _attr(t, "text").strip() in ("Seguir", "Follow"):
            bb = _bounds(t)
            if not bb:
                continue
            cx = (bb[0] + bb[2]) // 2
            # centralizado + lá embaixo = o botão do POPUP (não os da lista, que ficam à direita).
            # Relativo à tela real (antes era cx 380-700 + y>=1650, fixo p/ ~1920 → off-screen no 1600).
            if int(_w * 0.33) <= cx <= int(_w * 0.72) and bb[1] >= int(_h * 0.80):
                d.click(cx, (bb[1] + bb[3]) // 2)
                return True
    return False


def _estado_botao(xml, username):
    """Texto do botão da linha do `username` na folha (p/ saber se o follow COLOU).
    'Seguir' = não colou; 'A seguir'/'Solicitado'/'Pedido…'/'Enviar mensagem' = colou. '' = sumiu."""
    nome_y = None
    for m in re.finditer(r"<node[^>]*/?>", xml):
        t = m.group(0)
        if _attr(t, "resource-id").endswith(ROW_NAME) and _attr(t, "text") == username:
            bb = _bounds(t)
            if bb:
                nome_y = (bb[1] + bb[3]) // 2
                break
    if nome_y is None:
        return ""
    melhor, dist = "", 99999
    for m in re.finditer(r"<node[^>]*/?>", xml):
        t = m.group(0)
        if _attr(t, "resource-id").endswith(ROW_FOLLOW) and _attr(t, "text"):
            bb = _bounds(t)
            if bb:
                cy = (bb[1] + bb[3]) // 2
                if abs(cy - nome_y) < dist:
                    dist, melhor = abs(cy - nome_y), _attr(t, "text").strip()
    return melhor if dist < 75 else ""


def seguir_curtidores(d, log, limite=0, entre=(1, 3), pausa_cada=0, pausa_longa=(20, 60),
                      parar_flag=None, base=0, simular=False):
    """Na folha de curtidores ABERTA, segue TODOS (ou até `limite`>0), um por vez relendo a
    tela a cada clique. VERIFICA se cada follow COLOU (o botão mudou de 'Seguir'); se o IG
    desfizer vários seguidos = soft-block → para. Devolve (seguidos, motivo, viu_usuarios).
    motivo: 'fim'|'limite'|f'bloqueio:{x}'|'parado'|'perdido'|'softblock'.
    `base` = follows já feitos ANTES deste post na run — só pra o log mostrar o total ACUMULADO
    (a barra/progresso lê o 'total N' do log; sem isto ela reiniciava a cada post)."""
    seguidos, vistos = 0, set()
    viu_users = False
    prev_vis, sem_mov, desvios, nao_colou = None, 0, 0, 0
    prox_pausa = pausa_cada
    try:
        _w, _h = d.window_size()
    except Exception:
        _h = 1600
    f_top, f_bot = int(_h * 0.14), int(_h * 0.95)   # faixa Y válida p/ os botões, da tela REAL
    while True:
        if parar_flag and parar_flag():
            return seguidos, "parado", viu_users
        xml = _dump(d)
        blk = _bloqueio(xml)
        if blk:
            return seguidos, f"bloqueio:{blk}", viu_users
        if _dialogo_revisao(xml):
            # IG pediu pra revisar a conta antes de seguir (conta recém-criada) → confirma
            if _confirmar_revisao(d, xml):
                _log(log, "  (confirmei o aviso 'revê esta conta antes de seguir')")
            else:
                d.press("back")
            _sleep(1.0, 2.0)
            continue
        if not _na_folha(xml):
            # um clique pode ter aberto um perfil por engano → volta pra folha
            desvios += 1
            if desvios > 6:
                return seguidos, "perdido", viu_users
            d.press("back")
            _sleep(1.0, 1.6)
            continue
        nomes, botoes = _ler_folha(xml, f_top, f_bot)
        if nomes:
            viu_users = True
        novo = next(((u, xy) for u, xy in botoes if u not in vistos), None)
        if novo and simular:
            # SIMULAÇÃO: percorre a lista igual, mas NÃO toca em "Seguir" (conta como se tivesse)
            u = novo[0]
            vistos.add(u)
            seguidos += 1
            k = base + seguidos
            _log(log, f"  + @{str(u).lstrip('@')}  ({k}/{(base + limite) if limite else k}) · simulado")
            if limite and seguidos >= limite:
                return seguidos, "limite", viu_users
            _sleep(0.4, 0.9)
            continue
        if novo:
            u, (x, y) = novo
            vistos.add(u)
            d.click(x, y)
            _sleep(*entre)
            # confirma o popup "revê esta conta" se aparecer (senão o follow não completa)
            xml2 = _dump(d)
            if _dialogo_revisao(xml2):
                _confirmar_revisao(d, xml2)
                _sleep(1.2, 2.0)
                xml2 = _dump(d)
            # VERIFICA se o follow COLOU (o botão saiu de 'Seguir'). Se o IG desfez = soft-block.
            est = _estado_botao(xml2, u)
            if est == TXT_SEGUIR:
                nao_colou += 1
                _log(log, f"  ~ {u}: NÃO colou ({nao_colou}) — IG desfez o follow")
                if nao_colou >= 4:
                    _log(log, "  !! SOFT-BLOCK: IG desfazendo os follows — parando (conta no limite)")
                    return seguidos, "softblock", viu_users
                _sleep(1.5, 2.8)
                continue
            nao_colou = 0
            seguidos += 1
            # log LIMPO e alinhado: "  + @user  (K/den)". K = base+seguidos = follows ACUMULADOS da
            # conta (1º número → é o que os loggers do agente parseiam, ver _RE_FOLLOW no
            # agente_emulador: o formato daqui e o regex de lá foram definidos JUNTOS pra casarem).
            # den = teto da conta quando há limite (base+limite = o cap), senão repete K (sem teto).
            k = base + seguidos
            den = (base + limite) if limite else k
            _log(log, f"  + @{str(u).lstrip('@')}  ({k}/{den})")
            if limite and seguidos >= limite:
                return seguidos, "limite", viu_users
            if pausa_cada:
                prox_pausa -= 1
                if prox_pausa <= 0:
                    p = random.uniform(*pausa_longa)
                    _log(log, f"  …respiro {int(p)}s")
                    time.sleep(p)
                    prox_pausa = pausa_cada
            continue
        # nenhum botão novo visível → rola a folha pra baixo
        atual = tuple(nomes)
        if atual and atual == prev_vis:
            sem_mov += 1
            if sem_mov >= 3:               # lista não mexe mais = chegou no fim
                return seguidos, "fim", viu_users
        else:
            sem_mov = 0
        prev_vis = atual
        _scroll_folha(d)
        _sleep(1.2, 2.0)


# ─────────────────────── reagir (marcar feito) ────────────────
def reagir_coracao(d, tap_xy, log):
    """Long-press na mídia do post e toca ❤️ (1º emoji da barra). Se o emoji não aparecer de
    primeira (menu não abriu), reabre a barra e tenta de novo. Devolve True se reagiu."""
    x, y = tap_xy
    for _tent in range(3):
        d.long_click(x, y, 0.7)
        _sleep(1.0, 1.6)
        xml = _dump(d)
        cands = []
        for m in re.finditer(r"<node[^>]*/?>", xml):
            t = m.group(0)
            if "Rea" in _attr(t, "content-desc") and _attr(t, "resource-id").endswith("/image"):
                bb = _bounds(t)
                if bb:
                    cands.append((bb[0], (bb[0] + bb[2]) // 2, (bb[1] + bb[3]) // 2))
        if cands:
            cands.sort()  # mais à esquerda = ❤️
            _, cx, cy = cands[0]
            d.click(cx, cy)
            _sleep(1.0, 1.6)
            return True
        d.press("back")  # fecha o menu e tenta reabrir
        _sleep(0.6, 1.0)
    return False


# ─────────────────── fronteira (último reagido) + marcação ────
def _assinatura_thread(d):
    """Hash do conteúdo visível (textos + y dos posts) p/ detectar quando a rolagem parou."""
    import hashlib
    xml = _dump(d)
    txts = "|".join(re.findall(r'text="([^"]*)"', xml))
    ys = ",".join(str(_bounds(m.group(0))[1])
                  for m in re.finditer(r"<node[^>]*/?>", xml)
                  if _attr(m.group(0), "resource-id").endswith(XMA_BUBBLE) and _bounds(m.group(0)))
    return hashlib.md5((txts + "#" + ys).encode("utf-8", "ignore")).hexdigest()


def _ir_ao_fundo(d, log=None, max_scrolls=30):
    """Desce a conversa até o fim (post mais NOVO), em passos CONTROLADOS. Necessário porque o IG
    abre o chat no divisor 'Novas mensagens', não no fundo."""
    if log:
        _log(log, "indo ao fim da conversa (mais recente)…")
    prev, estavel = None, 0
    for _ in range(max_scrolls):
        sig = _pos_vis(d)
        if sig == prev:
            estavel += 1
            if estavel >= 2:
                return
        else:
            estavel = 0
        prev = sig
        _scroll_ctrl(d, "baixo")   # passo controlado (sem arremesso) — não pula o fundo
        _assentar(d)


def ir_para_fronteira(d, log, max_scrolls=400, reg=None, parar_flag=None):
    """Vai ao fim e SOBE em passos CONTROLADOS até achar um card já FEITO (reagido OU no REGISTRO
    da frota) — a fronteira. Daí o loop processa pra BAIXO. Usar o registro além da reação é
    ESSENCIAL: as reações não colam, então sem isso ele subia a thread INTEIRA (lento) sem nunca
    achar fronteira. Com o registro, para no 1º post já-feito, pertinho dos novos."""
    _ir_ao_fundo(d, log)
    _sleep(1.0, 1.5)
    _log(log, "subindo (passo controlado) até o último card feito (fronteira)…")
    for i in range(max_scrolls):
        if parar_flag and parar_flag():
            return "parado"   # o processar() vê o flag logo em seguida e encerra sem seguir
        _assentar(d)
        posts, _blk = posts_na_tela(d)
        if any(p["reagido"] or (reg is not None and _feito_recente(reg, p["chave"])) for p in posts):
            _log(log, f"fronteira achada (scroll {i})")
            return "fronteira"
        if not _subir_ctrl(d):
            _log(log, f"cheguei no TOPO da conversa (scroll {i}) sem achar feito — processo todos")
            return "topo"
        if i and i % 25 == 0:
            _log(log, f"  ainda subindo atrás do último reagido… (scroll {i})")
    # NÃO achou a fronteira nem o topo: NÃO começa a seguir num post qualquer do meio
    _log(log, f"!! não achei o último reagido em {max_scrolls} passos — não sigo ninguém nesta conta")
    return None


def ir_para_autor(d, autor, log, max_scrolls=40):
    """Início EXPLÍCITO: vai ao fim e sobe até achar o post do `autor`, deixando-o na tela pra
    o loop começar dali. Determinístico (não depende de reação). True se achou."""
    autor = autor.strip().lstrip("@")
    _log(log, f"procurando o post de '{autor}' pra começar…")
    _ir_ao_fundo(d, log)
    _sleep(1.0, 1.5)
    for i in range(max_scrolls):
        posts, _blk = posts_na_tela(d)
        if any(autor in (p["autor"] or "") for p in posts if p["autor"] != "?"):
            _log(log, f"achei o post de {autor} (scroll {i}) — começando por ele")
            return True
        if not _subir_insistindo(d):
            _log(log, f"cheguei no topo do histórico sem achar '{autor}'")
            return False
    _log(log, f"não achei '{autor}' em {max_scrolls} scrolls")
    return False


def marcar_post(d, log, autor=None):
    """Reage ❤️ no post do `autor` (o que acabou de processar) e confirma a pílula. Se o card
    saiu da tela ao voltar da folha de curtidores, PROCURA rolando (alterna cima/baixo) em vez
    de desistir — senão o post nunca fica marcado e vira reprocesso eterno (outra conta refaz).
    Sem autor, marca o pendente mais antigo visível. Devolve True se marcou."""
    # REGRA: só reage num card que ESTÁ INTEIRO na tela e foi VISTO sem reação. Se o rodapé (pílula)
    # estiver escondido, primeiro traz ele pra tela. Reagir "no escuro" e repetir tirava o ❤ (toggle).
    for tent in range(8):
        _assentar(d)
        posts, _blk = posts_na_tela(d)
        if autor and autor != "?":
            alvo = [p for p in posts if p["chave"] == autor]   # autor = CHAVE do post
            if not alvo:
                # card do post processado pode ter saído da tela → procura (não reage errado)
                antes = _autores_vis(d)
                _scroll(d, "cima" if tent % 2 == 0 else "baixo", forca=1.2)
                _assentar(d)
                if _autores_vis(d) == antes and tent >= 2:
                    return False      # tela travada e não achou → desiste sem marcar errado
                continue
            p = alvo[0]
        else:
            pend = [p for p in posts if not p["reagido"] and p["inteiro"]]
            if not pend:
                return True
            p = pend[0]
        if not p["inteiro"]:
            _scroll_ctrl(d, "baixo")   # rola o conteúdo pra cima → o rodapé (pílula) aparece
            continue
        if p["reagido"]:
            return True                # já tem ❤ visível → NÃO toca de novo (tiraria a reação)
        reagir_coracao(d, p["tap"], log)
        _sleep(1.0, 1.6)
    return False


# ─── registro persistente de posts já concluídos (fonte da verdade da frota) ───
# A reação ❤️ no grupo é instável de LER e de MARCAR (menu de reação finético), então a verdade
# de "esse post já foi feito" vive NESTE arquivo, não na reação. {autor: timestamp}. Chave = autor
# do post (o card do IG não expõe id/shortcode estável). Janela: depois de _FEITOS_JANELA o mesmo
# autor volta a ser processável (cobre re-drop do mesmo perfil). Compartilhado pela frota (1 só PC).
_FEITOS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "posts_feitos.json")
_FEITOS_JANELA = 14 * 24 * 3600   # 14 dias


def _feitos_carregar():
    try:
        with open(_FEITOS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _feitos_salvar(reg):
    try:
        with open(_FEITOS_PATH, "w", encoding="utf-8") as f:
            json.dump(reg, f)
    except Exception:
        pass


def _feito_recente(reg, chave):
    """chave = 'autor|legenda' (ou só 'autor' quando a legenda não deu pra ler — no layout antigo o
    caption_title às vezes vem VAZIO no dump, ex.: legenda começando com aspas).
    - registro com legenda cobre SÓ aquele post;
    - registro só-autor NÃO cobre post com legenda (senão 1 post feito escondia os outros do mesmo
      autor — gui_lomonaco x3, 19/10). Post sem legenda lida: qualquer registro do autor cobre.
    O registro é a 2ª proteção: a 1ª é o ❤ (gruda e é lido nos 2 layouts desde 19/10)."""
    agora = time.time()
    chave = chave or ""

    def _ok(k):
        v = reg.get(k)
        return bool(v) and (agora - v) < _FEITOS_JANELA

    if _ok(chave):
        return True
    if "|" in chave:
        return False
    return any(k.startswith(chave + "|") and _ok(k) for k in reg)


def _marcar_feito(reg, autor):
    if autor and autor != "?":
        reg[autor] = time.time()
        _feitos_salvar(reg)


# ─────────────────────────── orquestração ─────────────────────
def processar(d, log, nome_chat="vaitomanoquasenada", max_posts=0, limite_follows_run=0,
              delay_post=(90, 240), entre=(1, 3), pausa_cada=0, pausa_longa=(20, 60),
              inicio=None, parar_flag=None, simular=False):
    """Fluxo: entra no chat → sobe até a fronteira (último reagido) → processa os posts SEM
    reação em ordem de envio (mais antigo primeiro) → ao seguir TODOS os curtidores, reage ❤️
    pra marcar. Para na hora se bloquear. Devolve dict com o saldo.
    max_posts=0 → até acabar/bloquear; limite_follows_run=0 → sem teto de follows no run."""
    total_follows, posts_feitos = 0, 0
    reg_feitos = _feitos_carregar()   # registro PERSISTENTE (frota) de posts já concluídos
    feitos_run = set()                # autores já tratados NESTE run (mata o reprocesso imediato)
    if not abrir_thread(d, nome_chat, log):
        if conta_restrita(d):
            _log(log, "!! conta RESTRITA pelo IG (não pode mandar DM / ações limitadas) — pulando")
            return {"ok": False, "motivo": "conta_restrita", "follows": 0, "posts": 0}
        return {"ok": False, "motivo": "thread_nao_abriu", "follows": 0, "posts": 0}

    if inicio:
        ir_para_autor(d, inicio, log)
    else:
        # vai ao fundo e SOBE verificando as reações até o ÚLTIMO REAGIDO (a fronteira). Daí processa
        # pra BAIXO, em ordem de envio. NUNCA pega o 1º post do fundo sem antes subir e conferir.
        if ir_para_fronteira(d, log, reg=reg_feitos, parar_flag=parar_flag) is None:
            return {"ok": False, "motivo": "fronteira_nao_achada", "follows": 0, "posts": 0}
    recup = 0
    ultimo_autor, falhas_post = None, 0
    while True:
        if parar_flag and parar_flag():
            return {"ok": True, "motivo": "parado", "follows": total_follows, "posts": posts_feitos}

        # RESILIÊNCIA: se algo tirou a gente da tela do chat (clique acidental, tela errada),
        # volta pro chat e reposiciona no fundo (varre de novo; o registro evita reprocessar).
        if not em_thread(d, nome_chat):
            recup += 1
            _log(log, f"não estou na tela do chat — voltando (recuperação {recup})")
            if recup > 8:
                return {"ok": False, "motivo": "muitas_recuperacoes", "follows": total_follows, "posts": posts_feitos}
            if not abrir_thread(d, nome_chat, log):
                return {"ok": False, "motivo": "thread_nao_abriu", "follows": total_follows, "posts": posts_feitos}
            if inicio:
                ir_para_autor(d, inicio, log)
            elif ir_para_fronteira(d, log, reg=reg_feitos, parar_flag=parar_flag) is None:   # re-verifica a fronteira
                return {"ok": False, "motivo": "fronteira_nao_achada", "follows": total_follows, "posts": posts_feitos}
            continue

        _assentar(d)                      # espera a tela parar antes de ler (a reação não falseia)
        posts, blk = posts_na_tela(d)
        if blk:
            _log(log, f"!! BLOQUEIO: {blk} — parando pra não queimar a conta")
            return {"ok": False, "motivo": f"bloqueio:{blk}", "follows": total_follows, "posts": posts_feitos}

        # FLEET (1 conta por post): qualquer POST de verdade (ehpost: tem mídia/curtidas) SEM
        # reação é pendente. A reação é COMPARTILHADA no grupo = "alguém da frota já fez, pula".
        # NÃO filtra por posição: o antigo 'y1 > último_reagido' jogava fora posts novos que
        # ficavam ACIMA de um reagido na tela → a conta cravava "+0 todos reagidos" errado.
        # Mensagem-indisponível / perfil / nota NÃO entram (ehpost=False, sem curtidas).
        # "feito" = reagido no grupo OU já concluído pela frota (registro) OU já tratado neste run.
        # O REGISTRO é a fonte da verdade (a reação ❤️ é instável de ler/marcar).
        # FRONTEIRA VISÍVEL: o post FEITO (reagido OU registrado) mais BAIXO na tela. Tudo ACIMA dele
        # é passado (já feito pela frota) e NÃO é reprocessado — mesmo que a reação não tenha colado.
        # Só processa o que está ABAIXO da fronteira. Sem nenhum feito na tela = já passei a fronteira
        # (estou no território novo) → processo todos os pendentes visíveis.
        y_fronteira = max((p["y1"] for p in posts
                           if p["reagido"] or _feito_recente(reg_feitos, p["chave"])), default=None)
        # p["inteiro"]: card com rodapé escondido NÃO é pendente ainda (o ❤ pode estar embaixo da
        # caixa de escrever) — o _descer_ctrl traz ele inteiro pra tela na próxima volta.
        pendentes = [p for p in posts if not p["reagido"] and p["ehpost"] and p["inteiro"]
                     and p["chave"] not in feitos_run
                     and not _feito_recente(reg_feitos, p["chave"])
                     and (y_fronteira is None or p["y1"] > y_fronteira)]
        if not pendentes:
            # nada novo abaixo da fronteira NESTA tela → DESCE (passo controlado) rumo ao mais NOVO.
            # A fronteira (último reagido) ficou pra cima; todo o trabalho está abaixo dela, em ordem
            # de envio. "acabou" quando não dá mais pra descer (cheguei no post mais novo = o fim).
            if not _descer_ctrl(d):
                _log(log, "acabou — cheguei no fim (post mais novo)")
                return {"ok": True, "motivo": "fim", "follows": total_follows, "posts": posts_feitos}
            continue

        post = pendentes[0]  # topo da tela (mais antigo visível ABAIXO da fronteira) ainda não feito
        _log(log, f"→ card de {post['autor']}; abrindo…")
        d.click(*post["tap"])
        _sleep(2.5, 3.5)

        lc = d(resourceId=rid(LIKE_COUNT))
        if not lc.exists:
            # pode ser post sem curtidas OU a gente nem abriu o post (tela errada). Só marca se
            # continuarmos no post certo; senão a recuperação do topo cuida no próximo giro.
            _log(log, "  não abriu as curtidas — pulando")
            d.press("back"); _sleep(1.2, 2.0)
            feitos_run.add(post["chave"])   # não reprocessa neste run (sem persistir: pode ser transitório)
            continue
        lc.click()
        _sleep(2.0, 3.0)
        # a folha "Gostos" abre na hora mas a LISTA chega depois (spinner) — com rede lenta 2-3s
        # não bastava e virava "folha não abriu" falso (gui_lomonaco#2, 19/10). Espera até ~10s.
        d(resourceId=rid(ROW_FOLLOW)).wait(timeout=8)
        if not d(resourceId=rid(ROW_FOLLOW)).exists:
            _log(log, "  folha de curtidores não abriu — fechando")
            d.press("back"); _sleep(1.0, 1.6); d.press("back"); _sleep(1.0, 1.6)
            # não trava no mesmo post: após 3 falhas seguidas, marca e segue
            if post["chave"] == ultimo_autor:
                falhas_post += 1
            else:
                ultimo_autor, falhas_post = post["chave"], 1
            if falhas_post >= 3:
                _log(log, f"  {post['autor']} não abre há 3x — pulo")
                feitos_run.add(post["chave"]); falhas_post = 0
            continue

        restante = (limite_follows_run - total_follows) if limite_follows_run else 0
        seguidos, motivo, viu = seguir_curtidores(d, log, limite=restante, entre=entre,
                                                  pausa_cada=pausa_cada, pausa_longa=pausa_longa,
                                                  parar_flag=parar_flag, base=total_follows,
                                                  simular=simular)
        total_follows += seguidos
        _log(log, f"  post: +{seguidos} follows ({motivo})")

        # fecha folha + post → volta pra thread
        d.press("back"); _sleep(1.0, 1.6)
        d.press("back"); _sleep(1.2, 2.0)

        if motivo.startswith("bloqueio"):
            _log(log, f"!! {motivo} — parando")
            return {"ok": False, "motivo": motivo, "follows": total_follows, "posts": posts_feitos}
        if motivo == "softblock":
            _log(log, "!! SOFT-BLOCK — o IG tá desfazendo os follows (conta no limite do dia). Parando.")
            return {"ok": False, "motivo": "softblock", "follows": total_follows, "posts": posts_feitos}

        if motivo == "fim":
            # só conclui se a lista realmente carregou (viu curtidores); senão deixa pendente
            if viu and simular:
                feitos_run.add(post["chave"])       # simulação: não registra nem reage ❤
                _log(log, f"  (simulação: não marquei o post de {post['autor']})")
                posts_feitos += 1
            elif viu:
                feitos_run.add(post["chave"])
                _marcar_feito(reg_feitos, post["chave"])   # REGISTRO = fonte da verdade (persiste)
                if marcar_post(d, log, post["chave"]):     # ❤️ best-effort (marcador visual na frota)
                    _log(log, f"  ❤️ marcado ({post['autor']})")
                else:
                    _log(log, f"  registrado ({post['autor']}) — não reprocessa")
                posts_feitos += 1
            else:
                _log(log, "  curtidas não carregaram — não concluo (tenta no próximo run)")
        elif motivo in ("limite", "parado"):
            return {"ok": True, "motivo": motivo, "follows": total_follows, "posts": posts_feitos}
        elif motivo == "perdido":
            feitos_run.add(post["chave"])   # move pro próximo neste run; NÃO persiste (post não concluído)
            _log(log, "  perdi a folha no meio — sigo pro próximo sem concluir")

        if max_posts and posts_feitos >= max_posts:
            return {"ok": True, "motivo": "max_posts", "follows": total_follows, "posts": posts_feitos}

        if delay_post and delay_post[1] > 0:
            p = random.uniform(*delay_post)
            _log(log, f"próximo post em {int(p)}s…")
            time.sleep(p)
