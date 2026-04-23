"""Tests for the `Plugin.auth()` contribution hook (FMCP-24).

Semantic rule: FastMCP's auth slot is singular. `auth=` + every plugin's
`auth()` return are collected; at most one `AuthProvider` may be active.
Multiple sources raise `PluginError` — no automatic `MultiAuth` wrapping.
Users who want multi-source auth build `MultiAuth` explicitly.
"""

from __future__ import annotations

import contextlib

import pytest

from fastmcp import FastMCP
from fastmcp.server.auth.auth import AuthProvider, TokenVerifier
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from fastmcp.server.plugins.base import Plugin, PluginError, PluginMeta


def _verifier(token: str = "t") -> TokenVerifier:
    return StaticTokenVerifier(tokens={token: {"client_id": "c", "scopes": []}})


class _FakeServerAuth(AuthProvider):
    """Minimal non-TokenVerifier AuthProvider — stands in for an OAuth
    server in tests without needing a real issuer URL."""

    def __init__(self, base_url: str = "https://example.com") -> None:
        super().__init__(base_url=base_url)

    async def verify_token(self, token):  # type: ignore[override]
        return None


async def _enter_lifecycle(mcp: FastMCP) -> None:
    """Run the plugin contribution pipeline manually without launching a server."""
    async with contextlib.AsyncExitStack() as stack:
        await mcp._enter_plugin_contexts(stack)


class TestDefaultHook:
    def test_plugin_auth_defaults_to_empty_list(self):
        class P(Plugin):
            meta = PluginMeta(name="p")

        assert P().auth() == []


class TestSingleSource:
    async def test_lone_plugin_contribution_becomes_self_auth(self):
        """One plugin contributing one AuthProvider, no user `auth=` → that
        provider is installed directly as `self.auth`. No wrapping."""
        v = _verifier()

        class P(Plugin):
            meta = PluginMeta(name="p")

            def auth(self) -> list[AuthProvider]:
                return [v]

        mcp = FastMCP("t", plugins=[P()])
        await _enter_lifecycle(mcp)
        assert mcp.auth is v

    async def test_user_declared_alone_untouched(self):
        """No plugin contributing auth → `self.auth` is exactly the user
        value, no processing."""
        user_v = _verifier()
        mcp = FastMCP("t", auth=user_v)
        await _enter_lifecycle(mcp)
        assert mcp.auth is user_v

    async def test_no_sources_leaves_auth_none(self):
        mcp = FastMCP("t")
        await _enter_lifecycle(mcp)
        assert mcp.auth is None


class TestMultipleSourcesRejected:
    """FastMCP's auth slot is singular. Multiple contributors raise."""

    async def test_two_plugin_verifiers_raises(self):
        v1, v2 = _verifier("one"), _verifier("two")

        class P1(Plugin):
            meta = PluginMeta(name="p1")

            def auth(self) -> list[AuthProvider]:
                return [v1]

        class P2(Plugin):
            meta = PluginMeta(name="p2")

            def auth(self) -> list[AuthProvider]:
                return [v2]

        with pytest.raises(PluginError, match="Multiple auth sources"):
            FastMCP("t", plugins=[P1(), P2()])

    async def test_user_plus_plugin_raises(self):
        """User-declared `auth=` + any plugin contribution is ambiguous —
        framework doesn't silently pick a winner."""
        user_v, plugin_v = _verifier("u"), _verifier("p")

        class P(Plugin):
            meta = PluginMeta(name="p")

            def auth(self) -> list[AuthProvider]:
                return [plugin_v]

        with pytest.raises(PluginError, match="Multiple auth sources"):
            FastMCP("t", auth=user_v, plugins=[P()])

    async def test_two_server_contributions_raises(self):
        """Also covers the server-server case (historical multiauth reason)."""
        s1 = _FakeServerAuth("https://a.example")
        s2 = _FakeServerAuth("https://b.example")

        class P1(Plugin):
            meta = PluginMeta(name="p1")

            def auth(self) -> list[AuthProvider]:
                return [s1]

        class P2(Plugin):
            meta = PluginMeta(name="p2")

            def auth(self) -> list[AuthProvider]:
                return [s2]

        with pytest.raises(PluginError, match="Multiple auth sources"):
            FastMCP("t", plugins=[P1(), P2()])

    async def test_error_names_every_source(self):
        """Operator needs to know which sources conflict so they can
        disable auth on all but one."""
        v1, v2 = _verifier("a"), _verifier("b")

        class Alpha(Plugin):
            meta = PluginMeta(name="alpha")

            def auth(self) -> list[AuthProvider]:
                return [v1]

        class Beta(Plugin):
            meta = PluginMeta(name="beta")

            def auth(self) -> list[AuthProvider]:
                return [v2]

        with pytest.raises(PluginError) as exc_info:
            FastMCP("t", plugins=[Alpha(), Beta()])

        msg = str(exc_info.value)
        assert "'alpha'" in msg
        assert "'beta'" in msg


class TestRebuildOnEphemeralTeardown:
    async def test_ephemeral_plugin_auth_removed_on_teardown(self):
        """Ephemeral (loader-added) plugins' auth contributions must be
        stripped from `self.auth` when the plugin is torn down — the
        resolver rebuilds from scratch to avoid bespoke per-plugin
        accounting in the auth slot."""
        ephemeral_v = _verifier("temp")

        # Start with NO permanent auth so the ephemeral plugin has a
        # conflict-free slot to contribute into.
        mcp = FastMCP("t")
        assert mcp.auth is None

        class Ephemeral(Plugin):
            meta = PluginMeta(name="temp")

            def auth(self) -> list[AuthProvider]:
                return [ephemeral_v]

        async with contextlib.AsyncExitStack() as stack:
            await mcp._enter_plugin_contexts(stack)
            assert mcp.auth is None

            # Simulate a loader adding a plugin during lifespan.
            mcp._in_plugin_setup_pass = True
            try:
                mcp.add_plugin(Ephemeral())
            finally:
                mcp._in_plugin_setup_pass = False
            await mcp._enter_plugin_contexts(stack)
            assert mcp.auth is ephemeral_v

        # After stack exit ephemeral teardown fires and auth rebuilds.
        assert mcp.auth is None


class TestEagerComposition:
    def test_self_auth_is_set_before_lifespan(self):
        """HTTP/SSE transports snapshot `self.auth` when they build the
        Starlette app, which happens before lifespan entry. Plugin auth
        must therefore be composed at `add_plugin` time, not just during
        lifespan. Without this, HTTP routes would come up without the
        plugin-contributed auth wired into `RequireAuthMiddleware`."""
        v = _verifier()

        class P(Plugin):
            meta = PluginMeta(name="p")

            def auth(self) -> list[AuthProvider]:
                return [v]

        mcp = FastMCP("t", plugins=[P()])
        # No lifespan entered yet — construction only.
        assert mcp.auth is v

    def test_add_plugin_installs_auth(self):
        """Plugin added after construction (outside a loader context)
        should install its auth eagerly so HTTP transports see it."""
        v = _verifier()
        mcp = FastMCP("t")
        assert mcp.auth is None

        class P(Plugin):
            meta = PluginMeta(name="p")

            def auth(self) -> list[AuthProvider]:
                return [v]

        mcp.add_plugin(P())
        assert mcp.auth is v


class TestAddPluginAtomicity:
    def test_rejected_plugin_not_attached(self):
        """A plugin whose auth contribution would trip the 'Multiple auth
        sources' guard must be fully rolled back: not appended to
        `self.plugins`, no routes attached, no stale
        `_plugin_contributions` records. Otherwise catching the error
        can't recover — subsequent rebuilds would still include the
        rejected plugin."""
        v1 = _verifier("one")

        class P1(Plugin):
            meta = PluginMeta(name="p1")

            def auth(self) -> list[AuthProvider]:
                return [v1]

        class P2(Plugin):
            meta = PluginMeta(name="p2")

            def __init__(self) -> None:
                super().__init__()
                self._v = _verifier("two")

            def auth(self) -> list[AuthProvider]:
                return [self._v]

        p1 = P1()
        mcp = FastMCP("t", plugins=[p1])
        assert mcp.plugins == [p1]
        assert mcp.auth is v1

        p2 = P2()
        with pytest.raises(PluginError, match="Multiple auth sources"):
            mcp.add_plugin(p2)

        assert mcp.plugins == [p1]
        assert mcp.auth is v1
        assert id(p2) not in mcp._plugin_contributions


class TestDuplicateInstanceDedup:
    def test_same_instance_registered_twice_contributes_once(self):
        """Registering the same plugin instance twice is explicitly
        supported. Auth contributions must be deduped by instance id —
        otherwise a single auth-contributing instance would falsely trip
        the 'Multiple auth sources' guard."""

        class Contrib(Plugin):
            meta = PluginMeta(name="s")

            def __init__(self) -> None:
                super().__init__()
                self._v = _verifier()

            def auth(self) -> list[AuthProvider]:
                return [self._v]

        p = Contrib()
        # Must not raise even though `p` is in `self.plugins` twice.
        mcp = FastMCP("t", plugins=[p, p])
        assert mcp.auth is p._v
