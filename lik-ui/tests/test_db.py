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
