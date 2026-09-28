from app.tasks import BackgroundQueue


def test_run_pending_coalesces_to_latest_payload():
    calls = []
    q = BackgroundQueue(lambda key, payload: calls.append((key, payload)))
    q.submit("c@main", 1)
    q.submit("c@main", 2)
    assert q.run_pending() == 1
    assert calls == [("c@main", 2)]


def test_handler_failure_is_swallowed_and_queue_survives():
    calls = []

    def handler(key, payload):
        calls.append(payload)
        if payload == 1:
            raise RuntimeError("boom")

    q = BackgroundQueue(handler)
    q.submit("k", 1)
    assert q.run_pending() == 1
    q.submit("k", 2)
    q.run_pending()
    assert calls == [1, 2]


def test_flush_waits_for_worker_to_finish():
    done = []
    q = BackgroundQueue(lambda key, payload: done.append(payload))
    q.start()
    q.submit("k", 7)
    assert q.flush(timeout=2.0) is True
    assert done == [7]
    q.stop()


def test_stop_ignores_later_submits():
    calls = []
    q = BackgroundQueue(lambda key, payload: calls.append(payload))
    q.start()
    q.stop()
    q.submit("k", 1)
    q.run_pending()
    assert calls == []
