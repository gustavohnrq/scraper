from __future__ import annotations

from urllib.parse import quote_plus

from .profile_schema import ClientProfile


ASSINATURA = "Me chamo Gustavo Rodrigues, sou assistente do corretor Julio Barreto, da 61 Imóveis."


def build_profile_summary(profile: ClientProfile) -> str:
    quartos = f"{profile.quartos_exatos} quartos" if profile.quartos_exatos else f"mínimo de {profile.quartos_min} quartos"
    reg = ", ".join(profile.regioes_prioritarias[:2] + profile.regioes_aceitaveis[:1])
    return f"{quartos}, até R$ {profile.preco_max:,.0f} e foco em {reg}".replace(",", ".")


def build_whatsapp_message(profile: ClientProfile, selected: list[dict]) -> str:
    resumo = build_profile_summary(profile)
    links = [i.get("link") for i in selected if i.get("link")][:5]
    if len(links) < 2:
        links = links[:]
    links_block = "\n".join(links)

    tipo_hint = {
        "familia": "priorizando conforto e moradia real",
        "investidor": "priorizando liquidez e potencial de valorização",
        "upgrade": "priorizando ganho de padrão",
    }.get(profile.tipo_cliente.lower(), "priorizando boa aderência")

    return (
        "Olá, tudo bem?\n\n"
        f"{ASSINATURA}\n\n"
        "Separei algumas opções de imóveis dentro do perfil que você busca, "
        f"considerando {resumo}, {tipo_hint}.\n\n"
        f"{links_block}\n\n"
        "Queria entender com você:\n"
        "ainda está buscando imóvel ou já conseguiu resolver essa demanda?\n\n"
        "Caso já esteja sendo atendido por alguém da nossa equipe, me avisa por aqui para eu não duplicar o atendimento.\n\n"
        "Se ainda estiver buscando, posso te direcionar opções ainda mais alinhadas ao que você procura."
    )


def build_wa_me_text(message: str) -> str:
    return quote_plus(message)


def build_wa_me_url(phone: str, encoded_text: str) -> str:
    return f"https://wa.me/{phone}?text={encoded_text}"
