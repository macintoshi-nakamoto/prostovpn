from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app import provisioning
from app.db import SessionLocal, init_db
from app.main import app
from app.models import GB, Provisioning, Server, SubscriptionToken, UserKey, utcnow

TEMPLATE = (
    "[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n"
    "DNS = 1.1.1.1, 1.0.0.1\nMTU = 1280\nJc = 4\nJmin = 40\nJmax = 70\n"
    "S1 = 15\nS2 = 20\nH1 = 111\nH2 = 222\nH3 = 333\nH4 = 444\n"
    "\n[Peer]\nPublicKey = server-pub-key\nAllowedIPs = 0.0.0.0/0, ::/0\n"
    "Endpoint = 45.0.0.1:51820\nPersistentKeepalive = 25\n"
)


def test_with_endpoint_host_changes_only_host():
    cfg = provisioning.render_from_template(TEMPLATE, "priv", "10.8.1.5/32")
    moved = provisioning.with_endpoint_host(cfg, "9.9.9.9")
    assert "Endpoint = 9.9.9.9:51820" in moved
    assert [l for l in cfg.splitlines() if not l.startswith("Endpoint")] == [
        l for l in moved.splitlines() if not l.startswith("Endpoint")
    ]


def test_host_and_port_are_orthogonal():
    cfg = provisioning.render_from_template(TEMPLATE, "priv", "10.8.1.5/32")
    both = provisioning.with_endpoint_port(provisioning.with_endpoint_host(cfg, "9.9.9.9"), 443)
    assert "Endpoint = 9.9.9.9:443" in both


def test_ipv6_host_survives_port_rewrite():
    cfg = provisioning.render_from_template(TEMPLATE, "priv", "10.8.1.5/32").replace(
        "45.0.0.1:51820", "[2a01:4f8::1]:51820"
    )
    out = provisioning.with_endpoint_host(cfg, "[2a02::2]")
    assert "Endpoint = [2a02::2]:51820" in out


def test_with_private_key_replaces_only_interface_key():
    cfg = provisioning.render_from_template(TEMPLATE, "OLDPRIV", "10.8.1.5/32")
    out = provisioning.with_private_key(cfg, "NEWPRIV")
    assert "PrivateKey = NEWPRIV" in out
    assert "PublicKey = server-pub-key" in out
    assert provisioning.with_private_key(cfg, "") == cfg


def test_private_key_for_prefers_cipher_then_falls_back(tmp_path):
    from app import crypto

    key = UserKey(config=provisioning.render_from_template(TEMPLATE, "PLAINPRIV", "10.8.1.5/32"))
    assert provisioning.private_key_for(key) == "PLAINPRIV"
    key.private_key_enc = crypto.encrypt("CIPHERPRIV")
    assert provisioning.private_key_for(key) == "CIPHERPRIV"
    key.config = key.config.replace("PLAINPRIV", provisioning.ENCRYPTED_PLACEHOLDER)
    key.private_key_enc = None
    assert provisioning.private_key_for(key) == ""


def test_serving_config_drops_node_when_key_unresolvable():
    server = Server(name="n", host="9.9.9.9", port=51820, provisioning=Provisioning.SSH)
    cfg = provisioning.render_from_template(TEMPLATE, provisioning.ENCRYPTED_PLACEHOLDER, "10.8.1.5/32")
    key = UserKey(config=cfg, private_key_enc=None, address="10.8.1.5/32")
    assert provisioning.serving_config(server, key) is None


def test_with_endpoint_host_brackets_bare_ipv6():
    cfg = provisioning.render_from_template(TEMPLATE, "priv", "10.8.1.5/32")
    out = provisioning.with_endpoint_host(cfg, "2a01:4f8::1")
    assert "Endpoint = [2a01:4f8::1]:51820" in out


def test_serving_config_shared_is_untouched():
    server = Server(
        name="sh", host="1.2.3.4", provisioning=Provisioning.SHARED,
        shared_config="[Interface]\nPrivateKey = shared\nAddress = 10.0.0.9/32\n"
        "\n[Peer]\nPublicKey = p\nEndpoint = 5.6.7.8:51820\n",
    )
    out = provisioning.serving_config(server, None)
    assert "Endpoint = 5.6.7.8:51820" in out
    assert "1.2.3.4" not in out


@pytest.fixture
def ssh(monkeypatch):
    calls = {"add": [], "remove": []}
    monkeypatch.setattr(
        provisioning, "add_peer_over_ssh",
        lambda server, pub, addr, *, interface="awg0": calls["add"].append(
            (server.id, pub, addr, interface)
        ),
    )
    monkeypatch.setattr(
        provisioning, "remove_peer_over_ssh",
        lambda server, pub, *, interface="awg0": calls["remove"].append(
            (server.id, pub, interface)
        ),
    )
    return calls


@pytest.fixture
def client():
    init_db()
    with TestClient(app) as c:
        yield c


def _admin_headers(client):
    r = client.post("/api/admin/login", json={"login": "admin", "password": "admin"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _make_ssh_server(name: str, host: str = "45.0.0.1") -> int:
    with SessionLocal() as db:
        server = Server(
            name=name, country=name, country_code=name[:2].upper(), city="Town",
            host=host, port=51820, alt_ports="443,2408",
            provisioning=Provisioning.SSH, awg_template=TEMPLATE,
            ssh_host="127.0.0.1", ssh_user="root", ssh_key="dummy",
        )
        db.add(server)
        db.commit()
        return server.id


def _make_user(client, headers, name: str):
    created = client.post(
        "/api/admin/users",
        json={"name": name, "planCode": "3months", "trafficLimitBytes": 100 * GB},
        headers=headers,
    ).json()
    return created["user"]["id"], created["user"]["login"], created["password"]


def _login(client, login: str, password: str, device: str = "dev-1"):
    r = client.post(
        "/api/v1/login",
        json={"login": login, "password": password, "platform": "android",
              "app_version": "1.1.5", "device_id": device},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_login_returns_subscription_url(client, ssh):
    headers = _admin_headers(client)
    _make_ssh_server("nl-sub-url")
    _uid, login, password = _make_user(client, headers, "sub url")
    body = _login(client, login, password)
    assert body.get("subscription_url"), "устройству обязана прийти ссылка подписки"
    assert "/s/" in body["subscription_url"]


def test_subscription_lists_endpoints_with_priority(client, ssh):
    headers = _admin_headers(client)
    sid = _make_ssh_server("de-endpoints", host="45.0.0.9")
    _uid, login, password = _make_user(client, headers, "endpoints")
    url = _login(client, login, password)["subscription_url"]

    body = client.get(url).json()
    assert body["version"] == 1
    ours = next(s for s in body["servers"] if s["id"] == sid)
    ports = [e["port"] for e in ours["endpoints"]]
    prios = [e["priority"] for e in ours["endpoints"]]
    assert set(ports) == {51820, 443, 2408}
    assert prios == sorted(prios) == list(range(len(prios)))
    cred = ours["endpoints"][0]["credentials"]
    assert all(e["host"] == "45.0.0.9" for e in ours["endpoints"])
    assert cred["type"] == "amneziawg"
    assert "PrivateKey" in cred["config"] and provisioning.ENCRYPTED_PLACEHOLDER not in cred["config"]
    assert cred["obfuscation"]["Jc"] == 4 and cred["obfuscation"]["H1"] == 111


def test_amnezia_format_round_trips(client, ssh):
    headers = _admin_headers(client)
    _make_ssh_server("se-amnezia", host="45.0.0.5")
    _uid, login, password = _make_user(client, headers, "amnezia")
    url = _login(client, login, password)["subscription_url"]

    r = client.get(url, params={"format": "amnezia"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    links = base64.b64decode(r.text).decode().splitlines()
    assert links and all(l.startswith("vpn://") for l in links)
    parsed = provisioning.read_vpn_key(links[0])
    assert parsed["defaultContainer"] == "amnezia-awg"


def test_only_hash_is_stored(client, ssh):
    headers = _admin_headers(client)
    _make_ssh_server("nl-hash")
    _uid, login, password = _make_user(client, headers, "hash")
    url = _login(client, login, password)["subscription_url"]
    raw = url.rsplit("/s/", 1)[1]
    with SessionLocal() as db:
        rows = list(db.query(SubscriptionToken).all())
        assert rows and all(t.token_hash != raw for t in rows)


def test_invalid_token_is_404_json(client, ssh):
    r = client.get("/s/definitely-not-a-real-token")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert "detail" in r.json()


def test_rotate_kills_old_link_keeps_keys(client, ssh):
    headers = _admin_headers(client)
    sid = _make_ssh_server("nl-rotate")
    _uid, login, password = _make_user(client, headers, "rotate")
    body = _login(client, login, password)
    token_app = body["token"]
    old_url = body["subscription_url"]
    assert client.get(old_url).status_code == 200

    with SessionLocal() as db:
        before = db.query(UserKey).filter(UserKey.server_id == sid).first()
        pub_before, addr_before = before.public_key, before.address

    ssh["add"].clear()
    ssh["remove"].clear()
    r = client.post("/api/v1/subscription/rotate", headers={"Authorization": f"Bearer {token_app}"})
    assert r.status_code == 200
    new_url = r.json()["subscription_url"]

    assert new_url != old_url
    assert client.get(old_url).status_code == 404, "старая ссылка обязана умереть"
    assert client.get(new_url).status_code == 200
    with SessionLocal() as db:
        after = db.query(UserKey).filter(UserKey.server_id == sid).first()
        assert after.public_key == pub_before and after.address == addr_before
    assert ssh["add"] == [] and ssh["remove"] == []


def test_device_disconnect_revokes_subscription(client, ssh):
    from app import services

    headers = _admin_headers(client)
    _make_ssh_server("nl-disc")
    uid, login, password = _make_user(client, headers, "disc")
    url = _login(client, login, password, device="dev-disc")["subscription_url"]
    assert client.get(url).status_code == 200

    with SessionLocal() as db:
        from app.models import Session as Sess, User

        sess = db.query(Sess).filter(Sess.user_id == uid, Sess.device_id == "dev-disc").first()
        services.disconnect_device(db, sess)

    assert client.get(url).status_code == 404


def test_subscription_empty_when_no_access(client, ssh):
    headers = _admin_headers(client)
    sid = _make_ssh_server("nl-blocked")
    uid, login, password = _make_user(client, headers, "blocked")
    url = _login(client, login, password)["subscription_url"]
    assert any(s["id"] == sid for s in client.get(url).json()["servers"])

    client.post(f"/api/admin/users/{uid}/block", json={"reason": "тест"}, headers=headers)
    body = client.get(url).json()
    assert body["servers"] == []


def test_etag_304_and_cache_headers(client, ssh):
    headers = _admin_headers(client)
    sid = _make_ssh_server("nl-etag", host="45.1.1.1")
    _uid, login, password = _make_user(client, headers, "etag")
    url = _login(client, login, password)["subscription_url"]

    first = client.get(url)
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert "must-revalidate" in first.headers["cache-control"]
    assert "no-store" not in first.headers["cache-control"]

    again = client.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 304

    with SessionLocal() as db:
        db.get(Server, sid).host = "45.2.2.2"
        db.commit()
    changed = client.get(url, headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag


def test_rate_limit_caps_but_does_not_lock(client, ssh):
    headers = _admin_headers(client)
    _make_ssh_server("nl-rate")
    _uid, login, password = _make_user(client, headers, "rate")
    url = _login(client, login, password)["subscription_url"]

    statuses = [client.get(url).status_code for _ in range(61)]
    assert statuses.count(200) >= 60
    limited = client.get(url)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) <= 61


def test_ip_change_reaches_everyone_without_reissue(client, ssh):
    headers = _admin_headers(client)
    sid = _make_ssh_server("nl-move", host="45.10.0.1")
    _uid, login, password = _make_user(client, headers, "move")
    body = _login(client, login, password)
    token_app = body["token"]
    url = body["subscription_url"]

    with SessionLocal() as db:
        key = db.query(UserKey).filter(UserKey.server_id == sid).first()
        pub, addr, priv_enc = key.public_key, key.address, key.private_key_enc
        rev_before = db.get(Server, sid).endpoint_rev

    ssh["add"].clear()
    ssh["remove"].clear()
    server_row = client.get("/api/admin/servers", headers=headers).json()
    payload = next(s for s in server_row if s["id"] == sid)
    payload["host"] = "77.77.77.77"
    upd = client.put(f"/api/admin/servers/{sid}", json=payload, headers=headers)
    assert upd.status_code in (200, 204), upd.text

    assert ssh["add"] == [] and ssh["remove"] == []
    with SessionLocal() as db:
        key = db.query(UserKey).filter(UserKey.server_id == sid).first()
        assert key.public_key == pub and key.address == addr and key.private_key_enc == priv_enc
        assert db.get(Server, sid).endpoint_rev == rev_before + 1

    sub = client.get(url).json()
    ours = next(s for s in sub["servers"] if s["id"] == sid)
    assert all(e["host"] == "77.77.77.77" for e in ours["endpoints"])
    assert "77.77.77.77" in ours["endpoints"][0]["credentials"]["config"]
    assert sub["revision"] >= rev_before + 1

    legacy = client.get("/api/v1/servers", headers={"Authorization": f"Bearer {token_app}"}).json()
    ours_legacy = next(s for s in legacy["servers"] if s["id"] == sid)
    assert "77.77.77.77" in ours_legacy["config"]


def test_sticky_port_survives_in_first_endpoint(client, ssh):
    headers = _admin_headers(client)
    sid = _make_ssh_server("nl-sticky", host="45.20.0.1")
    _uid, login, password = _make_user(client, headers, "sticky")
    url = _login(client, login, password)["subscription_url"]

    with SessionLocal() as db:
        key = (
            db.query(UserKey)
            .filter(UserKey.server_id == sid, UserKey.device_id == "dev-1")
            .first()
        )
        key.endpoint_port = 2408
        key.last_handshake_at = utcnow()
        db.commit()

    ours = next(s for s in client.get(url).json()["servers"] if s["id"] == sid)
    assert ours["endpoints"][0]["port"] == 2408
    assert "45.20.0.1:2408" in ours["endpoints"][0]["credentials"]["config"]


def test_backfill_encrypts_private_key_but_keeps_config_nonempty(client, ssh):
    from app import migrations

    headers = _admin_headers(client)
    sid = _make_ssh_server("nl-enc")
    _uid, login, password = _make_user(client, headers, "enc")
    _login(client, login, password)

    with SessionLocal() as db:
        migrations.backfill(db)
    with SessionLocal() as db:
        key = db.query(UserKey).filter(UserKey.server_id == sid).first()
        assert key.private_key_enc, "приватник обязан быть зашифрован"
        assert key.config and "PrivateKey" in key.config
        assert provisioning.private_key_for(key)


def test_compromise_reissues_keys_and_kills_links(client, ssh):
    headers = _admin_headers(client)
    sid = _make_ssh_server("nl-compromise")
    uid, login, password = _make_user(client, headers, "compromise")
    body = _login(client, login, password)
    old_url = body["subscription_url"]
    assert client.get(old_url).status_code == 200
    with SessionLocal() as db:
        before = db.query(UserKey).filter(UserKey.server_id == sid, UserKey.device_id == "dev-1").first()
        pub_before = before.public_key

    r = client.post(f"/api/admin/users/{uid}/subscription/reissue", headers=headers)
    assert r.status_code == 200, r.text

    assert client.get(old_url).status_code == 404
    with SessionLocal() as db:
        after = db.query(UserKey).filter(UserKey.server_id == sid, UserKey.device_id == "dev-1").first()
        assert after.public_key and after.public_key != pub_before


def test_served_key_matches_peer_after_reissue(client, ssh):
    from app import migrations

    headers = _admin_headers(client)
    sid = _make_ssh_server("nl-match", host="45.40.0.1")
    uid, login, password = _make_user(client, headers, "match")
    url = _login(client, login, password)["subscription_url"]
    with SessionLocal() as db:
        migrations.backfill(db)

    def served_private():
        ours = next(s for s in client.get(url).json()["servers"] if s["id"] == sid)
        return ours["endpoints"][0]["credentials"]["private_key"]

    with SessionLocal() as db:
        pub0 = db.query(UserKey).filter(UserKey.server_id == sid, UserKey.device_id == "dev-1").first().public_key
    assert provisioning.public_key_of(served_private()) == pub0

    r = client.post(f"/api/admin/users/{uid}/subscription/reissue", headers=headers)
    assert r.status_code == 200
    with SessionLocal() as db:
        key = db.query(UserKey).filter(UserKey.server_id == sid, UserKey.device_id == "dev-1").first()
        pub1 = key.public_key
        assert pub1 != pub0
        from app import crypto

        assert provisioning.public_key_of(crypto.decrypt(key.private_key_enc)) == pub1

    new_url = _login(client, login, password)["subscription_url"]
    ours = next(s for s in client.get(new_url).json()["servers"] if s["id"] == sid)
    assert provisioning.public_key_of(ours["endpoints"][0]["credentials"]["private_key"]) == pub1


def test_serving_uses_cipher_after_plaintext_stripped(client, ssh):
    from app import migrations

    headers = _admin_headers(client)
    sid = _make_ssh_server("nl-stripped", host="45.30.0.1")
    _uid, login, password = _make_user(client, headers, "stripped")
    url = _login(client, login, password)["subscription_url"]

    with SessionLocal() as db:
        migrations.backfill(db)
    with SessionLocal() as db:
        key = db.query(UserKey).filter(UserKey.server_id == sid, UserKey.device_id == "dev-1").first()
        real_priv = provisioning.private_key_for(key)
        key.config = provisioning.with_private_key(key.config, provisioning.ENCRYPTED_PLACEHOLDER)
        db.commit()
        assert provisioning.ENCRYPTED_PLACEHOLDER in key.config

    ours = next(s for s in client.get(url).json()["servers"] if s["id"] == sid)
    served = ours["endpoints"][0]["credentials"]["config"]
    assert f"PrivateKey = {real_priv}" in served
    assert provisioning.ENCRYPTED_PLACEHOLDER not in served


def test_reuse_guard_survives_encryption(client, ssh):
    from app import migrations, services

    headers = _admin_headers(client)
    sid = _make_ssh_server("nl-reuse")
    uid, login, password = _make_user(client, headers, "reuse")
    _login(client, login, password)
    with SessionLocal() as db:
        migrations.backfill(db)

    ssh["add"].clear()
    ssh["remove"].clear()
    with SessionLocal() as db:
        from app.models import User

        user = db.get(User, uid)
        services.ensure_keys(db, user)
    assert all(c[0] != sid for c in ssh["add"])
    assert ssh["remove"] == []
