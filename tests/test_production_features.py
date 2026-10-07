from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.storage.sessions import InMemorySessionStore


def client():
    return TestClient(create_app(Settings(llm_provider="mock", rate_limit_per_minute=100), store=InMemorySessionStore()))

def test_patch_history_undo_and_exports():
    c=client(); created=c.post('/api/v1/sessions').json(); sid=created['session_id']
    r=c.patch(f'/api/v1/sessions/{sid}/fields/full_name',json={'value':'Jane Smith'}); assert r.status_code==200
    assert r.json()['state']['structured']['full_name']=='Jane Smith'
    history=c.get(f'/api/v1/sessions/{sid}/history'); assert history.status_code==200 and history.json()
    assert c.get(f'/api/v1/sessions/{sid}/export.pdf').headers['content-type'].startswith('application/pdf')
    assert 'wordprocessingml.document' in c.get(f'/api/v1/sessions/{sid}/export.docx').headers['content-type']
    undone=c.post(f'/api/v1/sessions/{sid}/undo').json(); assert undone['state']['structured']['full_name'] is None

def test_request_id_and_rate_limit():
    c=TestClient(create_app(Settings(llm_provider='mock',rate_limit_per_minute=1),store=InMemorySessionStore()))
    a=c.get('/api/health'); b=c.get('/api/health')
    assert a.headers['x-request-id'] and b.status_code==429
