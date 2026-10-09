"""Crash reports from the browser land in the log; cross-origin posts are refused."""
import logging


def test_client_error_is_logged_and_cross_origin_refused(client, caplog):
    body = {"message": "Cannot read properties of undefined (reading 'label')", "stack": "at Training\nat TabBoundary",
            "path": "/app/training", "where": "tab", "build": "/assets/index-abc.js", "ua": "test"}
    with caplog.at_level(logging.WARNING, logger="dosslap.client"):
        r = client.post("/api/client-errors", json=body, headers={"Origin": "http://testserver"})
    assert r.status_code == 204
    assert any("client-error where=tab path=/app/training" in m for m in caplog.messages)
    assert client.post("/api/client-errors", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    # oversized fields are rejected, not logged
    assert client.post("/api/client-errors", json={**body, "message": "x" * 600},
                       headers={"Origin": "http://testserver"}).status_code == 422
