"""Central ECLIPSE visual identity for Discord."""

BRAND_NAME = "ECLIPSE"
TAGLINE = "୨୧ beyond the ordinary ୨୧"
EMOJIS = {"veil": "🌑", "heart": "♡", "ribbon": "🎀", "spark": "✦", "wing": "🪽", "flower": "🌸", "crown": "♛", "coin": "💗"}

def divider(char="─", width=28):
    return char * width

def title(text):
    return f"╭{divider()}╮\n          ♡ {text} ♡\n╰{divider()}╯"
