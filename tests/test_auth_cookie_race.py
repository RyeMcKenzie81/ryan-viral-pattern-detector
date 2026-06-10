"""Regression: GSC/OAuth redirect must not bounce a logged-in user to login.

are_cookies_ready() gave up after 3 cycles (~1.5s) and returned True with the
cookie iframe still empty after a cross-domain OAuth redirect, so require_auth
showed the login form and the in-flight GSC token/property flow was lost (GSC
never reconnected). It must now WAIT for the real non-empty signal with a
generous cap on the _oauth_return path.
"""
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def auth():
    import viraltracker.ui.auth as auth_mod
    return auth_mod


def _controller(cookies):
    c = MagicMock()
    c.getAll.return_value = cookies
    return c


class TestAreCookiesReadyOAuthRace:
    def test_oauth_waits_well_past_old_3_cycle_cap(self, auth):
        # The regression: with empty cookies + _oauth_return, the OLD code gave
        # up at cycle 3. It must now keep waiting (False) through 10 cycles.
        sess = {"_oauth_return": True}
        with patch.object(auth, "st") as mst, \
             patch.object(auth, "_get_cookie_controller", return_value=_controller({})):
            mst.session_state = sess
            for cycle in range(10):
                assert auth.are_cookies_ready() is False, f"bailed to login at cycle {cycle}"

    def test_returns_true_as_soon_as_cookies_load(self, auth):
        sess = {"_oauth_return": True, "_cookies_check_count": 2}
        with patch.object(auth, "st") as mst, \
             patch.object(auth, "_get_cookie_controller", return_value=_controller({"vt_session": "abc"})):
            mst.session_state = sess
            assert auth.are_cookies_ready() is True

    def test_non_oauth_path_still_one_cycle(self, auth):
        # Job-polling guard unchanged: one wait cycle, then proceed.
        sess = {}
        with patch.object(auth, "st") as mst, \
             patch.object(auth, "_get_cookie_controller", return_value=_controller({})):
            mst.session_state = sess
            assert auth.are_cookies_ready() is False   # cycle 0 -> wait
            assert auth.are_cookies_ready() is True     # cycle 1 -> proceed

    def test_oauth_gives_up_after_generous_cap(self, auth):
        # Genuinely logged out: empty forever -> wait out the cap, then proceed
        # (to login). Cap is 12; at count==12 it gives up and clears the flag.
        sess = {"_oauth_return": True, "_cookies_check_count": 12}
        with patch.object(auth, "st") as mst, \
             patch.object(auth, "_get_cookie_controller", return_value=_controller({})):
            mst.session_state = sess
            assert auth.are_cookies_ready() is True
            assert "_oauth_return" not in sess
