# -*- coding: utf-8 -*-
"""gen_avatar_svgs.py - Use GLM chat API to generate 11 cute cartoon bull SVG avatars."""
import json
import os
import sys
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

OUT_DIR = os.path.join(PROJECT, "docs", "mockups", "avatars")
os.makedirs(OUT_DIR, exist_ok=True)

# Use anthropic SDK (same as multi-agent-stock)
import anthropic

with open(os.path.join(PROJECT, "config", "model.json"), encoding="utf-8") as f:
    cfg = json.load(f)

client = anthropic.Anthropic(
    api_key=cfg["api_key"],
    base_url=cfg["base_url"],
)

MODEL = cfg.get("model", "glm-5.1")

ROLES = {
    "tech": {
        "skin": "cream yellow (light warm yellow)",
        "accessory": "round blue-rimmed glasses and a small chart icon floating nearby",
        "expression": "focused and studious",
    },
    "fund": {
        "skin": "light pink (soft pastel pink)",
        "accessory": "green necktie and a small calculator badge",
        "expression": "serious and professional",
    },
    "news": {
        "skin": "light brown (warm tan)",
        "accessory": "orange reporter/newsboy cap",
        "expression": "curious and alert",
    },
    "bull": {
        "skin": "reddish brown (warm terracotta)",
        "accessory": "red superhero cape flowing behind, determined look, upward pointing arrow next to him",
        "expression": "determined and aggressive (battle-ready)",
    },
    "bear": {
        "skin": "gray (cool neutral gray)",
        "accessory": "green scarf around neck, downward pointing arrow next to him",
        "expression": "worried frown, concerned",
    },
    "rm": {
        "skin": "purple-gray (muted mauve)",
        "accessory": "small golden crown on head",
        "expression": "thoughtful and contemplative",
    },
    "aggr": {
        "skin": "bright orange (vivid warm orange)",
        "accessory": "hat with flame pattern, energetic pose",
        "expression": "excited and enthusiastic",
    },
    "neu": {
        "skin": "beige (light cream)",
        "accessory": "no accessories, clean simple look",
        "expression": "calm and neutral, peaceful smile",
    },
    "cons": {
        "skin": "dark brown (rich chocolate)",
        "accessory": "holding a small blue shield in front",
        "expression": "serious and cautious",
    },
    "riskmgr": {
        "skin": "black and white patches (holstein cow pattern)",
        "accessory": "navy blue necktie and a clipboard under arm",
        "expression": "strict and meticulous",
    },
    "trader": {
        "skin": "golden (warm golden yellow)",
        "accessory": "gold baseball cap worn backwards, target/dartboard icon next to him",
        "expression": "confident smirk",
    },
}

SVG_PROMPT = """You are a professional flat-design illustrator. Create a cute cartoon bull/calf avatar as SVG code.

Requirements:
- ViewBox: 0 0 200 200 (square avatar)
- Style: Q-version (chibi) flat illustration, similar to LINE sticker or WeChat emoji quality
- Base: round face, two small curved horns on top, floppy ears on sides, big expressive eyes with white highlights, small oval nostril-nose, subtle smile
- Skin color: {skin}
- Accessory: {accessory}
- Expression: {expression}
- Background: solid light circle or clean transparent
- Colors: vibrant but harmonious, use flat fills (no gradients needed)
- Keep it simple enough to render at 48x48px but detailed enough at 200x200px

Output ONLY the SVG code (starting with <svg and ending with </svg>). No explanation, no markdown code blocks."""


def generate_one(role):
    info = ROLES[role]
    prompt = SVG_PROMPT.format(
        skin=info["skin"],
        accessory=info["accessory"],
        expression=info["expression"],
    )

    out_path = os.path.join(OUT_DIR, role + ".svg")
    if os.path.exists(out_path):
        print("[skip] " + role + ".svg exists")
        return True

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text.strip()

        # Extract SVG from response (in case model adds backticks or explanation)
        svg_start = content.find("<svg")
        svg_end = content.rfind("</svg>")
        if svg_start >= 0 and svg_end > svg_start:
            svg = content[svg_start:svg_end + 6]
        else:
            print("  ERROR: no SVG found in response")
            print("  Response preview: " + content[:200])
            return False

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(svg)
        print("  saved -> " + out_path + " (" + str(len(svg)) + " chars)")
        return True

    except Exception as e:
        print("  ERROR: " + str(e))
        return False


if __name__ == "__main__":
    # If --test flag, only generate 1 (tech)
    if "--test" in sys.argv:
        print("[test] generating tech only...")
        generate_one("tech")
    else:
        for role in ROLES:
            print("[gen] " + role)
            generate_one(role)
            time.sleep(1)  # rate limit

    print("\nGenerated files:")
    for f in sorted(os.listdir(OUT_DIR)):
        if f.endswith(".svg"):
            size = os.path.getsize(os.path.join(OUT_DIR, f))
            print("  " + f + ": " + str(size) + " bytes")
