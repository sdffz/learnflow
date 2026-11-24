import pytest

from app.domain import LearnerProfile
from app.profile_agent import extract_dimensions, extract_profile, next_profile_question


def test_extracts_more_than_six_profile_dimensions():
    update = extract_profile(
        LearnerProfile(),
        "我是软件工程大一学生，Python 会一点，想完成课程项目，"
        "喜欢视频和图解，每周能学 6 小时，神经网络比较薄弱，对机器人感兴趣。",
    )

    assert len(update.profile.dimensions) >= 6
    assert update.profile.dimensions["编程基础"].value == "入门"
    # Values are captured from the sentence, so the goal keeps the learner's
    # own wording instead of a normalised label.
    assert "项目" in update.profile.dimensions["学习目标"].value


def test_low_information_message_keeps_existing_dimensions():
    initial = extract_profile(LearnerProfile(), "我零基础，想准备考试。").profile

    update = extract_profile(initial, "好的")

    assert update.profile.dimensions["编程基础"].value == "零基础"
    assert "考试" in update.profile.dimensions["学习目标"].value
    assert update.changed_dimensions == []


def test_question_requests_a_missing_dimension():
    profile = extract_profile(LearnerProfile(), "我零基础，刚接触 AI。").profile

    question = next_profile_question(profile)

    assert "学习目标" in question


@pytest.mark.asyncio
async def test_message_without_new_signal_keeps_confidence_intact():
    """A message the extractor cannot parse must not churn existing dimensions.

    Regression: the offline provider echoed stored dimensions back with a
    lowered confidence, so every "unparseable" turn both reported changes that
    did not happen and shrank every axis of the radar chart.
    """
    from app.model_gateway import MockProvider
    from app.profile_agent import extract_profile_with_model

    first, _ = await extract_profile_with_model(
        LearnerProfile(),
        "我是软件工程大二学生，Python 会一点，想完成课程项目，"
        "喜欢视频和图解，每周能学 6 小时。",
        MockProvider(),
    )
    before = {
        name: dimension.confidence
        for name, dimension in first.profile.dimensions.items()
    }
    assert len(before) >= 4

    second, source = await extract_profile_with_model(
        first.profile,
        "嗯嗯知道了",
        MockProvider(),
    )

    after = {
        name: dimension.confidence
        for name, dimension in second.profile.dimensions.items()
    }
    assert after == before
    assert second.changed_dimensions == []
    assert source == "rules"


@pytest.mark.asyncio
async def test_natural_sentence_covers_six_dimensions():
    """The challenge requires >= 6 dimensions from a normal self-description."""
    from app.model_gateway import MockProvider
    from app.profile_agent import extract_profile_with_model

    update, _ = await extract_profile_with_model(
        LearnerProfile(),
        "我是软件工程大二学生，Python会一点，想完成课程项目，"
        "喜欢视频和图解，每周能学6小时，编程能力比较薄弱，对网络安全感兴趣",
        MockProvider(),
    )

    dimensions = update.profile.dimensions
    assert len(dimensions) >= 6
    assert dimensions["先修知识"].value == "大二"
    assert dimensions["当前薄弱点"].value == "编程"
    assert dimensions["兴趣方向"].value == "网络安全"
    assert dimensions["学习节奏"].value == "每周6小时"


@pytest.mark.asyncio
async def test_parsed_message_updates_only_the_named_dimension():
    from app.model_gateway import MockProvider
    from app.profile_agent import extract_profile_with_model

    first, _ = await extract_profile_with_model(
        LearnerProfile(),
        "我想完成项目，喜欢视频和图解，每周能学 6 小时。",
        MockProvider(),
    )
    untouched = {
        name: dimension.confidence
        for name, dimension in first.profile.dimensions.items()
        if name != "学习目标"
    }

    second, _ = await extract_profile_with_model(
        first.profile,
        "其实我目标是想通过考试",
        MockProvider(),
    )

    assert "考试" in second.profile.dimensions["学习目标"].value
    assert "学习目标" in second.changed_dimensions
    assert set(second.changed_dimensions) == {"学习目标"}
    for name, confidence in untouched.items():
        assert second.profile.dimensions[name].confidence == confidence


# --- capture-based extraction: unknown phrasings must still work -------------


@pytest.mark.parametrize(
    "sentence,dimension,expected",
    [
        ("想做渗透测试方向，密码学一直搞不懂", "当前薄弱点", "密码学"),
        ("想做渗透测试方向，密码学一直搞不懂", "兴趣方向", "渗透测试"),
        ("我对分布式系统超级感兴趣", "兴趣方向", "分布式系统"),
        ("但操作系统没掌握", "当前薄弱点", "操作系统"),
        ("概率论薄弱", "当前薄弱点", "概率论"),
        ("我在准备考研", "学习目标", "考研"),
        ("大三了", "先修知识", "大三"),
        ("每天只能学半小时", "学习节奏", "每天0.5小时"),
    ],
)
def test_captures_unseen_phrasings(sentence, dimension, expected):
    """Values are spans from the learner's sentence, not a fixed vocabulary.

    A whitelist would only recognise phrasings somebody had already listed, so
    topics like 密码学 or 分布式系统 used to fall through silently.
    """
    found = extract_dimensions(sentence)

    assert dimension in found, f"{sentence!r} 未抽取到 {dimension}"
    assert found[dimension][0] == expected


def test_captured_value_keeps_the_learners_own_wording():
    found = extract_dimensions("我对多模态生成特别感兴趣")

    assert found["兴趣方向"][0] == "多模态生成"
    # The evidence shows the phrase the value came from.
    assert "感兴趣" in found["兴趣方向"][1]


def test_media_preference_is_not_mistaken_for_an_interest():
    found = extract_dimensions("我对刷题特别感兴趣")

    assert "兴趣方向" not in found
    assert found["资源偏好"][0] == "练习题库"


def test_noise_words_are_trimmed_from_captured_spans():
    found = extract_dimensions("但操作系统没掌握")

    assert found["当前薄弱点"][0] == "操作系统"