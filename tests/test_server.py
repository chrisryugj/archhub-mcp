"""server.py — 키 만료 D-day 계산 단위테스트 (외부 API 비의존).

server import 시 ArchHubClient는 메타(meta_dict)만 쓰므로 네트워크 없이 가능하다.
"""

import datetime

from archhub import server


def test_key_expiry_none_when_unset(monkeypatch):
    monkeypatch.setattr(server, "KEY_EXPIRES", "")
    assert server._key_expiry_days() is None


def test_key_expiry_none_on_bad_format(monkeypatch):
    monkeypatch.setattr(server, "KEY_EXPIRES", "2028/06/02")  # ISO 아님
    assert server._key_expiry_days() is None


def test_key_expiry_future_days(monkeypatch):
    future = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
    monkeypatch.setattr(server, "KEY_EXPIRES", future)
    assert server._key_expiry_days() == 10


def test_key_expiry_past_is_negative(monkeypatch):
    past = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
    monkeypatch.setattr(server, "KEY_EXPIRES", past)
    assert server._key_expiry_days() == -5
