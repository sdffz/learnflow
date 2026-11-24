from pydantic import BaseModel, Field

from .domain import LearnerProfile

QUESTIONS = [
    {
        "id": "q1",
        "stem": "监督学习与无监督学习最关键的差别是什么？",
        "options": ["是否使用带标签数据", "是否使用神经网络", "是否需要计算机", "是否是中文任务"],
        "answer": 0,
        "knowledge_point": "机器学习",
        "explanation": "监督学习使用带标签样本，无监督学习通常不依赖人工标签。",
    },
    {
        "id": "q2",
        "stem": "A* 搜索中的启发式函数主要起什么作用？",
        "options": ["删除所有重复状态", "保证程序不会崩溃", "估计剩余代价以引导搜索", "替代目标测试"],
        "answer": 2,
        "knowledge_point": "搜索与问题求解",
        "explanation": "启发式函数估计从当前状态到目标的剩余代价，帮助搜索聚焦。",
    },
    {
        "id": "q3",
        "stem": "ReLU 激活函数在负区间的输出是多少？",
        "options": ["0", "1", "输入本身", "无穷大"],
        "answer": 0,
        "knowledge_point": "神经网络",
        "explanation": "ReLU 在 x < 0 时输出 0，在 x >= 0 时输出 x。",
    },
    {
        "id": "q4",
        "stem": "过拟合最典型的表现是？",
        "options": ["训练集和验证集都很差", "训练集很好但验证集明显较差", "模型没有参数", "训练数据完全没有标签"],
        "answer": 1,
        "knowledge_point": "机器学习",
        "explanation": "过拟合模型记住训练样本，却难以泛化到未见数据。",
    },
    {
        "id": "q5",
        "stem": "大模型应用防止隐私泄露最可靠的措施是？",
        "options": ["只在提示词里提醒模型", "配合权限控制、日志脱敏和最小数据原则", "把所有数据公开", "关闭所有测试"],
        "answer": 1,
        "knowledge_point": "人工智能伦理",
        "explanation": "关键安全边界应通过权限、数据处理和审计等工程手段实现。",
    },
]


class AssessmentResult(BaseModel):
    score: int = Field(ge=0, le=100)
    correct_count: int
    total: int
    mastery: dict[str, float]
    updated_profile: LearnerProfile
    recommendation: str


class AssessmentAgent:
    def public_questions(self) -> list[dict]:
        return [
            {key: value for key, value in question.items() if key != "answer"}
            for question in QUESTIONS
        ]

    def grade(self, profile: LearnerProfile, answers: dict[str, int]) -> AssessmentResult:
        if set(answers) != {question["id"] for question in QUESTIONS}:
            raise ValueError("answers_must_cover_all_questions")

        totals: dict[str, int] = {}
        correct: dict[str, int] = {}
        correct_count = 0
        for question in QUESTIONS:
            point = question["knowledge_point"]
            totals[point] = totals.get(point, 0) + 1
            if answers[question["id"]] == question["answer"]:
                correct[point] = correct.get(point, 0) + 1
                correct_count += 1

        mastery = dict(profile.mastery)
        for point, total in totals.items():
            ratio = correct.get(point, 0) / total
            mastery[point] = round(0.3 + 0.65 * ratio, 2)

        score = round(correct_count / len(QUESTIONS) * 100)
        updated_profile = profile.model_copy(update={"mastery": mastery})
        recommendation = (
            "掌握较稳，可以进入项目实战并尝试迁移题。"
            if score >= 80
            else "建议先复习失分知识点，再完成一轮分层练习和代码实验。"
        )
        return AssessmentResult(
            score=score,
            correct_count=correct_count,
            total=len(QUESTIONS),
            mastery=mastery,
            updated_profile=updated_profile,
            recommendation=recommendation,
        )
