import pytest

from app.domain import AgentEvent, GenerationRun, Learner
from app.repository import Repository
from app.stream import RunStream


@pytest.mark.asyncio
async def test_stream_replays_persisted_events_for_completed_run(tmp_path):
    repository = Repository(tmp_path / "learnflow.sqlite3")
    repository.initialize()
    repository.create_learner(Learner(id="learner-1", name="测试学生"))
    repository.create_run(
        GenerationRun(
            id="run-1",
            learner_id="learner-1",
            topic="神经网络",
            status="completed",
            progress=100,
        )
    )
    repository.append_event(
        AgentEvent(
            sequence=1,
            run_id="run-1",
            agent="orchestrator",
            phase="run",
            status="completed",
            summary="完成",
        )
    )
    stream = RunStream(repository)

    events = [event async for event in stream.stream("run-1")]

    assert [event.sequence for event in events] == [1]
    repository.close()
