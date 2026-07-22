"""Unit tests for trazo.core.context (TRZ-P2-01).

DoD: thread + nested-context tests. The nested-context tests prove the
step stack behaves correctly under nesting; the thread tests prove
contextvar isolation across threads and that the per-run seq counter
still serializes correctly *within* one run even when touched from
multiple threads.
"""

from __future__ import annotations

import threading

import pytest

from trazo.core.context import (
    agent_scope,
    current_agent_id,
    current_run_id,
    current_step_id,
    get_config,
    init,
    is_initialized,
    run_scope,
    step_scope,
)
from trazo.errors import NotInitializedError

# These tests exercise trazo.core.context.init directly, not the public
# trazo.init — the latter also starts a real background Shipper thread
# (TRZ-P2-03), which these config-resolution tests have no need for.


def test_init__resolves_config() -> None:
    init(project="research-assistant", endpoint="http://example.test", api_key="k")

    config = get_config()
    assert config.project == "research-assistant"
    assert config.endpoint == "http://example.test"
    assert config.api_key == "k"


def test_init__falls_back_to_env_var_for_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAZO_API_KEY", "from-env")
    init(project="p")
    assert get_config().api_key == "from-env"


def test_get_config__before_init_raises_not_initialized() -> None:
    assert is_initialized() is False
    with pytest.raises(NotInitializedError):
        get_config()


def test_run_scope__establishes_and_tears_down_run_context() -> None:
    assert current_run_id() is None

    with run_scope("proj") as ctx:
        assert current_run_id() == ctx.run_id
        assert ctx.run_id.startswith("run_")

    assert current_run_id() is None


def test_run_scope__seq_counter_strictly_increases_from_zero() -> None:
    with run_scope("proj") as ctx:
        assert [ctx.next_seq() for _ in range(5)] == [0, 1, 2, 3, 4]


def test_step_scope__nests_and_current_step_id_is_innermost() -> None:
    assert current_step_id() is None

    with step_scope("stp_outer") as outer:
        assert current_step_id() == outer
        with step_scope("stp_inner") as inner:
            assert current_step_id() == inner
            assert inner != outer
        assert current_step_id() == outer  # back to outer after inner exits

    assert current_step_id() is None


def test_step_scope__sibling_steps_do_not_leak_into_each_other() -> None:
    with step_scope("stp_a"):
        pass
    with step_scope("stp_b") as b:
        assert current_step_id() == b


def test_agent_scope__sets_and_restores_agent_id() -> None:
    assert current_agent_id() is None
    with agent_scope("researcher"):
        assert current_agent_id() == "researcher"
    assert current_agent_id() is None


def test_context__isolated_across_threads() -> None:
    """Setting run/step/agent context in one thread must not be visible in
    another — contextvars are per-thread by default."""
    other_thread_saw: dict[str, object] = {}

    def _other_thread() -> None:
        other_thread_saw["run_id"] = current_run_id()
        other_thread_saw["step_id"] = current_step_id()
        other_thread_saw["agent_id"] = current_agent_id()

    with run_scope("proj") as ctx, step_scope() as step, agent_scope("researcher"):
        thread = threading.Thread(target=_other_thread)
        thread.start()
        thread.join()

        # the main thread's context is still intact after the other thread ran
        assert current_run_id() == ctx.run_id
        assert current_step_id() == step

    assert other_thread_saw == {"run_id": None, "step_id": None, "agent_id": None}


def test_context__seq_counter_is_shared_and_thread_safe_within_one_run() -> None:
    """Even though contextvars don't cross threads, the RunContext object
    passed explicitly to worker threads shares one _SeqCounter instance —
    concurrent next_seq() calls from multiple threads must never collide."""
    with run_scope("proj") as ctx:
        seqs: list[int] = []
        lock = threading.Lock()

        def _worker() -> None:
            for _ in range(200):
                seq = ctx.next_seq()
                with lock:
                    seqs.append(seq)

        threads = [threading.Thread(target=_worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(seqs) == list(range(8 * 200))  # no duplicates, no gaps
