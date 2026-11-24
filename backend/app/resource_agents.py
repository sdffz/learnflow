import asyncio
import json
import re
from html import escape

from pydantic import BaseModel, Field

from .domain import LearnerProfile, utc_now
from .knowledge_domain import KnowledgeChunk
from .model_gateway import ModelProvider


class LearningResource(BaseModel):
    id: str | None = None
    type: str
    title: str
    knowledge_point: str
    content: dict
    metadata: dict = Field(default_factory=dict)
    status: str = "verified"
    created_at: str = Field(default_factory=utc_now)


RESOURCE_ROLES = ("document", "mindmap", "quiz", "codelab", "slides", "animation")

# Offline fallback, used only when a role's model call fails or returns an
# unusable payload. It is deliberately plain: it exists to keep the six-resource
# contract alive, not to be the product's voice.
FALLBACK_CONTENT = {
    "神经网络": {
        "big_idea": "神经网络通过多层可学习单元逐步提取特征，并用损失函数和反向传播调整参数。",
        "chain": ["输入与特征", "加权求和", "激活函数", "前向传播", "损失计算", "反向传播"],
        "example": "判断一张图片是否包含猫时，网络会从边缘、纹理逐步组合出更高层特征。",
        "code": "def relu(x):\n    return max(0, x)\n\nprint(relu(-2), relu(3))",
        "output": "0 3",
        "misconception": "参数多不等于模型一定更懂语义，数据偏差和过拟合仍会导致错误。",
    },
}

DEFAULT_CONTENT = FALLBACK_CONTENT["神经网络"]


def _fallback_for(topic: str) -> dict:
    return dict(FALLBACK_CONTENT.get(topic, DEFAULT_CONTENT))


def _dimension_value(profile: LearnerProfile, name: str, fallback: str) -> str:
    dimension = profile.dimensions.get(name)
    return dimension.value if dimension else fallback


def _difficulty(profile: LearnerProfile) -> str:
    foundation = _dimension_value(profile, "编程基础", "入门")
    return "入门" if foundation in {"零基础", "入门"} else "进阶"


def _as_text(value: object, limit: int = 4000) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _as_str_list(value: object, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    items = [str(item).strip() for item in value if str(item).strip()]
    return items[:limit]


def _normalise_markdown(text: str) -> str:
    """Make model-authored markdown render predictably.

    Models write emphasis like `**队列（Queue）**`. CommonMark does not treat a
    closing `**` as right-flanking when the preceding character is punctuation,
    and full-width brackets count as punctuation, so the asterisks leaked into
    the UI as literal characters. Dropping the markers is better than shipping
    visible `**` to a learner.
    """
    text = re.sub(r"\*\*([^*\n]+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]{1,60}?)\*(?!\*)", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    return text.strip()


class ResourceBundle:
    """Six role-specific agents, each producing its own full content."""

    async def generate(
        self,
        profile: LearnerProfile,
        topic: str,
        provider: ModelProvider,
        personal_sources: list[KnowledgeChunk] | None = None,
    ) -> list[LearningResource]:
        sources = personal_sources or []
        source_payload = [
            {
                "assetId": source.asset_id,
                "assetTitle": source.asset_title,
                "courseTitle": source.course_title,
                "title": source.title,
                "excerpt": source.excerpt[:220],
            }
            for source in sources[:6]
        ]
        difficulty = _difficulty(profile)
        minutes = 25 if difficulty == "入门" else 40
        context = {
            "topic": topic,
            "safe_topic": escape(topic),
            "difficulty": difficulty,
            "minutes": minutes,
            "sources": source_payload,
            "profile": {
                name: dimension.value for name, dimension in profile.dimensions.items()
            },
            "reason": (
                f"围绕“{_dimension_value(profile, '学习目标', '理解课程')}”，"
                f"采用{_dimension_value(profile, '资源偏好', '图解')}，"
                f"补强{_dimension_value(profile, '当前薄弱点', '核心概念')}"
            ),
        }

        # Roles are independent; running them concurrently keeps a six-role run
        # within a demo-friendly time budget.
        results = await asyncio.gather(
            *(
                self._build(role, context, provider)
                for role in RESOURCE_ROLES
            )
        )
        return list(results)

    async def _build(
        self,
        role: str,
        context: dict,
        provider: ModelProvider,
    ) -> LearningResource:
        payload = {
            **context,
            "role": role,
            "baseline": _fallback_for(context["topic"]),
            "output_schema": {"required": ROLE_FIELDS[role]},
        }
        try:
            output = await provider.complete_json(role, payload)
        except Exception:  # noqa: BLE001 - one role must not abort the bundle
            return getattr(self, f"_fallback_{role}")(context, "template")
        if not isinstance(output, dict):
            return getattr(self, f"_fallback_{role}")(context, "template")
        resource = getattr(self, f"_{role}")(context, output)
        if resource is None:
            return getattr(self, f"_fallback_{role}")(context, "template")
        return resource

    # ------------------------------------------------------------------ meta

    @staticmethod
    def _meta(context: dict, generated_by: str) -> dict:
        return {
            "difficulty": context["difficulty"],
            "estimated_minutes": context["minutes"],
            "personalization_reason": context["reason"],
            "sources": context["sources"],
            "generated_by": generated_by,
        }

    # -------------------------------------------------------------- document

    def _document(self, context: dict, output: dict) -> LearningResource | None:
        sections = output.get("sections")
        if not isinstance(sections, list) or not sections:
            return None
        rendered: list[str] = []
        for item in sections[:8]:
            if not isinstance(item, dict):
                continue
            heading = _as_text(item.get("heading"), 80)
            body = _as_text(item.get("body"), 3000)
            if heading and body:
                rendered.append(f"## {heading}\n\n{body}")
        if not rendered:
            return None

        parts = [f"# {_as_text(output.get('title'), 80) or context['topic']}", ""]
        parts.extend(rendered)
        self_check = _as_text(output.get("self_check"), 400)
        if self_check:
            parts.append(f"## 自检\n\n{self_check}")
        if context["sources"]:
            citations = "\n".join(
                f"- 《{source['assetTitle']}》 · {source['title']}"
                for source in context["sources"]
            )
            parts.append(
                "## 来自你的资料\n\n"
                f"{citations}\n\n"
                "以上内容来自当前课程的个人知识库，可在资料详情中继续追溯原文。"
            )
        markdown = "\n\n".join(parts)
        return LearningResource(
            type="document",
            title=_as_text(output.get("title"), 80) or f"{context['topic']}·个性化讲解",
            knowledge_point=context["topic"],
            content={"markdown": markdown},
            metadata=self._meta(context, "model"),
        )

    def _fallback_document(self, context: dict, source: str) -> LearningResource:
        data = _fallback_for(context["topic"])
        markdown = (
            f"# {context['topic']}：从直觉到原理\n\n"
            f"## 你的学习入口\n\n{data['big_idea']}\n\n"
            f"## 一张图看懂过程\n\n`{' → '.join(data['chain'])}`\n\n"
            f"## 场景例子\n\n{data['example']}\n\n"
            f"## 常见误区\n\n{data['misconception']}\n\n"
            "## 自检\n\n请尝试不用术语复述：输入是什么、系统做了什么、结果为什么可能出错？"
        )
        return LearningResource(
            type="document",
            title=f"{context['topic']}·个性化讲解",
            knowledge_point=context["topic"],
            content={"markdown": markdown},
            metadata=self._meta(context, source),
        )

    # --------------------------------------------------------------- mindmap

    def _mindmap(self, context: dict, output: dict) -> LearningResource | None:
        branches = output.get("branches")
        if not isinstance(branches, list) or not branches:
            return None
        children: list[dict] = []
        for index, item in enumerate(branches[:8], start=1):
            if not isinstance(item, dict):
                continue
            label = _as_text(item.get("label"), 60)
            if not label:
                continue
            node: dict = {"id": f"b{index}", "label": label}
            sub = _as_str_list(item.get("children"), 6)
            if sub:
                node["children"] = [
                    {"id": f"b{index}-{j}", "label": text}
                    for j, text in enumerate(sub, start=1)
                ]
            children.append(node)
        if not children:
            return None
        root = _as_text(output.get("root"), 60) or context["topic"]
        return LearningResource(
            type="mindmap",
            title=f"{context['topic']}知识地图",
            knowledge_point=context["topic"],
            content={"root": {"id": "root", "label": root, "children": children}},
            metadata=self._meta(context, "model"),
        )

    def _fallback_mindmap(self, context: dict, source: str) -> LearningResource:
        data = _fallback_for(context["topic"])
        children = [
            {"id": f"{index}-concept", "label": item}
            for index, item in enumerate(data["chain"], start=1)
        ]
        children.append({"id": "pitfall", "label": "常见误区"})
        return LearningResource(
            type="mindmap",
            title=f"{context['topic']}知识地图",
            knowledge_point=context["topic"],
            content={
                "root": {"id": "root", "label": context["topic"], "children": children}
            },
            metadata=self._meta(context, source),
        )

    # ------------------------------------------------------------------ quiz

    def _quiz(self, context: dict, output: dict) -> LearningResource | None:
        raw = output.get("questions")
        if not isinstance(raw, list) or not raw:
            return None
        questions: list[dict] = []
        for index, item in enumerate(raw[:6], start=1):
            if not isinstance(item, dict):
                continue
            stem = _as_text(item.get("stem"), 400)
            options = _as_str_list(item.get("options"), 6)
            if not stem or len(options) < 2:
                continue
            try:
                answer = int(item.get("answer"))
            except (TypeError, ValueError):
                continue
            if not 0 <= answer < len(options):
                # A model that miscounts its own options is not trustworthy.
                continue
            questions.append(
                {
                    "id": f"q{index}",
                    "stem": stem,
                    "options": options,
                    "answer": answer,
                    "explanation": _as_text(item.get("explanation"), 600),
                }
            )
        if not questions:
            return None
        title = _as_text(output.get("title"), 80) or f"{context['topic']}·分层练习"
        return LearningResource(
            type="quiz",
            title=title,
            knowledge_point=context["topic"],
            content={"questions": questions},
            metadata=self._meta(context, "model"),
        )

    def _fallback_quiz(self, context: dict, source: str) -> LearningResource:
        data = _fallback_for(context["topic"])
        level = "基础理解" if context["difficulty"] == "入门" else "迁移应用"
        return LearningResource(
            type="quiz",
            title=f"{context['topic']}·{level}练习",
            knowledge_point=context["topic"],
            content={
                "questions": [
                    {
                        "id": "q1",
                        "stem": f"关于“{context['topic']}”，下面哪项最符合核心思想？",
                        "options": [
                            data["big_idea"],
                            "参数量越多，结论一定越正确",
                            "只要演示成功，就不需要测试",
                        ],
                        "answer": 0,
                        "explanation": data["big_idea"],
                    }
                ]
            },
            metadata=self._meta(context, source),
        )

    # --------------------------------------------------------------- codelab

    def _codelab(self, context: dict, output: dict) -> LearningResource | None:
        task = _normalise_markdown(_as_text(output.get("task"), 4000))
        solution = _as_text(output.get("solution"), 4000)
        if not task or not solution:
            return None
        return LearningResource(
            type="codelab",
            title=_as_text(output.get("title"), 80) or f"{context['topic']}代码实验",
            knowledge_point=context["topic"],
            content={
                "language": _as_text(output.get("language"), 20) or "python",
                "task": task,
                "starter": _as_text(output.get("starter"), 2000) or "# 在此补全代码\n",
                "solution": solution,
                "expected_output": _as_text(output.get("expected_output"), 400),
                "explanation": _as_text(output.get("explanation"), 1200),
            },
            metadata=self._meta(context, "model"),
        )

    def _fallback_codelab(self, context: dict, source: str) -> LearningResource:
        data = _fallback_for(context["topic"])
        if context["difficulty"] == "入门":
            starter = "# 将代码补全后运行\n# 观察输入如何变成输出\ndef experiment(value):\n    pass\n"
            task = "补全函数并解释每行代码的作用。"
        else:
            starter = "# 编写实验：改变输入并记录三种边界情况\ndef experiment(values):\n    pass\n"
            task = "实现更通用的版本，并比较正常、边界和异常输入。"
        return LearningResource(
            type="codelab",
            title=f"{context['topic']}代码实验",
            knowledge_point=context["topic"],
            content={
                "language": "python",
                "task": task,
                "starter": starter,
                "solution": data["code"],
                "expected_output": data["output"],
                "explanation": data["big_idea"],
            },
            metadata=self._meta(context, source),
        )

    # ---------------------------------------------------------------- slides

    def _slides(self, context: dict, output: dict) -> LearningResource | None:
        raw = output.get("slides")
        if not isinstance(raw, list) or not raw:
            return None
        slides: list[dict] = []
        for item in raw[:10]:
            if not isinstance(item, dict):
                continue
            title = _as_text(item.get("title"), 80)
            body = _as_text(item.get("body"), 800)
            if title and body:
                slides.append(
                    {
                        "title": title,
                        "kicker": _as_text(item.get("kicker"), 40) or "个性化微课",
                        "body": body,
                    }
                )
        if not slides:
            return None
        return LearningResource(
            type="slides",
            title=_as_text(output.get("title"), 80) or f"{context['topic']}微课件",
            knowledge_point=context["topic"],
            content={"slides": slides},
            metadata=self._meta(context, "model"),
        )

    def _fallback_slides(self, context: dict, source: str) -> LearningResource:
        data = _fallback_for(context["topic"])
        return LearningResource(
            type="slides",
            title=f"{context['topic']}微课件",
            knowledge_point=context["topic"],
            content={
                "slides": [
                    {"title": context["topic"], "kicker": "个性化微课", "body": data["big_idea"]},
                    {"title": "过程链", "kicker": "Know the flow", "body": " → ".join(data["chain"])},
                    {"title": "生活化例子", "kicker": "Make it concrete", "body": data["example"]},
                    {"title": "需要警惕", "kicker": "Check assumptions", "body": data["misconception"]},
                ]
            },
            metadata=self._meta(context, source),
        )

    # ------------------------------------------------------------- animation

    def _animation(self, context: dict, output: dict) -> LearningResource | None:
        raw = output.get("steps")
        if not isinstance(raw, list) or not raw:
            return None
        steps: list[tuple[str, str]] = []
        for item in raw[:8]:
            if isinstance(item, dict):
                title = _as_text(item.get("title"), 60)
                caption = _as_text(item.get("caption"), 200)
                if title:
                    steps.append((title, caption))
            elif isinstance(item, str) and item.strip():
                steps.append((item.strip()[:60], ""))
        if not steps:
            return None
        headline = _as_text(output.get("headline"), 120) or context["topic"]
        intro = _as_text(output.get("intro"), 600)
        return LearningResource(
            type="animation",
            title=f"{context['topic']}动画微课",
            knowledge_point=context["topic"],
            content={
                "html": self._animation_html(context["safe_topic"], headline, intro, steps),
                "duration_seconds": 6 + len(steps) * 3,
            },
            metadata=self._meta(context, "model"),
        )

    def _fallback_animation(self, context: dict, source: str) -> LearningResource:
        data = _fallback_for(context["topic"])
        steps = [(step, "") for step in data["chain"]]
        return LearningResource(
            type="animation",
            title=f"{context['topic']}动画微课",
            knowledge_point=context["topic"],
            content={
                "html": self._animation_html(
                    context["safe_topic"], context["topic"], data["big_idea"], steps
                ),
                "duration_seconds": 6 + len(steps) * 3,
            },
            metadata=self._meta(context, source),
        )

    @staticmethod
    def _animation_html(
        safe_topic: str,
        headline: str,
        intro: str,
        steps: list[tuple[str, str]],
    ) -> str:
        items = "".join(
            f'<li style="--i:{index}"><span>{index + 1}</span>'
            f'<strong>{escape(title)}</strong>'
            + (f"<em>{escape(caption)}</em>" if caption else "")
            + "</li>"
            for index, (title, caption) in enumerate(steps)
        )
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    *{{box-sizing:border-box}}body{{margin:0;font-family:ui-sans-serif,system-ui;background:#f5f0e7;color:#15324a}}
    main{{min-height:100vh;padding:clamp(24px,7vw,72px);display:grid;align-content:center;overflow:hidden}}
    small{{letter-spacing:.18em;color:#e25d3f;font-weight:700}}h1{{font-size:clamp(36px,8vw,86px);margin:.2em 0}}
    p{{font-size:clamp(16px,2.4vw,24px);max-width:850px;line-height:1.7}}
    ol{{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
    li{{padding:18px;border:1px solid #c8c0b3;background:#fffaf0;border-radius:18px;animation:rise .7s ease backwards;animation-delay:calc(var(--i)*.16s)}}
    li span{{display:block;font-size:12px;color:#e25d3f}}li strong{{display:block;font-size:16px;margin-top:4px}}
    li em{{display:block;font-style:normal;font-size:13px;color:#5a6470;margin-top:6px;line-height:1.5}}
    @keyframes rise{{from{{opacity:0;transform:translateY(18px)}}}}
  </style>
</head>
<body><main>
  <small>THINK · TRY · REFLECT</small>
  <h1>{safe_topic}</h1>
  <p>{escape(headline) if not intro else escape(intro)}</p>
  <ol>{items}</ol>
</main></body></html>"""

    def serialize_for_prompt(self, resource: LearningResource) -> str:
        return json.dumps(resource.model_dump(), ensure_ascii=False)


# Required keys per role. The live adapter puts these in the system prompt so a
# model knows the shape before it starts writing.
ROLE_FIELDS = {
    "document": ["title", "sections", "self_check"],
    "mindmap": ["root", "branches"],
    "quiz": ["questions"],
    "codelab": ["task", "starter", "solution", "expected_output"],
    "slides": ["slides"],
    "animation": ["headline", "intro", "steps"],
}
