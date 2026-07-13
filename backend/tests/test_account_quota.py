from __future__ import annotations

import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_parallel_ai_quota_never_exceeds_account_limit():
    import main
    from auth import ACCESS_LIMITS, hash_password
    from database import SessionLocal
    from models import UsageLog, User

    db = SessionLocal()
    user = User(
        email=f"quota-{secrets.token_hex(8)}@example.com",
        password_hash=hash_password("TestPassword123!"),
        name="Quota Test",
        tier="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    previous_limit = ACCESS_LIMITS["user"]["ai_per_day"]
    ACCESS_LIMITS["user"]["ai_per_day"] = 3
    barrier = threading.Barrier(8)

    def consume() -> int:
        thread_db = SessionLocal()
        try:
            thread_user = thread_db.get(User, user_id)
            barrier.wait()
            main._consume_ai_credit(thread_user, thread_db, "parallel_test")
            return 200
        except HTTPException as exc:
            return exc.status_code
        finally:
            thread_db.close()

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(lambda _index: consume(), range(8)))

        assert statuses.count(200) == 3
        assert statuses.count(429) == 5
        assert (
            db.query(UsageLog)
            .filter(UsageLog.user_id == user_id, UsageLog.action == "ai")
            .count()
            == 3
        )
    finally:
        ACCESS_LIMITS["user"]["ai_per_day"] = previous_limit
        db.query(UsageLog).filter(UsageLog.user_id == user_id).delete()
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
        db.close()


def test_power_match_charges_only_after_cache_miss(monkeypatch):
    import main
    from auth import hash_password
    from database import SessionLocal
    from models import User, UserMemory

    db = SessionLocal()
    user = User(
        email=f"power-match-{secrets.token_hex(8)}@example.com",
        password_hash=hash_password("TestPassword123!"),
        name="Power Match Test",
        tier="user",
    )
    db.add(user)
    db.flush()
    db.add(UserMemory(user_id=user.id, resume_text="Experienced engineer " * 20))
    db.commit()
    main._power_match_cache.pop(user.id, None)
    snapshot = {"result_version": main._POWER_MATCH_RESULT_VERSION, "resume_ready": True}
    monkeypatch.setattr(main, "_job_corpus_marker", lambda _db: "corpus")
    monkeypatch.setattr(main, "_power_resume_source_meta", lambda *_args: {})
    monkeypatch.setattr(main, "_load_power_match_snapshot", lambda **_kwargs: snapshot)
    monkeypatch.setattr(
        main,
        "_consume_ai_credit",
        lambda *_args: pytest.fail("cached Smart Match must not consume quota"),
    )

    try:
        assert main.get_power_match(limit=8, direct_employers_only=True, user=user, db=db) is snapshot

        class QuotaConsumed(Exception):
            pass

        main._power_match_cache.pop(user.id, None)
        monkeypatch.setattr(main, "_load_power_match_snapshot", lambda **_kwargs: None)
        monkeypatch.setattr(
            main,
            "_consume_ai_credit",
            lambda *_args: (_ for _ in ()).throw(QuotaConsumed()),
        )
        with pytest.raises(QuotaConsumed):
            main.get_power_match(limit=8, direct_employers_only=True, user=user, db=db)
    finally:
        main._power_match_cache.pop(user.id, None)
        db.query(UserMemory).filter(UserMemory.user_id == user.id).delete()
        db.query(User).filter(User.id == user.id).delete()
        db.commit()
        db.close()


def test_legacy_recommendations_charge_before_rag_work(monkeypatch):
    import main
    from database import SessionLocal
    from starlette.responses import Response

    db = SessionLocal()
    user = SimpleNamespace(id=9_800_002, tier="user")

    class QuotaConsumed(Exception):
        pass

    monkeypatch.setattr(main._PUBLIC_RATE_LIMITER, "allow", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        main,
        "_consume_ai_credit",
        lambda *_args: (_ for _ in ()).throw(QuotaConsumed()),
    )
    monkeypatch.setattr(
        main,
        "_extract_resume_skills",
        lambda *_args: pytest.fail("RAG work must start after quota consumption"),
    )

    try:
        with pytest.raises(QuotaConsumed):
            main.get_recommended_jobs(
                body={"resume_text": "Experienced data engineer " * 4},
                response=Response(),
                user=user,
                db=db,
            )
    finally:
        db.close()


def test_http_rag_request_returns_429_after_account_quota(monkeypatch):
    import main
    from auth import ACCESS_LIMITS, get_current_user, hash_password
    from database import SessionLocal
    from fastapi.testclient import TestClient
    from models import UsageLog, User

    db = SessionLocal()
    user = User(
        email=f"http-quota-{secrets.token_hex(8)}@example.com",
        password_hash=hash_password("TestPassword123!"),
        name="HTTP Quota Test",
        tier="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    previous_limit = ACCESS_LIMITS["user"]["ai_per_day"]
    ACCESS_LIMITS["user"]["ai_per_day"] = 1
    main.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id,
        tier="user",
    )
    monkeypatch.setattr(main, "_extract_resume_skills", lambda *_args: ([], "none"))
    client = TestClient(main.app)
    body = {"resume_text": "Experienced data engineer " * 4}

    try:
        assert client.post("/api/jobs/recommended", json=body).status_code == 200
        exhausted = client.post("/api/jobs/recommended", json=body)
        assert exhausted.status_code == 429
        assert "used all 1 AI requests" in exhausted.json()["detail"]
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)
        ACCESS_LIMITS["user"]["ai_per_day"] = previous_limit
        db.query(UsageLog).filter(UsageLog.user_id == user_id).delete()
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
        db.close()


def test_cross_account_agent_chat_and_tailoring_return_404(monkeypatch):
    import main
    import tailoring_pipeline
    from auth import get_current_user
    from resume_agent import session as agent_session
    from fastapi.testclient import TestClient

    user = SimpleNamespace(id=2, tier="user")
    agent_state = agent_session._new_state("private-agent")
    agent_state["_owner_key"] = "user:1"
    tailor_state = tailoring_pipeline.PipelineState("private-tailor", owner_key="user:1")

    with agent_session._sessions_lock:
        agent_session._sessions["private-agent"] = agent_state
    with tailoring_pipeline._pipelines_lock:
        tailoring_pipeline._active_pipelines["private-tailor"] = tailor_state

    main.app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(
        main,
        "_consume_ai_credit",
        lambda *_args: pytest.fail("cross-account request must fail before quota consumption"),
    )
    client = TestClient(main.app)

    try:
        assert client.post(
            "/api/resume/agent/chat",
            json={"session_id": "private-agent", "message": "continue"},
        ).status_code == 404
        assert client.get("/api/resume/tailor/private-tailor/status").status_code == 404
        assert client.get("/api/resume/tailor/private-tailor/result").status_code == 404
        assert client.post(
            "/api/resume/tailor/private-tailor/feedback",
            json={"bullet_id": "x", "action": "accept"},
        ).status_code == 404
        assert client.post("/api/resume/tailor/private-tailor/apply").status_code == 404
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)
        with agent_session._sessions_lock:
            agent_session._sessions.pop("private-agent", None)
        with tailoring_pipeline._pipelines_lock:
            tailoring_pipeline._active_pipelines.pop("private-tailor", None)
