"""Offline tests for the GKE side of the Home Depot transport (homedepot/fetch.py)
over the browser box: the gateway POST and its operation headers, the egress
(every call on the HOME pages while Akamai accepts the home egress, fallback
exits only while it is skipped for HOMEDEPOT_DIRECT_SKIP, a dropped page
retried on the same egress), the request budget, the box being unavailable,
and the gateway's own error mapping. browser_client.fetch_any is stubbed by
a fake box that picks the first candidate not marked busy; no box, no
Chrome, no network.

    python -m pytest homedepot/test_fetch.py -q
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_client  # noqa: E402
import config  # noqa: E402
from browser_client import BoxRefused, BoxUnavailable  # noqa: E402
from homedepot import fetch  # noqa: E402
from homedepot.fetch import (HomeDepotBadRequest, HomeDepotBlocked, HomeDepotNotFound,  # noqa: E402
                             HomeDepotUpstreamError)
from scraper_utils.testing import hosted_only

def _warm_refused():
    """A fresh page Akamai refused during its warm-up: the verdict on the egress."""
    return BoxRefused("homedepot/fetch: 502 homedepot: probe call refused (HTTP 206); Akamai rejects this egress")


def _page_dropped():
    """A parked page Akamai refused mid-call: the box closed that page."""
    return BoxRefused("homedepot/fetch: 502 homedepot: Akamai refused the request (HTTP 206); page dropped")


HOME = [(None, None), (None, "page-2")]
EXITS = ["http://u:p@fallback:20001", "http://u:p@fallback:20002"]


def _ok(root, value):
    return 200, json.dumps({"data": {root: value}})


class _Log(list):
    """The call log, carrying the `busy` set that steers the fake box's pick."""
    busy = None


@pytest.fixture
def box(monkeypatch):
    """A scripted box: `answers` is a list consumed per call, each a
    (status, body) pair or an exception the box raises (a BoxRefused is
    raised on the candidate picked); `log` records the call kwargs, the
    candidates offered and the exit picked; `busy` (a set of candidate
    indexes) steers which candidate the fake box picks: the first one not
    busy. The home egress is direct (None); fallback exits are minted in
    order fallback:20001, 20002, ..."""
    log = _Log()
    answers = []
    minted = []
    busy = set()

    def box_fetch_any(site, candidates, **kw):
        index = next(i for i in range(len(candidates)) if i not in busy)
        proxy = candidates[index][0]
        log.append(dict(kw, site=site, proxy=proxy, picked=candidates[index], candidates=list(candidates)))
        answer = answers.pop(0) if answers else _ok("searchModel", {"products": []})
        if isinstance(answer, Exception):
            if isinstance(answer, (BoxRefused, BoxUnavailable)):
                answer.candidate = index
                answer.proxy = proxy
            raise answer
        return index, {"status": answer[0], "headers": {}, "body": answer[1], "final_url": kw.get("url")}
    monkeypatch.setattr(browser_client, "fetch_any", box_fetch_any)
    monkeypatch.setattr(config, "homedepot_proxy", lambda: None)
    monkeypatch.setattr(config, "homedepot_fallback_proxy",
                        lambda: (minted.append(f"http://u:p@fallback:{20000 + len(minted) + 1}"), minted[-1])[1])
    monkeypatch.setattr(config, "HOMEDEPOT_FALLBACK_PROXY_COUNTRY", "us")
    monkeypatch.setattr(config, "HOMEDEPOT_DIRECT_SKIP", 600)
    monkeypatch.setattr(config, "RETRY_BACKOFF", 0)
    monkeypatch.setattr(config, "BROWSER_BURST_FACTOR", 4)     # never applies to Home Depot
    monkeypatch.setattr(config, "HOMEDEPOT_BROWSER_SLOTS", 2)
    # fresh module state per test
    fetch._FALLBACK.reset()
    monkeypatch.setattr(fetch, "_home", fetch._UNSET)
    monkeypatch.setattr(fetch, "_home_skip_until", 0.0)
    log.busy = busy
    return log, answers, minted


def _proxies(log):
    return [e.get("proxy") for e in log]


@hosted_only
def test_gateway_post_goes_to_the_box_with_the_operation_headers(box):
    log, answers, _ = box
    answers.append(_ok("searchModel", {"products": [1]}))
    out = fetch.graphql("searchModel", "query searchModel { x }", {"keyword": "drill"}, root="searchModel")
    assert out == {"products": [1]}
    (call,) = log
    assert call["site"] == "homedepot"
    assert call["url"] == fetch.GATEWAY + "?opname=searchModel"
    assert call["method"] == "POST"
    assert call["headers"]["x-experience-name"] == "search-desktop" and call["headers"]["x-current-url"] == "/s/"
    assert call["headers"]["content-type"] == "application/json" and call["headers"]["x-hd-dc"] == "origin"
    assert json.loads(call["body"]) == {"operationName": "searchModel", "variables": {"keyword": "drill"},
                                        "query": "query searchModel { x }"}
    assert call["proxy"] is None                               # the home egress: the box's own IP
    assert 0 < call["timeout"] <= fetch.REQUEST_BUDGET          # the box call never outlives the request
    # other operations carry their own experience pair; unknown ones the generic one
    answers.extend([_ok("storeSearch", {}), _ok("data", {})])
    fetch.graphql("storeSearch", "q", {}, root="storeSearch")
    fetch.graphql("somethingNew", "q", {})
    assert (log[1]["headers"]["x-experience-name"], log[1]["headers"]["x-current-url"]) == ("store-locator", "/l/store-locator")
    assert (log[2]["headers"]["x-experience-name"], log[2]["headers"]["x-current-url"]) == ("general-merchandise", "/")


@hosted_only
def test_every_call_is_offered_the_home_pages_only_and_no_exit_is_minted(box):
    log, _, minted = box
    for _ in range(3):
        fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert [e["candidates"] for e in log] == [HOME] * 3        # the share, never share x burst factor
    assert _proxies(log) == [None, None, None]
    assert minted == []                                        # a residential exit costs a 12-25 s warm-up


@hosted_only
def test_concurrent_calls_spread_over_the_home_pages_not_onto_exits(box):
    # 2026-11-12: the second concurrent call used to be handed a fallback exit
    # (a cold browser Akamai refuses more often than not).
    log, _, minted = box
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    log.busy.add(0)                                            # the first home page is serving another call
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    log.busy.clear()
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert [e["picked"] for e in log] == [(None, None), (None, "page-2"), (None, None)]
    assert minted == []


@hosted_only
def test_the_number_of_home_pages_is_the_share(box, monkeypatch):
    log, _, _ = box
    monkeypatch.setattr(config, "HOMEDEPOT_BROWSER_SLOTS", 3)
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert log[-1]["candidates"] == [(None, None), (None, "page-2"), (None, "page-3")]
    monkeypatch.setattr(config, "HOMEDEPOT_BROWSER_SLOTS", 1)
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert log[-1]["candidates"] == [(None, None)]


@hosted_only
def test_a_refused_fresh_home_page_hands_over_to_the_fallback_exits_for_the_skip(box, monkeypatch):
    log, answers, minted = box
    answers.extend([_warm_refused(), _ok("searchModel", {"ok": 1})])
    before = time.monotonic()
    assert fetch.graphql("searchModel", "q", {}, root="searchModel") == {"ok": 1}
    assert _proxies(log) == [None, EXITS[0]]
    assert [c[0] for c in log[-1]["candidates"]] == EXITS       # the share again: two exits, home not among them
    assert before + 600 <= fetch._home_skip_until <= time.monotonic() + 600
    # the exits are sticky while home is skipped
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert _proxies(log)[-1] == EXITS[0] and minted == EXITS
    # once the skip has run out home is proven again, on the same pages
    monkeypatch.setattr(fetch, "_home_skip_until", time.monotonic() - 1)
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert log[-1]["candidates"] == HOME and minted == EXITS


@hosted_only
def test_a_refused_fallback_exit_is_replaced_and_the_skip_is_left_alone(box, monkeypatch):
    log, answers, minted = box
    until = time.monotonic() + 300
    monkeypatch.setattr(fetch, "_home_skip_until", until)
    answers.extend([_warm_refused(), _ok("searchModel", {"ok": 2})])
    assert fetch.graphql("searchModel", "q", {}, root="searchModel") == {"ok": 2}
    assert _proxies(log) == [EXITS[0], "http://u:p@fallback:20003"]
    assert [c[0] for c in log[-1]["candidates"]] == ["http://u:p@fallback:20003", EXITS[1]]
    assert fetch._home_skip_until == until


@hosted_only
def test_a_dropped_home_page_is_retried_on_home(box):
    # A parked page goes stale: the box closes it and the retry gets a fresh
    # page of the same egress. That says nothing about the IP.
    log, answers, minted = box
    answers.extend([_page_dropped(), _page_dropped(), _ok("searchModel", {"ok": 1})])
    assert fetch.graphql("searchModel", "q", {}, root="searchModel") == {"ok": 1}
    assert [e["candidates"] for e in log] == [HOME] * 3
    assert fetch._home_skip_until == 0.0 and minted == []


@hosted_only
def test_more_drops_than_parked_pages_is_the_verdict_on_home(box):
    log, answers, minted = box
    answers.extend([_page_dropped()] * 3 + [_ok("searchModel", {"ok": 1})])
    assert fetch.graphql("searchModel", "q", {}, root="searchModel") == {"ok": 1}
    assert _proxies(log) == [None, None, None, EXITS[0]]        # the third drop was a fresh page: the egress
    assert fetch._home_skip_until > 0


@hosted_only
def test_a_wedged_page_never_skips_home(box):
    log, answers, minted = box
    wedged = lambda: BoxRefused("homedepot/fetch: 502 homedepot: in-page fetch failed: Target closed")  # noqa: E731
    answers.extend([wedged() for _ in range(fetch.MAX_REFUSALS)])
    with pytest.raises(HomeDepotBlocked):
        fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert len(log) == fetch.MAX_REFUSALS and _proxies(log) == [None] * fetch.MAX_REFUSALS
    assert fetch._home_skip_until == 0.0 and minted == []


@hosted_only
def test_without_fallback_exits_home_is_never_skipped(box, monkeypatch):
    log, answers, minted = box
    monkeypatch.setattr(config, "HOMEDEPOT_FALLBACK_PROXY_COUNTRY", None)
    answers.extend([_warm_refused(), _ok("searchModel", {"ok": 1})])
    assert fetch.graphql("searchModel", "q", {}, root="searchModel") == {"ok": 1}
    assert [e["candidates"] for e in log] == [HOME] * 2 and minted == []


@hosted_only
def test_a_configured_home_exit_is_one_sticky_url_replaced_after_a_refusal(box, monkeypatch):
    log, answers, _ = box
    made = []
    monkeypatch.setattr(config, "homedepot_proxy",
                        lambda: (made.append(f"http://u:p@home:{30000 + len(made) + 1}"), made[-1])[1])
    for _ in range(2):
        fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert made == ["http://u:p@home:30001"]                    # minted once: the box keys the page by this URL
    assert log[-1]["candidates"] == [("http://u:p@home:30001", None), ("http://u:p@home:30001", "p30001-page-2")]
    answers.append(_warm_refused())
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    monkeypatch.setattr(fetch, "_home_skip_until", 0.0)
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    # the second page moves with the exit: the box keys it by its session id
    # alone, so the old id would keep serving on the refused exit
    assert log[-1]["candidates"] == [("http://u:p@home:30002", None), ("http://u:p@home:30002", "p30002-page-2")]


@hosted_only
def test_a_late_refusal_of_a_replaced_home_exit_leaves_the_new_one(box, monkeypatch):
    # Two calls fail on one home exit; the second reports after the first
    # already had it replaced: one fresh exit is burned, not two.
    log, _, _ = box
    made = []
    monkeypatch.setattr(config, "homedepot_proxy",
                        lambda: (made.append(f"http://u:p@home:{30000 + len(made) + 1}"), made[-1])[1])
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    fetch._skip_home("http://u:p@home:30001")
    monkeypatch.setattr(fetch, "_home_skip_until", 0.0)
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert made == ["http://u:p@home:30001", "http://u:p@home:30002"]
    fetch._skip_home("http://u:p@home:30001")                  # the other call's refusal of the OLD exit
    assert fetch._home_skip_until == 0.0
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert len(made) == 2 and log[-1]["candidates"][0] == ("http://u:p@home:30002", None)


@hosted_only
def test_every_egress_refused_is_blocked_within_the_refusal_cap(box):
    log, answers, _ = box
    answers.extend([_warm_refused() for _ in range(20)])
    with pytest.raises(HomeDepotBlocked, match="Akamai refused"):
        fetch.graphql("searchModel", "q", {}, root="searchModel")
    used = _proxies(log)
    assert len(used) == fetch.MAX_REFUSALS                      # until 2026-11-12: up to 10 warm-ups, 288 s
    assert used[0] is None and all(p.startswith("http://u:p@fallback:") for p in used[1:])


@hosted_only
def test_a_request_out_of_budget_stops_instead_of_trying_another_egress(box, monkeypatch):
    log, answers, _ = box
    monkeypatch.setattr(fetch, "REQUEST_BUDGET", fetch.MIN_CALL_SECONDS - 1)   # one warm-up spent it
    answers.extend([_warm_refused() for _ in range(5)])
    with pytest.raises(HomeDepotBlocked):
        fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert len(log) == 1


@hosted_only
def test_a_refusal_verdict_in_the_body_moves_the_egress_on_too(box):
    log, answers, _ = box
    answers.extend([(206, '{"data":{"Generic Errors API":null}}'), (401, ""), _ok("searchModel", {"ok": 1})])
    assert fetch.graphql("searchModel", "q", {}, root="searchModel") == {"ok": 1}
    assert _proxies(log) == [None, EXITS[0], "http://u:p@fallback:20003"]
    assert fetch._home_skip_until > 0


@hosted_only
def test_box_unavailable_is_an_upstream_error_and_keeps_the_egress(box):
    log, answers, minted = box
    answers.append(BoxUnavailable("homedepot/fetch: box unreachable"))
    with pytest.raises(HomeDepotUpstreamError, match="browser box unavailable") as info:
        fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert not isinstance(info.value, HomeDepotBlocked)
    assert len(log) == 1 and fetch._home_skip_until == 0.0 and minted == []
    fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert _proxies(log) == [None, None]


@hosted_only
def test_gateway_error_mapping(box):
    log, answers, _ = box
    answers.append((403, "forbidden"))
    with pytest.raises(HomeDepotBadRequest, match="HTTP 403"):
        fetch.graphql("searchModel", "q", {}, root="searchModel")
    answers.extend([(503, "down"), _ok("searchModel", {"ok": 1})])
    assert fetch.graphql("searchModel", "q", {}, root="searchModel") == {"ok": 1}   # 5xx retried on the same egress
    assert _proxies(log) == [None] * 3
    answers.extend([(503, "down")] * 5)
    with pytest.raises(HomeDepotUpstreamError, match="HTTP 503"):
        fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert len(log) == 3 + fetch.MAX_ATTEMPTS
    del answers[:]
    answers.append((200, "<html>"))
    with pytest.raises(HomeDepotUpstreamError, match="non-JSON"):
        fetch.graphql("searchModel", "q", {}, root="searchModel")
    answers.append((200, json.dumps({"data": {"product": None}, "errors": [{"message": "ItemId: 1 not found"}]})))
    with pytest.raises(HomeDepotNotFound, match="not found"):
        fetch.graphql("productClientOnlyProduct", "q", {}, root="product")
    answers.append((200, json.dumps({"data": None, "errors": [{"message": "invalid storeId"}]})))
    with pytest.raises(HomeDepotBadRequest, match="invalid"):
        fetch.graphql("storeSearch", "q", {}, root="storeSearch")
    answers.append((200, json.dumps({"data": None, "errors": [{"message": "ValidationError: unknown field"}]})))
    with pytest.raises(HomeDepotUpstreamError, match="rejected the document"):
        fetch.graphql("searchModel", "q", {}, root="searchModel")
    answers.append((418, "teapot"))
    with pytest.raises(HomeDepotUpstreamError, match="HTTP 418"):
        fetch.graphql("searchModel", "q", {}, root="searchModel")
    assert fetch._home_skip_until == 0.0                        # none of these is Akamai's verdict
