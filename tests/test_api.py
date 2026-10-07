from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.base import LLMUnavailable
from app.main import create_app
from tests.conftest import ScriptedLLM, fixture


def mock_client():
    return TestClient(create_app(Settings(llm_provider="mock")))


def test_health_and_session_creation():
    c = mock_client()
    assert c.get("/api/health").json()["llm_ready"] is True
    snap = c.post("/api/sessions").json()
    assert snap["messages"][0]["role"] == "assistant" and "FICTIONAL" in snap["document"]
    assert c.get(f"/api/sessions/{snap['session_id']}").status_code == 200


def test_full_conversation_with_mock_llm_reaches_complete_document():
    c = mock_client()
    sid = c.post("/api/sessions").json()["session_id"]
    send = lambda text: c.post(f"/api/sessions/{sid}/messages", json={"message": text}).json()
    out = send("My name is Jane Smith and I live at 12 Oak Road, London")
    assert out["state"]["data"]["full_name"] == "Jane Smith" and "worldwide" in out["reply"]
    send("Yes, worldwide")
    send("I have no children")
    send("My brother James Smith")
    send("None")
    out = send("No")
    assert out["complete"] is True
    assert "James Smith, my brother" in out["document"] and "FICTIONAL DOCUMENT" in out["document"]
    out = send("Actually my name is Jane Doe")  # correction after completion
    assert out["state"]["data"]["full_name"] == "Jane Doe" and "Jane Doe" in out["document"]


def test_mock_hedged_answer_needs_confirmation_then_confirms():
    c = mock_client()
    sid = c.post("/api/sessions").json()["session_id"]
    post = lambda t: c.post(f"/api/sessions/{sid}/messages", json={"message": t}).json()
    post("My name is Jane Smith and I live at 1 Oak Road")
    out = post("maybe worldwide")
    assert out["state"]["status"]["covers_worldwide_assets"] == "unconfirmed" and "confirm" in out["reply"]
    assert post("yes")["state"]["status"]["covers_worldwide_assets"] == "confirmed"


def test_unknown_session_and_invalid_message():
    c = mock_client()
    r = c.post("/api/sessions/nope/messages", json={"message": "hi"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"
    sid = c.post("/api/sessions").json()["session_id"]
    for body in ({"message": "   "}, {"message": ""}, {}):
        r = c.post(f"/api/sessions/{sid}/messages", json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_missing_configuration_degrades_gracefully():
    c = TestClient(create_app(Settings(llm_provider="anthropic")))
    health = c.get("/api/health").json()
    assert health["llm_ready"] is False and "ANTHROPIC_API_KEY" in health["detail"]
    sid = c.post("/api/sessions").json()["session_id"]  # app still usable
    r = c.post(f"/api/sessions/{sid}/messages", json={"message": "hi"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "llm_not_configured"


def test_provider_outage_returns_502_and_keeps_state():
    c = TestClient(create_app(Settings(), llm=ScriptedLLM(LLMUnavailable("down"))))
    sid = c.post("/api/sessions").json()["session_id"]
    r = c.post(f"/api/sessions/{sid}/messages", json={"message": "hi"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "llm_unavailable"
    assert len(c.get(f"/api/sessions/{sid}").json()["messages"]) == 1


def test_malformed_model_output_returns_200_with_warning():
    c = TestClient(create_app(Settings(), llm=ScriptedLLM(fixture("malformed_not_json"))))
    sid = c.post("/api/sessions").json()["session_id"]
    r = c.post(f"/api/sessions/{sid}/messages", json={"message": "I'm Jane"})
    assert r.status_code == 200 and r.json()["warnings"]
