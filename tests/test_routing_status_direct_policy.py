from types import SimpleNamespace

import pytest

from cato.ui.server import _build_routing_status_payload


class _Vault:
    def get(self, key: str) -> str:
        if key != "ANTHROPIC_API_KEY":
            raise AssertionError(f"routing diagnostics read unrelated credential: {key}")
        return "present-without-exposing-value"


@pytest.mark.parametrize("live_test", [True, False])
async def test_routing_status_reports_direct_policy_without_network_probe(live_test: bool) -> None:
    gateway = SimpleNamespace(
        _cfg=SimpleNamespace(
            swarmsync_enabled=True,
            swarmsync_api_url="https://must-not-be-contacted.invalid",
        ),
        _vault=_Vault(),
    )

    payload = await _build_routing_status_payload(gateway, live_test=live_test)

    assert payload["model_provider"] == "anthropic"
    assert payload["policy_source"] == "cato/model_policy.py"
    assert payload["anthropic_key_present"] is True
    assert payload["model_path_ready"] is True
    assert payload["swarmsync_in_model_path"] is False
    assert payload["swarmsync_non_model_integrations_enabled"] is True
    assert payload["network_probe_performed"] is False
    assert payload["live_test"]["skipped"] is True
    assert "present-without-exposing-value" not in repr(payload)


async def test_routing_status_fails_closed_when_gateway_is_unavailable() -> None:
    assert await _build_routing_status_payload(None) == {"error": "gateway not ready"}
