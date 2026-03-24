#!/usr/bin/env python3
"""
Test script for all backend fixes.
Run: cd backend && source .venv/bin/activate && python test_fixes.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# ── Fix 4: Verify resume_scorer bullet detection ────────────────────────────

print("=" * 60)
print("FIX 4: Resume scorer bullet detection")
print("=" * 60)

from resume_scorer import ResumeScorer

s = ResumeScorer()
result = s.analyze(
    "PROFESSIONAL EXPERIENCE\n"
    "Micron Technology\n"
    "Manager | 2022-2025\n"
    "Led multi-site manufacturing. Directed a team of 10. Achieved 35% reduction."
)
bullets = s._extract_bullets(
    "PROFESSIONAL EXPERIENCE\n"
    "Micron Technology\n"
    "Manager | 2022-2025\n"
    "Led multi-site manufacturing. Directed a team of 10. Achieved 35% reduction."
)
print(f"  Bullets detected: {len(bullets)}")
for i, b in enumerate(bullets, 1):
    print(f"    {i}. {b}")
bullet_detail = result["dimensions"]["presentation"]["items"]["bullet_count"]["detail"]
print(f"  Presentation bullet_count: {bullet_detail}")
assert len(bullets) == 3, f"Expected 3 bullets, got {len(bullets)}"
print("  PASS: 3 bullets detected")

# ── Fix 5: Verify resume_parser line joining ─────────────────────────────────

print()
print("=" * 60)
print("FIX 5: Resume parser line joining")
print("=" * 60)

from resume_parser import _join_broken_lines

text = "Led cross-\nfunctional delivery across\nmultiple fabs."
result_text = _join_broken_lines(text)
print(f"  Input:  {text!r}")
print(f"  Output: {result_text!r}")
expected = "Led crossfunctional delivery across multiple fabs."
assert result_text == expected, f"Expected {expected!r}, got {result_text!r}"
print("  PASS: line joining works correctly")

# ── Fix 1: Verify admin creation code is in on_startup ───────────────────────

print()
print("=" * 60)
print("FIX 1: Admin account creation in on_startup")
print("=" * 60)

import inspect
from main import on_startup, _build_bridge_plan

on_startup_src = inspect.getsource(on_startup)
bridge_src = inspect.getsource(_build_bridge_plan)

assert "ADMIN_EMAIL" in on_startup_src, "ADMIN_EMAIL not found in on_startup"
assert "ADMIN_EMAIL" not in bridge_src, "ADMIN_EMAIL still in _build_bridge_plan (dead code)"
print("  PASS: Admin creation code is in on_startup, not in _build_bridge_plan")

# ── Fix 3: Verify all endpoints respond correctly ────────────────────────────

print()
print("=" * 60)
print("FIX 3: Endpoint response tests")
print("=" * 60)

from fastapi.testclient import TestClient
from main import app

c = TestClient(app)

# Health
r = c.get("/")
print(f"  GET /                -> {r.status_code} keys={list(r.json().keys())}")
assert r.status_code == 200

# Privacy
r = c.get("/api/privacy")
print(f"  GET /api/privacy     -> {r.status_code} (HTML)")
assert r.status_code == 200

# Tiers
r = c.get("/api/tiers")
print(f"  GET /api/tiers       -> {r.status_code} ({len(r.json())} tiers)")
assert r.status_code == 200

# Sources
r = c.get("/api/sources")
print(f"  GET /api/sources     -> {r.status_code} keys={list(r.json().keys())}")
assert r.status_code == 200

# Jobs (cached)
r = c.get("/api/jobs")
print(f"  GET /api/jobs        -> {r.status_code} keys={list(r.json().keys())}")
assert r.status_code == 200

# Encouragement
r = c.get("/api/encouragement")
print(f"  GET /api/encouragement -> {r.status_code} keys={list(r.json().keys())}")
assert r.status_code == 200

# AI status
r = c.get("/api/ai/status")
print(f"  GET /api/ai/status   -> {r.status_code} keys={list(r.json().keys())}")
assert r.status_code == 200

# Resume templates
r = c.get("/api/resume/templates")
print(f"  GET /api/resume/templates -> {r.status_code} ({len(r.json())} templates)")
assert r.status_code == 200

# Resume score (anonymous)
r = c.post("/api/resume/score", json={
    "resume_text": "Led multi-site semiconductor manufacturing operations across 3 fabs.",
    "job_description": "",
})
print(f"  POST /api/resume/score -> {r.status_code} overall={r.json().get('overall_score')}")
assert r.status_code == 200

# Contact
r = c.post("/api/contact", json={
    "name": "Test User",
    "email": "test@example.com",
    "message": "Hello from test",
})
print(f"  POST /api/contact    -> {r.status_code}")
assert r.status_code == 201

# Auth: signup
import time
test_email = f"testfix_{int(time.time())}@example.com"
r = c.post("/api/auth/signup", json={
    "email": test_email,
    "password": "TestPass123!",
    "name": "Fix Tester",
})
print(f"  POST /api/auth/signup -> {r.status_code}")
assert r.status_code == 200
token = r.json()["token"]

# Auth: login
r = c.post("/api/auth/login", json={
    "email": test_email,
    "password": "TestPass123!",
})
print(f"  POST /api/auth/login -> {r.status_code}")
assert r.status_code == 200

# Auth: me (needs auth)
headers = {"Authorization": f"Bearer {token}"}
r = c.get("/api/auth/me", headers=headers)
print(f"  GET /api/auth/me     -> {r.status_code} name={r.json().get('name')}")
assert r.status_code == 200

# Tracked: list (needs auth)
r = c.get("/api/tracked", headers=headers)
print(f"  GET /api/tracked     -> {r.status_code} ({len(r.json())} tracked)")
assert r.status_code == 200

# Tracked: create
r = c.post("/api/tracked", json={
    "company": "Test Corp",
    "role": "Engineer",
    "status": "applied",
}, headers=headers)
print(f"  POST /api/tracked    -> {r.status_code}")
assert r.status_code == 201
tracked_id = r.json()["id"]

# Tracked: update
r = c.put(f"/api/tracked/{tracked_id}", json={
    "status": "interview",
}, headers=headers)
print(f"  PUT /api/tracked/{tracked_id}  -> {r.status_code}")
assert r.status_code == 200

# Tracked: delete
r = c.delete(f"/api/tracked/{tracked_id}", headers=headers)
print(f"  DELETE /api/tracked/{tracked_id} -> {r.status_code}")
assert r.status_code == 200

# Memory: get
r = c.get("/api/memory", headers=headers)
print(f"  GET /api/memory      -> {r.status_code}")
assert r.status_code == 200

# Memory: update
r = c.put("/api/memory", json={"career_goals": "Test goal"}, headers=headers)
print(f"  PUT /api/memory      -> {r.status_code}")
assert r.status_code == 200

# Memory: delete
r = c.delete("/api/memory", headers=headers)
print(f"  DELETE /api/memory   -> {r.status_code}")
assert r.status_code == 200

# Usage (needs auth)
r = c.get("/api/usage", headers=headers)
print(f"  GET /api/usage       -> {r.status_code} keys={list(r.json().keys())}")
assert r.status_code == 200

# Skills
r = c.get("/api/skills?q=software+engineer")
print(f"  GET /api/skills      -> {r.status_code} keys={list(r.json().keys())}")
assert r.status_code == 200

print()
print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)
