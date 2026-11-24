import re

from .domain import LearnerProfile, ProfileDimension, ProfileUpdate

DIMENSION_ORDER = [
    "先修知识",
    "学习目标",
    "认知风格",
    "当前薄弱点",
    "资源偏好",
    "学习节奏",
    "编程基础",
    "兴趣方向",
]

# Extraction is capture-based: the value is a span lifted from the learner's own
# sentence, not a lookup into a fixed vocabulary. A whitelist only recognises
# phrasings someone already thought of, so "对网络安全感兴趣" worked while
# "想做渗透测试" silently fell through. Capturing the span keeps unknown topics,
# fields and phrasings working without touching this table.

WEAK_MARKERS = (
    r"薄弱|较弱|弱|不懂|不会|不熟|不熟悉|没掌握|没学过|学不动|跟不上|吃力|"
    r"困难|有困难|不太行|不行|很差|差|有难度|搞不懂|弄不明白"
)
WEAK_PREFIX = (
    r"薄弱|不懂|不会|不熟|不熟悉|没掌握|吃力|有困难|不太会|不擅长"
)
# Filler that may sit between the captured noun and its marker.
_FILLER = r"(?:一直|就是|其实|还|也|都|比较|有点|很|挺|特别|尤其|真的|确实|这块|方面)?"

# 编程基础 keeps a closed vocabulary because resource difficulty keys off it.
PROGRAMMING_LEVELS: list[tuple[str, str]] = [
    (r"零基础|不会编程|没写过代码|没学过编程|没接触过编程|"
     r"编程.{0,6}?(?:基本为0|为0|是0|为零|不行|很差|不会)", "零基础"),
    (r"熟练|精通|项目经验|写过很多|做过很多项目|工程经验", "熟练"),
    (r"学过|会一点|会一些|用过|写过|入门|刚学|正在学|了解一点", "入门"),
]

# dimension -> list of patterns; named group "v" carries the captured value.
CAPTURE_RULES: dict[str, list[str]] = {
    "当前薄弱点": [
        rf"(?P<v>[\u4e00-\u9fa5A-Za-z]{{2,12}}?)(?:方面|这块|上)?{_FILLER}"
        rf"(?:{WEAK_MARKERS})",
        rf"(?:{WEAK_PREFIX})(?:的|在|是)?(?P<v>[\u4e00-\u9fa5A-Za-z]{{2,12}})",
    ],
    "兴趣方向": [
        r"(?:对|对于)(?P<v>[\u4e00-\u9fa5A-Za-z]{2,12}?)(?:方向|领域|方面)?"
        r"(?:很|比较|挺|特别|一直|真的)?(?:感兴趣|有兴趣|好奇|有热情)",
        r"(?P<v>[\u4e00-\u9fa5A-Za-z]{2,12}?)(?:方向|领域|方面)"
        r"(?:很|比较|挺|特别|一直|真的)?(?:感兴趣|有兴趣|好奇|有热情)",
        r"(?:想学|想做|想研究|想搞|想深入|向往)(?P<v>[\u4e00-\u9fa5A-Za-z]{2,12})",
        r"(?:兴趣|方向)(?:是|在)(?P<v>[\u4e00-\u9fa5A-Za-z]{2,12})",
    ],
    "学习目标": [
        r"(?:想|要|打算|准备|希望|目标(?:是)?|为了)(?:完成|通过|考过|考上|掌握|学会|拿下)"
        r"(?P<v>[\u4e00-\u9fa5A-Za-z]{2,14})",
        r"(?:准备|备战|应付|冲刺)(?P<v>[\u4e00-\u9fa5A-Za-z]{2,10})",
    ],
    "资源偏好": [
        r"(?:喜欢|偏好|习惯|爱|更想|倾向)(?:看|用|听|靠)?(?P<v>[\u4e00-\u9fa5A-Za-z]{2,10})",
    ],
    "学习节奏": [
        r"每(?:周|星期)[^，。；,.!！?？]{0,8}?(?P<v>[0-9]+|[一二三四五六七八九十两半]+)"
        r"\s*(?:个)?\s*小时",
        r"每(?:天|日)[^，。；,.!！?？]{0,8}?(?P<v>[0-9]+|[一二三四五六七八九十两半]+)"
        r"\s*(?:个)?\s*(?:分钟|小时)",
        r"(?P<v>碎片|周末|晚上|早上|业余)时间",
    ],    "先修知识": [
        r"(?P<v>大[一二三四五]|研[一二三]|博[一二三四]|高[一二三])(?:学生|在读)?",
        r"学过(?P<v>[\u4e00-\u9fa5A-Za-z+#]{2,12})",
        r"(?P<v>零基础|没接触过|完全没学过)",
    ],
}

# Closed-vocabulary dimensions: the categories drive downstream behaviour.
COGNITIVE_STYLES: list[tuple[str, str]] = [
    (r"图|视频|可视化|动画|视觉|演示|课件", "视觉型"),
    (r"例子|案例|动手|实操|练习|实践|项目", "实践型"),
    (r"推导|原理|证明|阅读|文字|教材|理论", "分析型"),
]

RESOURCE_KINDS: list[tuple[str, str]] = [
    (r"视频|动画|微课|录播", "视频动画"),
    (r"思维导图|导图|图解|图表|结构化", "视觉图解"),
    (r"题库|刷题|题目|练习|测验", "练习题库"),
    (r"代码|编程|实操|动手|实验", "代码实操"),
    (r"文档|讲义|阅读|文字|教材", "文字阅读"),
]

_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _cn_to_number(text: str) -> str:
    """Convert a short Chinese numeral to digits; leave other text as-is."""
    raw = text.strip()
    if not raw:
        return raw
    if raw == "半":
        return "0.5"
    if raw.isdigit():
        return raw
    if "十" in raw:
        head, _, tail = raw.partition("十")
        tens = _CN_DIGITS.get(head, 1) if head else 1
        ones = _CN_DIGITS.get(tail, 0) if tail else 0
        return str(tens * 10 + ones)
    if len(raw) == 1 and raw in _CN_DIGITS:
        return str(_CN_DIGITS[raw])
    return raw


_TRAIL = " 的了呢啊吧呀，。、,.!！?？；;：:"
_LEAD_NOISE = re.compile(
    r"^(?:但|但是|不过|而且|而且|然后|就是|其实|只是|还有|另外|我当时|我|自己)"
)
_TAIL_NOISE = re.compile(r"(?:超级|非常|特别|十分|比较|还算|还是|一直|真的|确实)$")
_SUFFIX_NOISE = ("能力", "水平", "基础", "方面", "部分", "内容", "方向")
_MEDIA = re.compile(r"视频|动画|图|题|代码|文档|讲义|教材|课件|实操")


def _clean(value: str) -> str:
    text = value.strip(_TRAIL)
    text = _LEAD_NOISE.sub("", text).strip(_TRAIL)
    text = _TAIL_NOISE.sub("", text).strip(_TRAIL)
    # "编程能力比较薄弱" captures "编程能力"; the suffix is noise, not meaning.
    for suffix in _SUFFIX_NOISE:
        if len(text) > len(suffix) + 1 and text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    text = re.split(r"[和与及、,，]", text)[0].strip(_TRAIL)
    return text[:24]


def _first_capture(patterns: list[str], message: str) -> tuple[str, str] | None:
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        raw = match.group("v")
        value = _clean(raw)
        # Single-character magnitudes ("两小时", "半小时") are legitimate, so
        # the length floor applies only when the span is not numeric.
        if len(value) < 2 and not (value.replace(".", "").isdigit() or value in _CN_DIGITS or value == "半"):
            continue
        return value, match.group(0).strip()
    return None


def _match_vocab(table: list[tuple[str, str]], message: str) -> tuple[str, str] | None:
    for pattern, label in table:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return label, match.group(0).strip()
    return None


def extract_dimensions(message: str) -> dict[str, tuple[str, str]]:
    """Return dimension -> (value, evidence) for every dimension with signal.

    Only dimensions actually evidenced in `message` appear in the result, so the
    caller can leave everything else untouched.
    """
    found: dict[str, tuple[str, str]] = {}

    for dimension, patterns in CAPTURE_RULES.items():
        hit = _first_capture(patterns, message)
        if hit:
            found[dimension] = hit

    # 节奏 values arrive as a bare magnitude; convert it and attach the unit
    # the sentence implied ("每周只能学两小时" -> 每周2小时).
    if "学习节奏" in found:
        value, evidence = found["学习节奏"]
        magnitude = _cn_to_number(value)
        if magnitude.replace(".", "").isdigit():
            if "分钟" in evidence:
                found["学习节奏"] = (f"每天{magnitude}分钟", evidence)
            elif "天" in evidence or "日" in evidence:
                found["学习节奏"] = (f"每天{magnitude}小时", evidence)
            else:
                found["学习节奏"] = (f"每周{magnitude}小时", evidence)

    # A captured "兴趣" that is really a media preference is reclassified
    # rather than dropped: "我对刷题特别感兴趣" is a resource preference.
    interest = found.pop("兴趣方向", None)
    if interest and _MEDIA.search(interest[0]):
        kind = _match_vocab(RESOURCE_KINDS, interest[0])
        if kind and "资源偏好" not in found:
            found["资源偏好"] = (kind[0], interest[1])
    elif interest:
        found["兴趣方向"] = interest

    preference = found.get("资源偏好")
    if preference:
        kind = _match_vocab(RESOURCE_KINDS, preference[0])
        if kind:
            found["资源偏好"] = (kind[0], preference[1])

    level = _match_vocab(PROGRAMMING_LEVELS, message)
    if level:
        found["编程基础"] = level

    style = _match_vocab(COGNITIVE_STYLES, message)
    if style:
        found["认知风格"] = style

    # 学习目标 and 兴趣方向 both fire on "想学/想做"; the goal wins and the
    # interest entry is dropped when they captured the same span.
    if "学习目标" in found and "兴趣方向" in found:
        if found["学习目标"][0] == found["兴趣方向"][0]:
            found.pop("兴趣方向")

    return found


def extract_profile(existing: LearnerProfile, message: str) -> ProfileUpdate:
    """Rule-based extraction. Acts as the offline and failure fallback path."""
    dimensions = dict(existing.dimensions)
    changed: list[str] = []

    for dimension, (value, evidence) in extract_dimensions(message).items():
        dimensions[dimension] = ProfileDimension(
            value=value,
            evidence=evidence[:160],
            confidence=0.8,
        )
        changed.append(dimension)

    profile = LearnerProfile(dimensions=dimensions, mastery=existing.mastery)
    missing = [name for name in DIMENSION_ORDER if name not in dimensions]
    assistant = (
        f"已更新 {len(changed)} 个画像维度。"
        if changed
        else "我已记录你的补充，画像会继续随学习行为更新。"
    )
    if missing:
        assistant += f" 还想了解一下：你的{missing[0]}是什么情况？"

    return ProfileUpdate(
        profile=profile,
        assistant_message=assistant,
        changed_dimensions=sorted(set(changed)),
    )


def _normalise_value(name: str, value: str) -> str:
    """Map free-form model wording onto the vocabulary downstream code expects.

    Only 编程基础 is bucketed: resource difficulty compares it against a closed
    set, so "较弱" must become 零基础/入门/熟练 or the comparison silently
    fails. Every other dimension is shown to the learner as written.
    """
    text = value.strip()
    if name == "编程基础":
        if re.search(
            r"零基础|无基础|没学过|不会|没接触|从未|不太行|很弱|较弱|偏弱|"
            r"较差|薄弱|零|从零|有限",
            text,
        ):
            return "零基础"
        if re.search(r"熟练|精通|很强|扎实|丰富|较强", text):
            return "熟练"
        return "入门"
    return text


def _grounded(evidence: str, message: str) -> bool:
    """True when the evidence actually appears in what the learner said.

    The model tends to invent a plausible dimension (a study goal inferred from
    a preference). Requiring the evidence to be a substring of the message
    drops those instead of trusting the prompt alone.
    """
    probe = evidence.strip().strip("。，、；：！？ \t")
    if not probe:
        return False
    if probe in message:
        return True
    # Allow a lightly reformatted span: compare the longest common run.
    compact = "".join(probe.split())
    if compact and compact in "".join(message.split()):
        return True
    return False


def merge_model_dimensions(
    existing: LearnerProfile,
    payload: dict,
    message: str,
) -> ProfileUpdate | None:
    """Turn a model's dimension list into a profile. None if unusable."""
    raw = payload.get("dimensions") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return None

    dimensions = dict(existing.dimensions)
    changed: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        value = str(item.get("value", "")).strip()
        if name not in DIMENSION_ORDER or not value:
            continue
        evidence = str(item.get("evidence", "")).strip() or message[:80] or value
        if not _grounded(evidence, message):
            # Unsupported dimension: the model inferred it rather than read it.
            continue
        try:
            confidence = float(item.get("confidence", 0.85))
        except (TypeError, ValueError):
            confidence = 0.85
        confidence = min(max(confidence, 0.0), 1.0)
        dimensions[name] = ProfileDimension(
            value=_normalise_value(name, value)[:80],
            evidence=evidence[:160],
            confidence=confidence,
        )
        changed.append(name)

    if not changed:
        return None

    profile = LearnerProfile(dimensions=dimensions, mastery=existing.mastery)
    missing = [name for name in DIMENSION_ORDER if name not in dimensions]
    assistant = f"已更新 {len(changed)} 个画像维度。"
    if missing:
        assistant += f" 还想了解一下：你的{missing[0]}是什么情况？"

    return ProfileUpdate(
        profile=profile,
        assistant_message=assistant,
        changed_dimensions=sorted(set(changed)),
    )


async def extract_profile_with_model(
    existing: LearnerProfile,
    message: str,
    provider,
) -> tuple[ProfileUpdate, str]:
    """Extract via the model, falling back to rules. Returns (update, source)."""
    payload = {
        "message": message,
        "existing_dimensions": {
            name: dimension.value for name, dimension in existing.dimensions.items()
        },
        "dimension_order": DIMENSION_ORDER,
        "rules": [
            "只抽取这段话里明确出现的维度；没有明确依据的维度不要输出，"
            "也不要根据其他维度推断。",
            "evidence 必须是原话中的片段，不能改写或总结。",
            "value 用学习者自己的说法，保持简短。",
        ],
        "output_schema": {
            "required": ["dimensions"],
            "shape": {
                "dimensions": [
                    {
                        "name": "必须是 dimension_order 之一",
                        "value": "该维度的简短取值，可用学习者自己的说法",
                        "evidence": "对话中的原话片段",
                        "confidence": "0 到 1 之间的小数",
                    }
                ]
            },
        },
    }
    try:
        output = await provider.complete_json("profile", payload)
    except Exception:  # noqa: BLE001 - fall back rather than fail the turn
        return extract_profile(existing, message), "rules"

    merged = merge_model_dimensions(existing, output, message)
    if merged is None:
        return extract_profile(existing, message), "rules"
    return merged, "model"


def next_profile_question(profile: LearnerProfile) -> str:
    missing = [name for name in DIMENSION_ORDER if name not in profile.dimensions]
    if not missing:
        return "画像信息已足够，可以开始生成个性化学习资源。"
    return f"你的{missing[0]}是什么情况？"
