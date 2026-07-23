"""Store round-trip tests. Require a reachable `_test` Postgres (see conftest `db`)."""


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
