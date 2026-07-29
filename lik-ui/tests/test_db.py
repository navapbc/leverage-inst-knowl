"""Store round-trip tests. Require a reachable `_test` Postgres (see conftest `db`)."""

from datetime import datetime, timedelta, timezone


def test_upsert_user_is_idempotent(store):
    first = store.upsert_user("alice@navapbc.com")
    again = store.upsert_user("alice@navapbc.com")
    assert first["id"] == again["id"]
    assert store.get_user_by_email("alice@navapbc.com")["id"] == first["id"]


def test_user_vault_mapping_roundtrips_and_is_unique(store):
    user = store.upsert_user("bob@navapbc.com")
    assert store.get_user_vault(user["id"]) is None
    store.set_user_vault(user["id"], "vlt_1")
    assert store.get_user_vault(user["id"]) == "vlt_1"
    # One vault per user: a second set overwrites rather than duplicating.
    store.set_user_vault(user["id"], "vlt_2")
    assert store.get_user_vault(user["id"]) == "vlt_2"


def test_sessions_are_scoped_to_their_user(store):
    a = store.upsert_user("a@navapbc.com")
    b = store.upsert_user("b@navapbc.com")
    sess = store.create_session(a["id"], "agent_1", "sess_1", title="First")
    assert [s["session_id"] for s in store.list_sessions(a["id"])] == [sess["session_id"]]
    assert store.list_sessions(b["id"]) == []
    # b cannot open a's session
    assert store.get_session(sess["session_id"], b["id"]) is None
    assert store.get_session(sess["session_id"], a["id"])["session_id"] == "sess_1"


def test_new_session_is_private_by_default(store):
    a = store.upsert_user("a@navapbc.com")
    sess = store.create_session(a["id"], "agent_1", "sess_1")
    assert sess["shared"] is False
    assert store.get_session("sess_1", a["id"])["shared"] is False


def test_shared_session_is_readable_by_non_owner(store):
    a = store.upsert_user("a@navapbc.com")
    b = store.upsert_user("b@navapbc.com")
    store.create_session(a["id"], "agent_1", "sess_1", title="First")
    # Private: only the owner can reach it via the read accessor.
    assert store.get_accessible_session("sess_1", b["id"]) is None
    assert store.get_accessible_session("sess_1", a["id"])["session_id"] == "sess_1"
    # Once shared, a different user can reach it read-only.
    assert store.set_session_shared("sess_1", a["id"], True) is True
    assert store.get_accessible_session("sess_1", b["id"])["session_id"] == "sess_1"
    # But it still does not appear in b's own list (no per-user copy).
    assert store.list_sessions(b["id"]) == []
    # Un-sharing revokes the non-owner's access again.
    assert store.set_session_shared("sess_1", a["id"], False) is True
    assert store.get_accessible_session("sess_1", b["id"]) is None


def test_get_accessible_session_unknown_id_is_none(store):
    a = store.upsert_user("a@navapbc.com")
    assert store.get_accessible_session("nope", a["id"]) is None


def test_set_session_shared_is_owner_scoped(store):
    a = store.upsert_user("a@navapbc.com")
    b = store.upsert_user("b@navapbc.com")
    store.create_session(a["id"], "agent_1", "sess_1")
    # A non-owner cannot share someone else's session; nothing changes.
    assert store.set_session_shared("sess_1", b["id"], True) is False
    assert store.get_session("sess_1", a["id"])["shared"] is False
    assert store.get_accessible_session("sess_1", b["id"]) is None


def test_new_session_defaults_to_seven_day_auto_delete(store):
    a = store.upsert_user("a@navapbc.com")
    sess = store.create_session(a["id"], "agent_1", "sess_1")
    # now() is the transaction instant, so both defaults evaluate it identically: the
    # auto-delete time is exactly 7 days after creation.
    assert sess["auto_delete_at"] - sess["created_at"] == timedelta(days=7)
    assert store.get_session("sess_1", a["id"])["auto_delete_at"] == sess["auto_delete_at"]


def test_set_session_auto_delete_at_reschedules(store):
    a = store.upsert_user("a@navapbc.com")
    store.create_session(a["id"], "agent_1", "sess_1")
    when = datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert store.set_session_auto_delete_at("sess_1", a["id"], when) is True
    # Compare the instant, not the rendered offset (psycopg renders in the session tz).
    assert store.get_session("sess_1", a["id"])["auto_delete_at"] == when


def test_set_session_auto_delete_at_is_owner_scoped(store):
    a = store.upsert_user("a@navapbc.com")
    b = store.upsert_user("b@navapbc.com")
    original = store.create_session(a["id"], "agent_1", "sess_1")["auto_delete_at"]
    # A non-owner cannot reschedule someone else's session; nothing changes.
    assert store.set_session_auto_delete_at("sess_1", b["id"], datetime(2030, 1, 1, tzinfo=timezone.utc)) is False
    assert store.get_session("sess_1", a["id"])["auto_delete_at"] == original


def test_list_sessions_due_returns_only_expired_with_owner(store):
    a = store.upsert_user("a@navapbc.com")
    b = store.upsert_user("b@navapbc.com")
    # One already-expired (owned by b), one far in the future (owned by a, default +7d).
    store.create_session(b["id"], "agent_1", "past")
    store.set_session_auto_delete_at("past", b["id"], datetime(2000, 1, 1, tzinfo=timezone.utc))
    store.create_session(a["id"], "agent_1", "future")

    due = store.list_sessions_due(datetime.now(timezone.utc))

    assert [(s["session_id"], s["user_id"]) for s in due] == [("past", b["id"])]


def test_list_sessions_due_empty_when_nothing_expired(store):
    a = store.upsert_user("a@navapbc.com")
    store.create_session(a["id"], "agent_1", "sess_1")  # default +7d, not yet due
    assert store.list_sessions_due(datetime.now(timezone.utc)) == []


def test_migration_backfills_existing_rows_to_now_plus_seven_days(store, db):
    """Exercise the prod-migration branch (not just the fresh-CREATE-TABLE default): an
    existing row from before the column existed must be backfilled to now()+7d — a fresh
    window — NOT created_at+7d, which for an old session would already be in the past."""
    from tests.conftest import INIT_SQL

    a = store.upsert_user("old@navapbc.com")
    # Simulate a pre-existing table: drop the column, insert a session with an old created_at.
    with db.connection() as conn:
        conn.execute("ALTER TABLE sessions DROP COLUMN auto_delete_at")
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, agent_id, created_at) "
            "VALUES ('old', %s, 'agent_1', now() - interval '90 days')",
            (a["id"],),
        )
        conn.commit()
    # Re-apply init.sql (idempotent) -> runs the ADD COLUMN ... NOT NULL DEFAULT migration.
    with db.connection() as conn:
        conn.execute(INIT_SQL.read_text())
        conn.commit()

    now = datetime.now(timezone.utc)
    backfilled = store.get_session("old", a["id"])["auto_delete_at"]
    # ~now()+7d (fresh window), decidedly NOT created_at+7d (which would be ~83 days in the past).
    assert now + timedelta(days=6) < backfilled < now + timedelta(days=8)


# --- scheduled runs (U1: owner-scoped CRUD) ------------------------------------


def test_get_user_by_id_roundtrips(store):
    a = store.upsert_user("a@navapbc.com")
    got = store.get_user_by_id(a["id"])
    assert got["id"] == a["id"] and got["email"] == "a@navapbc.com"
    assert store.get_user_by_id(999999) is None


def test_create_scheduled_run_roundtrips(store):
    a = store.upsert_user("a@navapbc.com")
    run = store.create_scheduled_run(a["id"], "Catalog Registration Agent", "sync the indexes", timedelta(days=1))
    assert run["agent_name"] == "Catalog Registration Agent"
    assert run["prompt"] == "sync the indexes"
    assert run["run_interval"] == timedelta(days=1)
    assert run["paused"] is False and run["pause_reason"] is None
    assert run["started_at"] is None and run["completed_at"] is None
    # Due immediately on creation so the first scan picks it up.
    assert run["next_run_at"] is not None
    listed = store.list_scheduled_runs(a["id"])
    assert [r["id"] for r in listed] == [run["id"]]


def test_scheduled_runs_are_owner_scoped(store):
    a = store.upsert_user("a@navapbc.com")
    b = store.upsert_user("b@navapbc.com")
    run = store.create_scheduled_run(a["id"], "agent", "go", timedelta(hours=1))
    # b sees none of a's schedules.
    assert store.list_scheduled_runs(b["id"]) == []
    # b cannot delete a's schedule; a can.
    assert store.delete_scheduled_run(run["id"], b["id"]) is False
    assert store.list_scheduled_runs(a["id"]) != []
    assert store.delete_scheduled_run(run["id"], a["id"]) is True
    assert store.list_scheduled_runs(a["id"]) == []


def test_set_scheduled_run_paused_is_owner_scoped(store):
    a = store.upsert_user("a@navapbc.com")
    b = store.upsert_user("b@navapbc.com")
    run = store.create_scheduled_run(a["id"], "agent", "go", timedelta(hours=1))
    assert store.set_scheduled_run_paused(run["id"], b["id"], True) is False
    assert store.set_scheduled_run_paused(run["id"], a["id"], True) is True
    assert store.list_scheduled_runs(a["id"])[0]["paused"] is True
    # Resuming clears any pause_reason.
    assert store.set_scheduled_run_paused(run["id"], a["id"], False) is True
    row = store.list_scheduled_runs(a["id"])[0]
    assert row["paused"] is False and row["pause_reason"] is None


def test_delete_scheduled_runs_for_user_removes_all(store):
    a = store.upsert_user("a@navapbc.com")
    b = store.upsert_user("b@navapbc.com")
    store.create_scheduled_run(a["id"], "agent", "one", timedelta(hours=1))
    store.create_scheduled_run(a["id"], "agent", "two", timedelta(hours=2))
    store.create_scheduled_run(b["id"], "agent", "other", timedelta(hours=1))
    assert store.delete_scheduled_runs_for_user(a["id"]) == 2
    assert store.list_scheduled_runs(a["id"]) == []
    # b's schedule is untouched.
    assert len(store.list_scheduled_runs(b["id"])) == 1


# --- scheduled runs (U4: scanner claim / complete / pause) ---------------------


def _set_run(db, run_id, **cols):
    """Poke scheduled_runs columns directly to simulate scheduler state (in-flight, due times)."""
    assigns = ", ".join(f"{k} = %s" for k in cols)
    with db.connection() as conn:
        conn.execute(f"UPDATE scheduled_runs SET {assigns} WHERE id = %s", (*cols.values(), run_id))
        conn.commit()


def test_claim_due_runs_claims_due_and_marks_in_flight(store):
    a = store.upsert_user("a@navapbc.com")
    run = store.create_scheduled_run(a["id"], "agent", "go", timedelta(hours=1))  # due immediately
    claimed = store.claim_due_runs()
    assert [r["id"] for r in claimed] == [run["id"]]
    assert claimed[0]["started_at"] is not None  # marked in flight
    # A second scan does not re-claim it (atomic claim; started_at now set, not yet stuck).
    assert store.claim_due_runs() == []


def test_claim_due_runs_skips_paused_and_not_yet_due(store):
    a = store.upsert_user("a@navapbc.com")
    paused = store.create_scheduled_run(a["id"], "agent", "p", timedelta(hours=1))
    store.set_scheduled_run_paused(paused["id"], a["id"], True)
    future = store.create_scheduled_run(a["id"], "agent", "f", timedelta(hours=1))
    _set_run(store.db, future["id"], next_run_at=datetime(2999, 1, 1, tzinfo=timezone.utc))
    assert store.claim_due_runs() == []


def test_claim_due_runs_reclaims_stuck_but_not_live(store):
    a = store.upsert_user("a@navapbc.com")
    now = datetime.now(timezone.utc)
    # A live run: in flight, started 1 min ago, max_runtime 1800s -> well within budget.
    live = store.create_scheduled_run(a["id"], "agent", "live", timedelta(hours=1), max_runtime_s=1800)
    _set_run(store.db, live["id"], started_at=now - timedelta(minutes=1), completed_at=None)
    # A stuck run: in flight, started 40 min ago, max_runtime 60s -> far past 60s + margin.
    stuck = store.create_scheduled_run(a["id"], "agent", "stuck", timedelta(hours=1), max_runtime_s=60)
    _set_run(store.db, stuck["id"], started_at=now - timedelta(minutes=40), completed_at=None)

    claimed = store.claim_due_runs()

    # Only the stuck one is reclaimed; the live runner (within its budget) is left alone.
    assert [r["id"] for r in claimed] == [stuck["id"]]
    assert claimed[0]["last_status"] == "abandoned"


def test_complete_run_records_outcome_and_advances(store):
    a = store.upsert_user("a@navapbc.com")
    run = store.create_scheduled_run(a["id"], "agent", "go", timedelta(hours=1))
    store.claim_due_runs()  # in flight
    store.complete_run(run["id"], "success", None, [{"server": "s", "tool": "t"}])
    row = store.list_scheduled_runs(a["id"])[0]
    assert row["started_at"] is None  # no longer in flight
    assert row["last_status"] == "success"
    assert row["last_skipped"] == [{"server": "s", "tool": "t"}]
    # next_run_at advanced to ~now + run_interval (1 hour).
    now = datetime.now(timezone.utc)
    assert now + timedelta(minutes=55) < row["next_run_at"] < now + timedelta(minutes=65)


def test_pause_and_flag_pauses_without_advancing(store):
    a = store.upsert_user("a@navapbc.com")
    run = store.create_scheduled_run(a["id"], "agent", "go", timedelta(hours=1))
    original_due = run["next_run_at"]
    store.claim_due_runs()
    store.pause_and_flag(run["id"], "needs_reauth", error="Confluence auth lapsed")
    row = store.list_scheduled_runs(a["id"])[0]
    assert row["paused"] is True and row["pause_reason"] == "needs_reauth"
    assert row["last_status"] == "auth_lapsed"
    assert row["started_at"] is None
    assert row["next_run_at"] == original_due  # not advanced
    # A paused row is never claimed even though it's due.
    assert store.claim_due_runs() == []


def test_session_analytics_upsert_is_idempotent_on_session_id(store):
    u = store.upsert_user("a@navapbc.com")
    base = {"session_id": "s1", "user_id": u["id"], "deletion_path": "manual", "input_tokens": 10}
    store.write_session_analytics(base)
    # A second write for the same session overwrites — exactly one record (R5).
    store.write_session_analytics({**base, "input_tokens": 99, "output_tokens": 5})
    rec = store.get_session_analytics("s1")
    assert rec["input_tokens"] == 99 and rec["output_tokens"] == 5
    with store.db.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM session_analytics").fetchone()["n"] == 1


def test_session_analytics_full_record_roundtrips_including_jsonb(store):
    u = store.upsert_user("a@navapbc.com")
    record = {
        "session_id": "s1", "user_id": u["id"], "user_email": "a@navapbc.com",
        "agent_id": "agent_1", "deletion_path": "prune",
        "input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 10, "cache_creation_tokens": 7,
        "active_seconds": 12.5, "wall_clock_seconds": 30.0,
        "user_message_count": 3, "ai_message_count": 3, "tool_use_count": 4, "error_count": 1,
        "tool_breakdown": {"tools": {"search": 3}, "servers": {"confluence": 3}},
        "error_types": {"mcp_connection_failed": 1},
    }
    store.write_session_analytics(record)
    rec = store.get_session_analytics("s1")
    assert rec["tool_breakdown"] == {"tools": {"search": 3}, "servers": {"confluence": 3}}
    assert rec["error_types"] == {"mcp_connection_failed": 1}
    assert rec["cache_creation_tokens"] == 7 and rec["tool_use_count"] == 4


def test_session_analytics_flagged_local_only_record(store):
    u = store.upsert_user("a@navapbc.com")
    store.write_session_analytics({
        "session_id": "s1", "user_id": u["id"], "deletion_path": "self_heal",
        "capture_incomplete": True, "capture_reason": "lost before capture",
    })
    rec = store.get_session_analytics("s1")
    assert rec["capture_incomplete"] is True and rec["capture_reason"] == "lost before capture"
    assert rec["input_tokens"] is None and rec["deleted_at"] is not None  # metrics null, still stamped


def test_session_analytics_outlives_user_deletion(store):
    u = store.upsert_user("a@navapbc.com")
    store.write_session_analytics({"session_id": "s1", "user_id": u["id"], "deletion_path": "manual"})
    # No FK cascade: deleting the user must NOT remove the analytics record.
    with store.db.connection() as conn:
        conn.execute("DELETE FROM users WHERE id = %s", (u["id"],))
        conn.commit()
    assert store.get_session_analytics("s1") is not None


def test_list_sessions_due_carries_agent_and_created_at(store):
    u = store.upsert_user("a@navapbc.com")
    store.create_session(u["id"], "agent_7", "s1")
    store.set_session_auto_delete_at("s1", u["id"], datetime.now(timezone.utc) - timedelta(days=1))
    due = store.list_sessions_due(datetime.now(timezone.utc))
    assert len(due) == 1
    assert due[0]["agent_id"] == "agent_7" and due[0]["created_at"] is not None


def _seed_analytics(store, session_id, user_id, email, tokens, path="prune"):
    store.write_session_analytics({
        "session_id": session_id, "user_id": user_id, "user_email": email,
        "deletion_path": path, "input_tokens": tokens, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_creation_tokens": 0,
        "tool_use_count": 2, "error_count": 1,
    })


def test_analytics_totals_scope_own_vs_all(store):
    a = store.upsert_user("a@navapbc.com")
    b = store.upsert_user("b@navapbc.com")
    _seed_analytics(store, "s1", a["id"], "a@navapbc.com", 100)
    _seed_analytics(store, "s2", a["id"], "a@navapbc.com", 50)
    _seed_analytics(store, "s3", b["id"], "b@navapbc.com", 10)
    own = store.session_analytics_totals(a["id"])
    assert own["sessions"] == 2 and own["total_tokens"] == 150 and own["tool_use_count"] == 4
    all_users = store.session_analytics_totals()
    assert all_users["sessions"] == 3 and all_users["total_tokens"] == 160


def test_analytics_totals_empty_is_zeroed(store):
    a = store.upsert_user("a@navapbc.com")
    t = store.session_analytics_totals(a["id"])
    assert t["sessions"] == 0 and t["total_tokens"] == 0 and t["error_count"] == 0


def test_analytics_daily_buckets_and_by_user(store):
    a = store.upsert_user("a@navapbc.com")
    b = store.upsert_user("b@navapbc.com")
    _seed_analytics(store, "s1", a["id"], "a@navapbc.com", 100)
    _seed_analytics(store, "s2", b["id"], "b@navapbc.com", 40)
    daily = store.session_analytics_daily()
    assert sum(row["sessions"] for row in daily) == 2
    assert sum(row["tokens"] for row in daily) == 140
    by_user = store.session_analytics_by_user()
    assert by_user[0]["user_email"] == "a@navapbc.com" and by_user[0]["tokens"] == 100
    assert {r["user_email"] for r in by_user} == {"a@navapbc.com", "b@navapbc.com"}


def test_list_all_sessions_spans_users_with_email(store):
    a = store.upsert_user("a@navapbc.com")
    b = store.upsert_user("b@navapbc.com")
    store.create_session(a["id"], "agent_1", "s1")
    store.create_session(b["id"], "agent_1", "s2")
    rows = store.list_all_sessions()
    assert {r["session_id"] for r in rows} == {"s1", "s2"}
    assert {r["user_email"] for r in rows} == {"a@navapbc.com", "b@navapbc.com"}


def test_analytics_totals_split_mcp_vs_builtin_tool_calls(store):
    u = store.upsert_user("a@navapbc.com")
    store.write_session_analytics({
        "session_id": "s1", "user_id": u["id"], "deletion_path": "prune", "tool_use_count": 5,
        "tool_breakdown": {"tools": {"search": 3, "think": 2},
                           "servers": {"atlassian": 3, "builtin": 2}},
    })
    store.write_session_analytics({
        "session_id": "s2", "user_id": u["id"], "deletion_path": "prune", "tool_use_count": 4,
        "tool_breakdown": {"tools": {"get_pr": 4}, "servers": {"github": 4}},
    })
    # A flagged record with no tool_breakdown contributes 0 to the split (and null-safe).
    store.write_session_analytics({
        "session_id": "s3", "user_id": u["id"], "deletion_path": "self_heal", "capture_incomplete": True,
    })
    t = store.session_analytics_totals(u["id"])
    assert t["tool_use_count"] == 9
    assert t["mcp_tool_calls"] == 7      # atlassian 3 + github 4
    assert t["builtin_tool_calls"] == 2  # builtin 2
    # The split reconciles to the total (no calls fall outside a server bucket).
    assert t["mcp_tool_calls"] + t["builtin_tool_calls"] == t["tool_use_count"]
