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
