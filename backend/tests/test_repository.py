from app.domain import AgentEvent, GenerationRun, Learner
from app.repository import Repository
from app.resource_agents import LearningResource


def test_repository_persists_run_events_and_resources(tmp_path):
    repository = Repository(tmp_path / "learnflow.sqlite3")
    repository.initialize()
    learner = Learner(
        id="learner-1",
        name="入门型学生",
        persona_id="beginner",
    )
    repository.create_learner(learner)
    repository.create_run(
        GenerationRun(id="run-1", learner_id=learner.id, topic="神经网络")
    )

    repository.append_event(
        AgentEvent(
            sequence=1,
            run_id="run-1",
            agent="document",
            phase="resource",
            status="completed",
            summary="讲解文档已完成",
        )
    )
    repository.save_resource(
        "run-1",
        LearningResource(
            id="resource-1",
            type="document",
            title="神经网络讲解",
            knowledge_point="神经网络",
            content={"markdown": "# 神经网络"},
        ),
    )

    assert repository.list_events("run-1")[0].summary == "讲解文档已完成"
    assert repository.list_resources("run-1")[0].id == "resource-1"
