from uuid import uuid4

from pydantic import BaseModel, Field

from .domain import Learner, utc_now


class PathNode(BaseModel):
    id: str
    title: str
    topic: str
    status: str
    dependency: str | None = None
    recommendation: str
    resource_types: list[str]


class LearningPath(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    learner_id: str
    title: str
    nodes: list[PathNode]
    adjustment_note: str
    created_at: str = Field(default_factory=utc_now)


TOPICS = {
    "人工智能概述": {
        "title": "建立人工智能的基本坐标系",
        "dependency": None,
    },
    "搜索与问题求解": {
        "title": "理解状态、动作与启发式搜索",
        "dependency": "人工智能概述",
    },
    "机器学习": {
        "title": "从数据中学习可泛化的规律",
        "dependency": "人工智能概述",
    },
    "神经网络": {
        "title": "理解前向传播、损失与反向传播",
        "dependency": "机器学习",
    },
    "人工智能伦理": {
        "title": "把公平、隐私和问责纳入设计",
        "dependency": "神经网络",
    },
}


class PathAgent:
    def build(self, learner: Learner) -> LearningPath:
        profile = learner.profile
        weak_dimension = profile.dimensions.get("当前薄弱点")
        weak_point = weak_dimension.value if weak_dimension else "机器学习"
        goal_dimension = profile.dimensions.get("学习目标")
        goal = goal_dimension.value if goal_dimension else "系统学习"
        preference_dimension = profile.dimensions.get("资源偏好")
        preference = preference_dimension.value if preference_dimension else "图解"

        topics = list(TOPICS)
        if weak_point in topics:
            topics.remove(weak_point)
            topics.insert(1, weak_point)

        resource_types = ["document", "mindmap"]
        if "题" in preference or goal == "准备考试":
            resource_types.extend(["quiz", "slides"])
        elif "代码" in preference or goal == "完成项目":
            resource_types.extend(["codelab", "animation"])
        else:
            resource_types.extend(["animation", "slides"])

        nodes = []
        previous_topic = None
        for index, topic in enumerate(topics):
            node = TOPICS[topic]
            nodes.append(
                PathNode(
                    id=f"node-{index + 1}",
                    title=node["title"],
                    topic=topic,
                    status="current" if index == 0 else "planned",
                    dependency=previous_topic,
                    recommendation=(
                        f"因为你的目标是“{goal}”，且当前需要加强“{weak_point}”，"
                        f"本节点优先使用{preference}类资源。"
                    ),
                    resource_types=resource_types,
                )
            )
            previous_topic = topic

        return LearningPath(
            learner_id=learner.id,
            title=f"{learner.name}的《人工智能导论》学习路径",
            nodes=nodes,
            adjustment_note=(
                f"路径已依据“{goal}”和薄弱点“{weak_point}”重排；"
                "完成练习后系统会再次调整。"
            ),
        )
