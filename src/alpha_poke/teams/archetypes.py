"""Team archetypes of Gen 9 OU (2026-10-30; the review app's team analysis), from what a team
shows -- its species, the moves, items and abilities known (a whole export, or what a replay
revealed): its features (hazard stack, webs, a weather, trick room, screens, volt-turn) by rules,
its style (stall, balance, bulky offense, hyper offense) by a small classifier on interpretable
counts (fit_style: scikit-learn's multinomial logistic regression on the forum's teams whose titles name their
style -- leave-one-out 73% on 177 teams, 2026-10-30, against 52% for hand rules and 40% for the
majority class; the labels are the authors' own and fuzzy), the hand rules when no model is
given. Both are checked against those forum titles at every knowledge update (scripts/knowledge.py
validate). The descriptions say how each plays and how it is beaten in general; which Pokemon,
sets and answers the current metagame uses come from the games (coach.meta), not from here.

A team: [{"species", "moves": set of move ids, "item": item id or "", "ability": ability id or ""}]."""

from alpha_poke.analysis.roles import to_id

ROCKS = {"stealthrock", "stoneaxe"}
LAYERS = {"spikes", "ceaselessedge", "toxicspikes"}
RECOVERY = {"recover", "roost", "softboiled", "slackoff", "moonlight", "synthesis", "morningsun",
            "shoreup", "strengthsap", "wish", "rest", "milkdrink", "junglehealing", "lifedew"}  # fmt: skip
PASSIVE = {"toxic", "willowisp", "thunderwave", "haze", "whirlwind", "roar", "dragontail",
           "protect", "spikyshield", "banefulbunker", "encore", "yawn", "curse", "leechseed"}  # fmt: skip
SETUP = {"swordsdance", "dragondance", "nastyplot", "calmmind", "bulkup", "quiverdance",
         "shellsmash", "agility", "rockpolish", "bellydrum", "tidyup", "victorydance",
         "shiftgear", "coil", "geomancy", "tailglow", "filletaway", "irondefense"}  # fmt: skip
PIVOTS = {
    "uturn",
    "voltswitch",
    "flipturn",
    "partingshot",
    "teleport",
    "chillyreception",
    "shedtail",
}
OFFENSIVE_ITEMS = {"choiceband", "choicespecs", "choicescarf", "lifeorb", "boosterenergy",
                   "focussash", "expertbelt", "weaknesspolicy", "loadeddice", "throatspray"}  # fmt: skip
WALLS = {"blissey", "chansey", "toxapex", "dondozo", "clodsire", "gliscor", "corviknight",
         "skarmory", "garganacl", "tinglu", "alomomola", "hippowdon", "quagsire", "slowbro",
         "slowking", "slowkinggalar", "mandibuzz", "pecharunt", "cresselia", "umbreon", "skeledirge"}  # fmt: skip

STYLES = ("stall", "balance", "bulky offense", "hyper offense")
FEATURES = (
    "hazard stack",
    "webs",
    "rain",
    "sun",
    "sand",
    "snow",
    "trick room",
    "screens",
    "volt-turn",
)

NAMES = {
    "stall": ("Stall", "受队"), "balance": ("Balance", "平衡队"), "bulky offense": ("Bulky offense", "重攻队"),
    "hyper offense": ("Hyper offense", "高速进攻队"), "hazard stack": ("Hazard stack", "钉子队"),
    "webs": ("Sticky Web", "黏网队"), "rain": ("Rain", "雨天队"), "sun": ("Sun", "晴天队"),
    "sand": ("Sand", "沙暴队"), "snow": ("Snow", "雪天队"), "trick room": ("Trick Room", "戏法空间队"),
    "screens": ("Screens", "双墙队"), "volt-turn": ("Volt-turn", "轮转队"),
}  # fmt: skip

# how each plays and how it is beaten in general (the metagame's members and answers: the data's)
ABOUT = {
    "stall": (
        "Walls with reliable recovery wear the opponent down with hazards and status (Toxic, burns) "
        "while switching between resists; wins slowly, by attrition. Beaten by strong wallbreakers "
        "(especially special ones and setup sweepers that outheal or ignore its damage), Taunt, Knock "
        "Off on its recovery items, and denying hazards with removal or Heavy-Duty Boots.",
        "一群带稳定回复的耐久宝可梦，靠钉子和异常状态（剧毒、灼伤）慢慢磨，在抵抗的宝可梦之间来回换人，打消耗战取胜。"
        "克制它的是强力破盾手（尤其是特攻手和能强化后硬扛的宝可梦）、挑衅、用拍落打掉它的回复道具，以及清钉或厚底靴让钉子失效。",
    ),
    "balance": (
        "A defensive core with recovery plus a few strong attackers: it trades safely, keeps hazards "
        "up and its own side clear, and wins with a sweeper or wallbreaker once the checks are worn "
        "down. Beaten by pressure it cannot switch into twice (doubles, pivots), by breaking its "
        "core with the right wallbreaker, and by winning the hazard game.",
        "一组带回复的防守核心加上几只强力输出：稳扎稳打地换人，保持对面有钉、自己这边干净，"
        "等对方能接的宝可梦被磨掉后，由清场手或破盾手收尾。对付它要给它连续两次接不住的压力（预判换人、折返），"
        "用合适的破盾手打穿它的防守核心，并在钉子上占优。",
    ),
    "bulky offense": (
        "Sturdy attackers with good typing and some recovery or pivoting: each can take a hit and hit "
        "back hard, so it keeps the initiative without fragile sweepers. Beaten by solid defensive "
        "pivots that check several of its attackers, speed control, and wearing it down with hazards.",
        "既耐打又能打的进攻型宝可梦，属性互补，带一些回复或折返：每只都能挨一下再狠狠还手，靠这个持续掌握主动。"
        "对付它要有一只能接住它多只输出手的防守轮换、速度控制，以及用钉子慢慢消耗。",
    ),
    "hyper offense": (
        "Fast, frail attackers and setup sweepers, often led by a Focus Sash hazard setter or dual "
        "screens: it aims to set up early and sweep before the opponent can switch around. Beaten by "
        "priority moves, Unaware or phazing walls, faster revenge killers (Choice Scarf), breaking the "
        "lead's plan (Taunt, Magic Bounce, hazard removal), and patience: its Pokemon cannot take many hits.",
        "速度快但脆的输出手和强化清场手，常用带气势头带的撒钉首发或双墙开场：想尽早强化，在对方来不及换人前横扫。"
        "对付它要有先制招式、纯朴或能吹人的耐久宝可梦、比它快的补刀手（讲究围巾），破坏它首发的计划（挑衅、魔法反射、清钉），"
        "并保持耐心：它的宝可梦挨不了几下。",
    ),
    "hazard stack": (
        "Two or more kinds of entry hazards (Stealth Rock with Spikes or Toxic Spikes), usually with a "
        "spinblocker or Magic Bounce to keep them up and phazing or pivoting to force switches into "
        "them. Beaten by reliable hazard removal (Defog, Rapid Spin, Court Change, Tidy Up) that can "
        "be used safely, Heavy-Duty Boots on the Pokemon that switch most, Magic Bounce, and fast "
        "pressure that leaves no time to set them.",
        "同时布置两种以上的入场钉（隐形岩加撒菱或毒菱），通常配一只挡清钉的宝可梦（幽灵属性挡高速旋转）或魔法反射来保住钉子，"
        "再用吹人或折返逼对方反复换人吃钉。对付它要有能安全使用的清钉手段（清除浓雾、高速旋转、换场、大扫除），"
        "给最常换上场的宝可梦带厚底靴，魔法反射，或者用快节奏进攻不给它撒钉的时间。",
    ),
    "webs": (
        "Sticky Web lowers the Speed of every grounded switch-in, so its offense outspeeds; usually "
        "with a Focus Sash setter and fast attackers. Beaten by removal (Defog, Rapid Spin, Court "
        "Change), Flying types, Levitate and Heavy-Duty Boots users, and Defiant / Competitive mons it "
        "boosts.",
        "黏黏网让对方每只着地的宝可梦上场时速度下降，让自己的进攻手抢到速度；通常配带气势头带的撒网手和速攻手。"
        "对付它要清钉（清除浓雾、高速旋转、换场）、用飞行属性、飘浮特性或厚底靴的宝可梦，以及带不服输、好胜特性的宝可梦（黏网反而让它们提升能力）。",
    ),
    "rain": (
        "Drizzle sets rain: Water moves hit harder, Fire weaker, Swift Swim attackers double their "
        "Speed, Thunder and Hurricane never miss. Beaten by taking the weather away (your own weather, "
        "outlasting its turns), Water resists and Water Absorb / Storm Drain, and stopping the setter.",
        "降雨特性开雨：水系招式更强、火系变弱，悠游自如的宝可梦速度翻倍，打雷和暴风必中。"
        "对付它要抢天气（自己的天气、或熬过雨的回合）、用抗水的宝可梦和储水、引水特性，以及先解决开雨的宝可梦。",
    ),
    "sun": (
        "Drought sets sun: Fire moves hit harder, Water weaker, Chlorophyll attackers double their "
        "Speed, Solar Beam needs no charge. Beaten by taking the weather away, Fire resists, and "
        "priority or faster attackers against the sun sweepers.",
        "日照特性开晴：火系招式更强、水系变弱，叶绿素的宝可梦速度翻倍，日光束不用蓄力。"
        "对付它要抢天气、用抗火的宝可梦，以及用先制或更快的攻击处理晴天下的清场手。",
    ),
    "sand": (
        "Sand Stream sets sand: Rock types get more Special Defense, Sand Rush attackers double their "
        "Speed, and it chips non-Rock/Ground/Steel Pokemon each turn. Beaten by taking the weather "
        "away, Water and Fighting attacks on its Rock and Ground cores, and Safety Goggles or Overcoat.",
        "扬沙特性起沙暴：岩石属性特防提升，拨沙的宝可梦速度翻倍，每回合削减非岩石、地面、钢属性宝可梦的体力。"
        "对付它要抢天气，用水系、格斗系攻击它的岩石和地面核心，以及防尘护目镜或防尘特性。",
    ),
    "snow": (
        "Snow Warning sets snow: Ice types get more Defense and Aurora Veil can halve damage. Beaten by "
        "Steel and Fire attacks, Brick Break or Psychic Fangs on the veil, and taking the weather away.",
        "降雪特性下雪：冰属性防御提升，可以用极光幕减半伤害。对付它要用钢系和火系攻击、劈瓦或精神之牙打破极光幕，以及抢天气。",
    ),
    "trick room": (
        "Trick Room makes the slower Pokemon move first for five turns, so slow, strong attackers sweep. "
        "Beaten by Taunt on the setter, stalling the turns out (Protect, switching), and Pokemon that "
        "are slow and strong themselves.",
        "戏法空间在五个回合里让速度慢的宝可梦先动，让又慢又强的输出手横扫。"
        "对付它要挑衅开空间的宝可梦、拖过这几个回合（守住、换人），以及本身又慢又强的宝可梦。",
    ),
    "screens": (
        "Reflect and Light Screen (often with Light Clay) halve the damage taken for several turns while "
        "setup sweepers boost. Beaten by Brick Break / Psychic Fangs, Infiltrator, Taunt on the setter, "
        "phazing, and stalling the screens out.",
        "反射壁和光墙（常带光之黏土）在几个回合内让伤害减半，同时让强化手安心强化。"
        "对付它要用劈瓦、精神之牙打破墙，用穿透特性、挑衅开墙的宝可梦、吹人，或拖过墙的回合。",
    ),
    "volt-turn": (
        "Many pivot moves (U-turn, Volt Switch, Flip Turn, Parting Shot) keep the momentum: each switch "
        "brings in the right attacker safely and chips the opponent's switch-ins. Beaten by Rocky Helmet "
        "and Rough Skin, Ground types against Volt Switch, hazards that punish its switching, and "
        "Pokemon that block the pivots.",
        "大量折返招式（急速折返、伏特替换、快速折返、抛下狠话）来保持节奏：每次换人都能安全换上合适的输出手，并削弱对方换上的宝可梦。"
        "对付它要用凸凸头盔和粗糙皮肤、用地面属性挡伏特替换、用钉子惩罚它的频繁换人，以及能卡住折返的宝可梦。",
    ),
}


def mon(species: str, moves=(), item: str = "", ability: str = "") -> dict:
    return {"species": to_id(species), "moves": {to_id(m) for m in moves}, "item": to_id(item or ""),
            "ability": to_id(ability or "")}  # fmt: skip


def from_export(text: str) -> list[dict]:
    """A Showdown export's team (its species, items, abilities, moves)."""
    out = []
    for block in text.strip().split("\n\n"):
        lines = [x.strip() for x in block.strip().split("\n") if x.strip()]
        if not lines:
            continue
        head = lines[0].split(" @ ")
        name = (
            head[0].split(" (")[-1].rstrip(")")
            if "(" in head[0] and not head[0].startswith("(")
            else head[0]
        )
        name = name.replace(" (M)", "").replace(" (F)", "").strip()
        ability = next((x.split(":", 1)[1] for x in lines if x.startswith("Ability:")), "")
        moves = [x[1:].strip() for x in lines if x.startswith("-")]
        out.append(mon(name, moves, head[1] if len(head) > 1 else "", ability))
    return out


DEFENSIVE_ITEMS = {
    "heavydutyboots",
    "leftovers",
    "rockyhelmet",
    "blacksludge",
    "assaultvest",
    "eviolite",
}
FEATURE_NAMES = ("recovering", "bulk", "offense", "speed", "setup", "offensive items", "passive",
                 "pivots", "hazard setters", "defensive items", "walls")  # fmt: skip


def features(team: list[dict]) -> list[float]:
    """The style classifier's inputs (FEATURE_NAMES): counts of recovering mons, setup, offensive
    items, passive moves, pivots, hazard setters, defensive items, walls; mean base bulk, offense,
    speed."""
    from alpha_poke.dex import GEN

    base = {"hp": 80, "atk": 80, "def": 80, "spa": 80, "spd": 80, "spe": 80}
    st = [(GEN.pokedex.get(m["species"]) or {}).get("baseStats") or base for m in team] or [base]
    moves = [m["moves"] for m in team]
    mean = lambda f: sum(f(s) for s in st) / len(st)  # noqa: E731
    return [float(x) for x in (
        sum(1 for m in team if m["moves"] & RECOVERY or m["ability"] == "regenerator"),
        mean(lambda s: (s["hp"] + s["def"] + s["spd"]) / 300), mean(lambda s: max(s["atk"], s["spa"]) / 100),
        mean(lambda s: s["spe"] / 100),
        sum(1 for mv in moves if mv & SETUP), sum(1 for m in team if m["item"] in OFFENSIVE_ITEMS),
        sum(1 for mv in moves if mv & PASSIVE), sum(1 for mv in moves if mv & PIVOTS),
        sum(1 for mv in moves if mv & (ROCKS | LAYERS)), sum(1 for m in team if m["item"] in DEFENSIVE_ITEMS),
        sum(1 for m in team if m["species"] in WALLS),
    )]  # fmt: skip


# What forum titles call the archetypes ("hastack", "hazard spam" -- hazard control or removal is
# not a stack) -- the labels fit_style learns and the checks compare with.
TITLES = {
    "stall": r"\bstall\b", "balance": r"\bbal(ance)?\b|\bfat\b", "bulky offense": r"\bbo\b|bulky off",
    "hyper offense": r"\bho\b|hyper ?off",
    "hazard stack": r"(?<!control )(?<!removal )\bstack|hastack|hazard ?spam",
    "webs": r"\bwebs?\b", "rain": r"\brain\b", "sun": r"\bsun\b", "sand": r"\bsand\b",
    "snow": r"\bsnow\b|aurora ?veil", "trick room": r"\btr\b|trick ?room", "screens": r"\bscreens?\b",
    "volt-turn": r"volt|v-?turn",
}  # fmt: skip


def title_labels(title: str) -> set[str]:
    import re

    t = title.lower()
    return {k for k, p in TITLES.items() if re.search(p, t)}


def labelled(entries) -> list[tuple[list[dict], set[str]]]:
    """The catalog's complete teams whose paste titles name an archetype: (team, labels)."""
    out = []
    for e in entries:
        labs = title_labels(" / ".join({s.get("paste_title") or "" for s in e.sources}))
        if e.complete and labs:
            out.append((from_export(e.text), labs))
    return out


def agreement(rows: list[tuple[list[dict], set[str]]], model: dict | None = None) -> dict:
    """Per archetype among the labelled teams: {"n" (titles naming it), "recall" (of those, tagged
    so), "precision" (of the teams tagged so whose titles name an archetype of its kind, named
    so)}."""
    out = {}
    for k in (*STYLES, *FEATURES):
        kind = set(STYLES if k in STYLES else FEATURES)
        n = hit = tagged = 0
        for team, labs in rows:
            if k in STYLES and len(labs & kind) != 1:
                continue  # (a style: one named)
            t = tags(team, model)
            got = {t["style"], *t["features"]}
            n += k in labs
            hit += k in labs and k in got
            tagged += k in got and bool(labs & kind)
        if n:
            out[k] = {
                "n": n,
                "recall": round(hit / n, 3),
                "precision": round(hit / max(tagged, 1), 3),
            }
    return out


def fit_style(teams: list[list[dict]], labels: list[str], C: float = 0.1) -> dict:
    """The style classifier (scikit-learn, the knowledge group: build time only): standardised
    features -> multinomial logistic regression (L2, C = 1 / strength), with its leave-one-out
    accuracy. Kept as plain numbers {"mean", "scale", "coef", "intercept", "classes", "loo"} so the
    app needs no scikit-learn (style_probs is its predict_proba)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import LeaveOneOut, cross_val_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X = [features(t) for t in teams]
    pipe = lambda: make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000))  # noqa: E731
    loo = cross_val_score(pipe(), X, labels, cv=LeaveOneOut()).mean()
    fit = pipe().fit(X, labels)
    sc, lr = fit[0], fit[1]
    return {"mean": sc.mean_.tolist(), "scale": sc.scale_.tolist(), "coef": lr.coef_.tolist(),
            "intercept": lr.intercept_.tolist(), "classes": [str(c) for c in lr.classes_],
            "loo": round(float(loo), 4), "n": len(X)}  # fmt: skip


def style_probs(team: list[dict], model: dict) -> dict[str, float]:
    """fit_style's model: the probability of each style (scikit-learn's predict_proba)."""
    import numpy as np

    x = (np.array(features(team)) - np.array(model["mean"])) / np.array(model["scale"])
    z = np.array(model["coef"]) @ x + np.array(model["intercept"])
    if len(model["classes"]) == 2:  # (two classes: one logit, the second's)
        z = np.r_[0.0, z]
    p = np.exp(z - z.max())
    return {s: round(float(v), 3) for s, v in zip(model["classes"], p / p.sum(), strict=True)}


def tags(team: list[dict], model: dict | None = None) -> dict:
    """{"style": one of STYLES, "style_probs" (with a model), "features": [FEATURES]} of a team
    (partial knowledge allowed: a replay's reveals -- a feature needs what shows it, the style is
    the best guess). ``model``: fit_style's, else the hand rules."""
    moves = [m["moves"] for m in team]
    every = set().union(*moves) if moves else set()
    items = {m["item"] for m in team}
    abilities = {m["ability"] for m in team}
    feats = []
    rocks, layers = every & ROCKS, every & LAYERS
    setters = sum(1 for mv in moves if mv & (ROCKS | LAYERS))
    if (rocks and layers) or len(layers) >= 2 or setters >= 3:
        feats.append("hazard stack")
    if "stickyweb" in every:
        feats.append("webs")
    if "drizzle" in abilities or ("raindance" in every and "swiftswim" in abilities):
        feats.append("rain")
    if "drought" in abilities or ("sunnyday" in every and "chlorophyll" in abilities):
        feats.append("sun")
    if "sandstream" in abilities:
        feats.append("sand")
    if "snowwarning" in abilities or "auroraveil" in every:
        feats.append("snow")
    if "trickroom" in every:
        feats.append("trick room")
    if ("reflect" in every and "lightscreen" in every) or "lightclay" in items:
        feats.append("screens")
    if sum(1 for mv in moves if mv & PIVOTS) >= 3:
        feats.append("volt-turn")
    recovering = sum(1 for m in team if m["moves"] & RECOVERY or m["ability"] == "regenerator")
    walls = sum(1 for m in team if m["species"] in WALLS)
    passive = sum(1 for mv in moves if mv & PASSIVE)
    setup = sum(1 for mv in moves if mv & SETUP)
    offensive = sum(1 for m in team if m["item"] in OFFENSIVE_ITEMS)
    if recovering >= 4 and walls >= 3 and setup + offensive <= 1 and passive >= 2:
        style = "stall"
    elif setup + offensive >= 4 and recovering <= 1 or "focussash" in items and setup >= 2:
        style = "hyper offense"
    elif recovering >= 2 and walls >= 2:
        style = "balance"
    else:
        style = "bulky offense"
    if model:
        probs = style_probs(team, model)
        return {"style": max(probs, key=probs.get), "style_probs": probs, "features": feats}
    return {"style": style, "features": feats}


def name(tag: str, lang: str) -> str:
    en, zh = NAMES[tag]
    return zh if lang == "zh" else en


def notes(tagged: dict, lang: str) -> dict[str, str]:
    """A tagged team's archetypes in ``lang`` ("zh" / "en"): name -> how it plays and is beaten."""
    i = 1 if lang == "zh" else 0
    return {NAMES[k][i]: ABOUT[k][i] for k in (tagged["style"], *tagged["features"])}
