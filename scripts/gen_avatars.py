# -*- coding: utf-8 -*-
"""gen_avatars.py - Use Zhipu CogView to generate 11 cartoon bull avatars"""
import json
import os
import time
import requests

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT, "docs", "mockups", "avatars")
os.makedirs(OUT_DIR, exist_ok=True)

with open(os.path.join(PROJECT, "config", "model.json"), encoding="utf-8") as f:
    cfg = json.load(f)

API_KEY = cfg["api_key"]
BASE = "https://open.bigmodel.cn/api/paas/v4/images/generations"

PREFIX = "可爱卡通小牛头像，Q版扁平插画风格，{skin}皮肤，圆脸，两只小牛角，大眼睛，微笑，{accessory}，纯白色背景，头像图标风格，简洁干净，高清质量"

ROLES = {
    "tech":    ("奶黄色",   "蓝色圆框眼镜"),
    "fund":    ("淡粉色",   "绿色领带和计算器徽章"),
    "news":    ("浅棕色",   "橙色记者帽"),
    "bull":    ("红棕色",   "披着红色披风，表情斗志昂扬，旁边有向上的红色箭头"),
    "bear":    ("灰色",     "围着绿色围巾，表情皱眉担忧，旁边有向下的绿色箭头"),
    "rm":      ("紫灰色",   "戴着金色小皇冠，表情沉思"),
    "aggr":    ("橙色",     "戴着有火焰图案的帽子，表情兴奋"),
    "neu":     ("米色",     "没有配饰，表情平静温和"),
    "cons":    ("深棕色",   "手持蓝色小盾牌，表情严肃"),
    "riskmgr": ("黑白花纹", "戴着深蓝色领带，手里拿着文件夹"),
    "trader":  ("金色",     "戴着金色棒球帽，旁边有靶心图案，表情自信"),
}

headers = {
    "Authorization": "Bearer " + API_KEY,
    "Content-Type": "application/json",
}

for role in ROLES:
    skin, accessory = ROLES[role]
    out_path = os.path.join(OUT_DIR, role + ".png")
    if os.path.exists(out_path):
        print("[skip] " + role + ".png already exists")
        continue

    prompt = PREFIX.format(skin=skin, accessory=accessory)
    print("[gen] " + role + ": " + skin + " + " + accessory)

    try:
        resp = requests.post(
            BASE,
            headers=headers,
            json={"model": "cogview-3-plus", "prompt": prompt, "size": "1024x1024"},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        urls = data.get("data", [])
        if not urls:
            print("  ERROR: no image url in response: " + json.dumps(data, ensure_ascii=False)[:200])
            continue

        img_url = urls[0].get("url", "")
        if not img_url:
            print("  ERROR: empty url")
            continue

        img_resp = requests.get(img_url, timeout=60)
        img_resp.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(img_resp.content)
        print("  saved -> " + out_path + " (" + str(len(img_resp.content)) + " bytes)")

    except Exception as e:
        print("  ERROR: " + str(e))

    time.sleep(2)

print("\nDone!")
for f in sorted(os.listdir(OUT_DIR)):
    if f.endswith(".png"):
        size = os.path.getsize(os.path.join(OUT_DIR, f))
        print("  " + f + ": " + str(size) + " bytes")
