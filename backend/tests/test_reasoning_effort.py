"""reasoning_effort stays inside the values gpt-5-mini AND gpt-6-luna accept.

Production moves between the two by flipping AZURE_OPENAI_DEPLOYMENT /
VISUAL_QA_*_MODEL, with no image change. An effort only one of them accepts
("minimal" on luna, "none"/"xhigh" on gpt-5-mini) would turn that flip, or its
rollback, into a 400 on every call — so both settings are validated, and the
visual-QA calls (which used to send no effort at all) are pinned.
"""

import logging

import pytest

from agents import base, visual_qa


@pytest.fixture(autouse=True)
def _fresh_cache():
    base._checked_effort.cache_clear()
    yield
    base._checked_effort.cache_clear()


def _base_effort() -> str:
    return base._azure_request_kwargs("gpt-5-mini", "hi", "", 100)["reasoning_effort"]


# --- AZURE_OPENAI_REASONING_EFFORT (every pipeline call via base.py) ----------

@pytest.mark.parametrize("value", ["low", "medium", "high"])
def test_base_passes_portable_values_through(monkeypatch, value):
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", value)
    assert _base_effort() == value


def test_base_default_is_low_when_unset(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_REASONING_EFFORT", raising=False)
    assert _base_effort() == "low"


@pytest.mark.parametrize("value", ["minimal", "none", "xhigh", "max", "", "fast"])
def test_base_rejects_non_portable_values_with_a_warning(monkeypatch, caplog, value):
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", value)
    with caplog.at_level(logging.WARNING, logger="agents.base"):
        assert _base_effort() == "low"
    assert any("AZURE_OPENAI_REASONING_EFFORT" in r.getMessage() for r in caplog.records)


def test_case_and_whitespace_are_normalised(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", " Medium ")
    assert _base_effort() == "medium"


def test_an_invalid_value_warns_once_not_per_call(monkeypatch, caplog):
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "minimal")
    with caplog.at_level(logging.WARNING, logger="agents.base"):
        for _ in range(5):
            _base_effort()
    assert len([r for r in caplog.records if "minimal" in r.getMessage()]) == 1


# --- VISUAL_QA_REASONING_EFFORT (judge + vision repair) -----------------------

def test_visual_qa_default_is_medium(monkeypatch):
    # medium == gpt-5-mini's implicit default, i.e. no behaviour change today.
    monkeypatch.delenv("VISUAL_QA_REASONING_EFFORT", raising=False)
    assert base.portable_reasoning_effort("VISUAL_QA_REASONING_EFFORT", "medium") == "medium"


@pytest.mark.parametrize("value", ["low", "high"])
def test_visual_qa_accepts_portable_values(monkeypatch, value):
    monkeypatch.setenv("VISUAL_QA_REASONING_EFFORT", value)
    assert base.portable_reasoning_effort("VISUAL_QA_REASONING_EFFORT", "medium") == value


@pytest.mark.parametrize("value", ["minimal", "none", "xhigh"])
def test_visual_qa_invalid_falls_back_to_medium(monkeypatch, caplog, value):
    monkeypatch.setenv("VISUAL_QA_REASONING_EFFORT", value)
    with caplog.at_level(logging.WARNING, logger="agents.base"):
        assert base.portable_reasoning_effort("VISUAL_QA_REASONING_EFFORT", "medium") == "medium"
    assert any("VISUAL_QA_REASONING_EFFORT" in r.getMessage() for r in caplog.records)


def test_module_setting_is_portable():
    assert visual_qa.VISUAL_QA_REASONING_EFFORT in base.PORTABLE_REASONING_EFFORTS


def test_judge_and_repair_requests_send_the_pinned_effort(monkeypatch):
    monkeypatch.setattr(visual_qa, "VISUAL_QA_REASONING_EFFORT", "high")
    frames = [b"\x89PNG fake"]
    judge = visual_qa.judge_request(frames)
    repair = visual_qa.repair_request("class S(Scene): pass", ["overlap"], frames)
    assert judge["reasoning_effort"] == "high" and repair["reasoning_effort"] == "high"
    # The rest of each call shape is what production has always sent.
    assert judge["max_completion_tokens"] == 4096 and repair["max_completion_tokens"] == 16000
    assert judge["model"] == visual_qa.VISUAL_QA_MODEL
    assert repair["model"] == visual_qa.VISUAL_QA_REPAIR_MODEL
    for req in (judge, repair):
        [message] = req["messages"]
        assert message["role"] == "user"
        assert [part["type"] for part in message["content"]] == ["text", "image_url"]
        assert message["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_requests_accept_a_deployment_and_effort_override():
    # tools/model_smoke.py sends the production shapes to another deployment.
    req = visual_qa.judge_request([b"x"], model="gpt-6-luna", effort="low")
    assert req["model"] == "gpt-6-luna" and req["reasoning_effort"] == "low"
