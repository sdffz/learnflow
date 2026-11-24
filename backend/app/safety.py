import re

from pydantic import BaseModel


class SafetyResult(BaseModel):
    allowed: bool
    reason: str | None = None


class SafetyService:
    BLOCKED = re.compile(r"危险方案|攻击学校|制作炸弹|窃取密码")

    def check(self, text: str) -> SafetyResult:
        if self.BLOCKED.search(text):
            return SafetyResult(allowed=False, reason="sensitive_content")
        return SafetyResult(allowed=True)
