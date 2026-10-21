"""tools/model_smoke.py, offline: fake clients stand in for Azure OpenAI.

The real run (`python -m tools.model_smoke --deployment ...`) is the
compatibility check before a model swap; these tests pin that it sends the
production shapes, flags unusable replies, and reports a missing deployment
as one clean table row instead of a traceback.
"""

import base64
import importlib
import io
import json
import os
from types import SimpleNamespace

import httpx
import openai
import pytest
from PIL import Image

from agents import visual_qa
from tools import model_smoke


def _reply(content: str, finish_reason: str = "stop"):
    return SimpleNamespace(
        model="gpt-5-mini-2025-08-07",
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=30,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=20),
        ),
        choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=content))],
    )


def _good_content(kwargs: dict) -> str:
    if kwargs.get("response_format") == {"type": "json_object"}:
        return '{"concepts": ["attention", "softmax"]}'
    if kwargs["max_completion_tokens"] == 16000:
        return "class SmokeScene(Scene):\n    def construct(self): ..."
    content = kwargs["messages"][-1]["content"]
    if isinstance(content, list):
        return json.dumps({"overlap": False, "cutoff": True, "collisions": False,
                           "severity": "minor", "issues": ["title overflows box"]})
    return "A Fourier transform splits a signal into frequencies."


class FakeClient:
    """Sync or async ``chat.completions.create``; records every kwargs dict."""

    def __init__(self, respond, *, is_async: bool):
        self.calls: list[dict] = []
        outer = self

        def create(**kwargs):
            outer.calls.append(kwargs)
            result = respond(kwargs)
            if isinstance(result, BaseException):
                raise result
            return result

        async def acreate(**kwargs):
            return create(**kwargs)

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=acreate if is_async else create))


def _clients(respond):
    return FakeClient(respond, is_async=True), FakeClient(respond, is_async=False)


@pytest.fixture(autouse=True)
def _no_effort_env(monkeypatch):
    # A developer's .env may set AZURE_OPENAI_REASONING_EFFORT; these tests
    # expect the code default (low) for the pipeline shapes. The tool itself
    # never writes the variable (see test_a_run_leaves_the_process_env_alone).
    monkeypatch.delenv("AZURE_OPENAI_REASONING_EFFORT", raising=False)


async def test_every_production_shape_is_sent_with_the_requested_effort():
    async_client, sync_client = _clients(lambda kw: _reply(_good_content(kw)))
    results = await model_smoke.run(
        "gpt-6-luna", "high", async_client=async_client, sync_client=sync_client,
    )

    assert [r.shape for r in results] == [
        "pipeline_text", "pipeline_json", "pipeline_sync", "visual_qa_judge", "visual_qa_repair",
    ]
    assert all(r.ok for r in results), [r.error for r in results]
    sent = async_client.calls + sync_client.calls
    assert len(sync_client.calls) == 1 and len(sent) == 5
    assert {kw["model"] for kw in sent} == {"gpt-6-luna"}
    assert {kw["reasoning_effort"] for kw in sent} == {"high"}
    assert all(r.reasoning_tokens == 20 and r.served_model.startswith("gpt-5-mini") for r in results)

    # The pipeline shapes are base._azure_request_kwargs: system + user, headroom.
    text, as_json = async_client.calls[0], async_client.calls[1]
    assert [m["role"] for m in text["messages"]] == ["system", "user"]
    assert text["max_completion_tokens"] == 256 + 4096
    assert as_json["response_format"] == {"type": "json_object"}
    # The visual-QA shapes are visual_qa.judge_request / repair_request, with
    # production's image input: VISUAL_QA_FRAMES frames at the -ql render size.
    judge, repair = async_client.calls[2], async_client.calls[3]
    assert judge["messages"][0]["content"][0]["text"] == visual_qa.JUDGE_PROMPT
    assert repair["max_completion_tokens"] == 16000
    for request in (judge, repair):
        images = [p["image_url"]["url"] for p in request["messages"][0]["content"][1:]]
        assert len(images) == visual_qa.VISUAL_QA_FRAMES
        prefix = "data:image/png;base64,"
        assert all(url.startswith(prefix) for url in images)
        frame = Image.open(io.BytesIO(base64.b64decode(images[0][len(prefix):])))
        assert frame.size == model_smoke.FRAME_SIZE == (854, 480)

    table = model_smoke.format_table(results)
    assert table.count("| ok ") == 5 and "totals: prompt 50, completion 150 (reasoning 100)" in table


async def test_a_run_leaves_the_process_env_alone(monkeypatch):
    # --effort used to be applied by writing AZURE_OPENAI_REASONING_EFFORT into
    # os.environ, which leaked "high" into every test that ran afterwards.
    async_client, sync_client = _clients(lambda kw: _reply(_good_content(kw)))
    before = dict(os.environ)
    await model_smoke.run("gpt-6-luna", "high", async_client=async_client, sync_client=sync_client)
    assert dict(os.environ) == before

    # Importing the module changes nothing either; only main() turns tracing off.
    monkeypatch.delenv("LANGFUSE_TRACING_ENABLED", raising=False)
    importlib.reload(model_smoke)
    assert "LANGFUSE_TRACING_ENABLED" not in os.environ


async def test_without_effort_each_shape_uses_its_production_setting(monkeypatch):
    monkeypatch.setattr(visual_qa, "VISUAL_QA_REASONING_EFFORT", "medium")
    async_client, sync_client = _clients(lambda kw: _reply(_good_content(kw)))
    results = await model_smoke.run("gpt-5-mini", None, async_client=async_client, sync_client=sync_client)
    assert [r.effort for r in results] == ["low", "low", "low", "medium", "medium"]


async def test_missing_deployment_is_a_clean_row_not_a_traceback():
    def not_found(_kwargs):
        response = httpx.Response(404, request=httpx.Request("POST", "https://example.invalid"))
        return openai.NotFoundError(
            "Error code: 404",
            response=response,
            body={"code": "DeploymentNotFound", "message": "The API deployment for this resource does not exist."},
        )

    async_client, sync_client = _clients(not_found)
    results = await model_smoke.run("gpt-6-luna", "medium", async_client=async_client, sync_client=sync_client)
    assert not any(r.ok for r in results)
    assert {r.error for r in results} == {
        "HTTP 404 DeploymentNotFound: The API deployment for this resource does not exist."
    }


@pytest.mark.parametrize(
    ("shape", "bad_content", "error"),
    [
        ("pipeline_text", "   ", "empty reply"),
        ("pipeline_json", "not json at all", "not parseable JSON"),
        ("visual_qa_judge", "", "empty judge reply"),
        ("visual_qa_judge", "looks fine to me", "unparseable"),
        ("visual_qa_repair", "I moved the title up.", "no class definition"),
        ("visual_qa_repair", "I cannot repair this class without more information.", "no class definition"),
    ],
)
async def test_unusable_replies_fail(shape, bad_content, error):
    order = ["pipeline_text", "pipeline_json", "pipeline_sync", "visual_qa_judge", "visual_qa_repair"]
    calls = iter(order)

    def respond(kwargs):
        return _reply(bad_content if next(calls) == shape else _good_content(kwargs))

    async_client, sync_client = _clients(respond)
    results = {r.shape: r for r in await model_smoke.run(
        "gpt-5-mini", "low", async_client=async_client, sync_client=sync_client,
    )}
    assert not results[shape].ok and error in results[shape].error
    assert all(r.ok for s, r in results.items() if s != shape)


async def test_truncated_reply_fails():
    async_client, sync_client = _clients(lambda kw: _reply(_good_content(kw), finish_reason="length"))
    results = await model_smoke.run("gpt-5-mini", "low", async_client=async_client, sync_client=sync_client)
    assert not any(r.ok for r in results)
    assert "finish_reason=length" in results[3].error


async def test_content_filtered_reply_fails_even_with_partial_content():
    async_client, sync_client = _clients(lambda kw: _reply(_good_content(kw), finish_reason="content_filter"))
    results = await model_smoke.run("gpt-5-mini", "low", async_client=async_client, sync_client=sync_client)
    assert not any(r.ok for r in results)
    assert all("finish_reason=content_filter" in r.error for r in results)


def test_exit_codes(monkeypatch, capsys):
    # setenv first so monkeypatch records the original and undoes main()'s write.
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    assert model_smoke.main(["--deployment", "gpt-5-mini"]) == 2

    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.invalid")

    async def fake_run(deployment, effort):
        return [model_smoke.Result(shape="pipeline_text", ok=ok_flag)]

    monkeypatch.setattr(model_smoke, "run", fake_run)
    ok_flag = True
    assert model_smoke.main(["--deployment", "gpt-5-mini", "--effort", "low"]) == 0
    assert os.environ["LANGFUSE_TRACING_ENABLED"] == "false"  # kept out of prod traces
    ok_flag = False
    assert model_smoke.main(["--deployment", "gpt-5-mini"]) == 1
    out = capsys.readouterr().out
    assert "FAILED: pipeline_text" in out and "test-key" not in out


def test_effort_outside_the_portable_set_is_rejected_by_the_cli():
    with pytest.raises(SystemExit):
        model_smoke.main(["--deployment", "gpt-5-mini", "--effort", "minimal"])
