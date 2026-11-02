#!/usr/bin/env python3
"""
obsidian_colors.py
Colour the Graphify knowledge map in Obsidian by PROJECT PART (data, events, models, airports, decision,
server, ESP32, thesis, management) instead of 60+ automatic groups, and hide third-party library noise.
Run after `graphify export obsidian` (re-running is safe).

Usage:
    python thesis/obsidian_colors.py            # vault: graphify-out/obsidian
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

VAULT = Path(__file__).resolve().parent.parent / "graphify-out" / "obsidian"
TAG = "قسم"  # Arabic tag prefix, so the colour groups read in Arabic inside Obsidian

# topic, colour, Arabic name (for the legend note), Arabic tag
TOPICS = [
    ("Data", "#2a78d6", "البيانات وتنزيلها", "البيانات"),
    ("Events", "#1baf7a", "تعريف المطر والعواصف", "المطر_والعواصف"),
    ("Models", "#9085e9", "النماذج والتعلّم الآلي", "النماذج"),
    ("Airports", "#eb6834", "عيون المطارات METAR", "المطارات"),
    ("Decision", "#0ca30c", "عقل القرار والمحاكاة", "القرار"),
    ("Server", "#e34948", "السيرفر والتشغيل الحي", "السيرفر"),
    ("ESP32", "#eda100", "جهاز ESP32", "ESP32"),
    ("Thesis", "#e87ba4", "تقرير الأطروحة", "الأطروحة"),
    ("Project", "#8a8984", "إدارة المشروع", "إدارة_المشروع"),
    ("Library", "#c3c2b7", "مكتبات خارجية", "مكتبات_خارجية"),
]
AR = {t: f"{TAG}/{a}" for t, _, _, a in TOPICS}

RULES = [  # first match wins; tested against the note's source_file (lower case)
    ("Thesis", r"^thesis/"),
    ("ESP32", r"^esp32/"),
    ("Airports", r"metar|part5"),
    ("Decision", r"decision\.py|simulat|part4|strategy|decision_timeline"),
    ("Events", r"define_events|events|part2|storm_example|delay_tradeoff"),
    ("Models", r"train_models|model|part3|pr_curves|feature_importance|train_report"),
    ("Server", r"live_decision|retrain|^server/|^deploy|^\.github/|render\.yaml"),
    ("Data", r"download_|prepare_|check_data|^data/|part1"),
    ("Project", r"handoff|^\.claude/|requirements|readme"),
]


def topic_of(src: str) -> str:
    s = src.lower()
    for t, rx in RULES:
        if re.search(rx, s):
            return t
    return "Library" if not s else "Project"


def main() -> int:
    if not VAULT.exists():
        sys.exit(f"vault not found: {VAULT} (run: graphify export obsidian)")
    counts = {t: 0 for t, *_ in TOPICS}
    for md in VAULT.glob("*.md"):
        if md.name.startswith("00 "):
            continue  # the colour legend note itself
        txt = md.read_text(encoding="utf-8")
        m = re.search(r'^source_file: "(.*)"$', txt, re.M)
        t = topic_of(m.group(1) if m else "")
        counts[t] += 1
        if re.search(rf"(?:topic|{TAG})/", txt):
            txt = re.sub(rf"(?:topic|{TAG})/\w+", AR[t], txt)  # also migrates the old English topic/ tags
        else:
            txt = txt.replace("\ntags:\n", f"\ntags:\n  - {AR[t]}\n", 1).rstrip() + f" #{AR[t]}\n"
        md.write_text(txt, encoding="utf-8")

    obs = VAULT / ".obsidian"
    gpath = obs / "graph.json"
    g = json.loads(gpath.read_text(encoding="utf-8")) if gpath.exists() else {}
    g["colorGroups"] = [{"query": f"tag:#{AR[t]}", "color": {"a": 1, "rgb": int(c[1:], 16)}} for t, c, *_ in TOPICS]
    g["search"] = f"-tag:#{AR['Library']}"     # hide third-party library internals (ArduinoJson, pandas types…)
    g.update({"showTags": False, "showAttachments": False, "showOrphans": True, "showArrow": False,
              "textFadeMultiplier": -0.6, "nodeSizeMultiplier": 1.2, "lineSizeMultiplier": 0.6})
    obs.mkdir(exist_ok=True)
    gpath.write_text(json.dumps(g, indent=2, ensure_ascii=False), encoding="utf-8")

    # hide the graph's "restore default settings" button: one click wipes all colour groups
    (obs / "snippets").mkdir(exist_ok=True)
    (obs / "snippets" / "hilla-graph.css").write_text(".graph-controls-button.mod-reset { display: none; }\n",
                                                      encoding="utf-8")
    apath = obs / "appearance.json"
    ap = json.loads(apath.read_text(encoding="utf-8")) if apath.exists() else {}
    ap["enabledCssSnippets"] = sorted(set(ap.get("enabledCssSnippets", [])) | {"hilla-graph"})
    apath.write_text(json.dumps(ap, indent=2), encoding="utf-8")

    # open the graph view first when the vault is opened
    ws = obs / "workspace.json"
    if not ws.exists():
        ws.write_text(json.dumps({"main": {"id": "m", "type": "split", "direction": "vertical", "children": [
            {"id": "t", "type": "tabs", "children": [{"id": "g", "type": "leaf", "state": {"type": "graph", "state": {}}}]}]},
            "active": "g"}, indent=2), encoding="utf-8")

    legend = ["# دليل الألوان — خريطة مشروع منظّف الألواح الذكي", "",
              "كل نقطة في المخطط = ملف أو فكرة أو دالة، وكل خط = علاقة بينهما. اللون = جزء المشروع:", ""]
    legend += [f"- <span style=\"color:{c}\">●</span> **{ar}** (`#{AR[t]}`) — {counts[t]} عقدة" for t, c, ar, _ in TOPICS]
    legend += ["", "افتح المخطط: **Ctrl + G**. اضغط على أي نقطة لفتح ملاحظتها."]
    (VAULT / "00 دليل الألوان.md").write_text("\n".join(legend) + "\n", encoding="utf-8")

    for t, c, ar, _ in TOPICS:
        print(f"{t:<9}{c}  {counts[t]:>4}  {ar}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
