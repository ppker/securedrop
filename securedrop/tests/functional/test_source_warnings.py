import os
import shutil

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from tests.functional.app_navigators.source_app_nav import SourceAppNavigator
from tests.functional.web_drivers import _FIREFOX_PATH


@pytest.fixture
def tor_browser_android_web_driver(sd_servers):
    # Create new profile and driver with the Tor Browser for Android user agent
    tba_user_agent = "Mozilla/5.0 (Android 10; Mobile; rv:115.0) Gecko/115.0 Firefox/115.0"
    f_profile_path2 = "/tmp/testprofile2"
    if os.path.exists(f_profile_path2):
        shutil.rmtree(f_profile_path2)
    os.mkdir(f_profile_path2)
    profile = webdriver.FirefoxProfile(f_profile_path2)
    profile.set_preference("general.useragent.override", tba_user_agent)

    tba_options = webdriver.FirefoxOptions()
    tba_options.binary_location = _FIREFOX_PATH
    tba_options.profile = profile

    if sd_servers.journalist_app_base_url.find(".onion") != -1:
        # set FF preference to socks proxy in Tor Browser
        profile.set_preference("network.proxy.type", 1)
        profile.set_preference("network.proxy.socks", "127.0.0.1")
        profile.set_preference("network.proxy.socks_port", 9150)
        profile.set_preference("network.proxy.socks_version", 5)
        profile.set_preference("network.proxy.socks_remote_dns", True)
        profile.set_preference("network.dns.blockDotOnion", False)
    profile.update_preferences()
    tba_web_driver = webdriver.Firefox(options=tba_options)

    # Set a null locale so this driver behaves the same as the others
    tba_web_driver.locale = None  # type: ignore[attr-defined]

    try:
        driver_user_agent = tba_web_driver.execute_script("return navigator.userAgent")
        assert driver_user_agent == tba_user_agent
        yield tba_web_driver
    finally:
        tba_web_driver.quit()


class TestSourceAppBrowserWarnings:
    def test_warning_appears_if_tor_browser_not_in_use(self, sd_servers, firefox_web_driver):
        # Given a user
        navigator = SourceAppNavigator(
            source_app_base_url=sd_servers.source_app_base_url,
            # Who is using Firefox instead of the tor browser
            web_driver=firefox_web_driver,
        )

        # When they access the source app's home page
        navigator.source_visits_source_homepage()

        # Then they see a warning
        warning_banner = navigator.driver.find_element(By.ID, "browser-tb")
        assert warning_banner.is_displayed()
        if navigator.accept_languages in [None, "en_US"]:
            assert "It is recommended to use Tor Browser" in warning_banner.text

        # And they are able to dismiss the warning
        warning_dismiss_button = navigator.driver.find_element(By.ID, "browser-tb-close")
        warning_dismiss_button.click()

        def warning_banner_is_hidden():
            assert warning_banner.is_displayed() is False

        navigator.nav_helper.wait_for(warning_banner_is_hidden)

    def test_warning_appears_if_tor_browser_android_is_used(
        self, sd_servers, tor_browser_android_web_driver
    ):
        # Given a user
        navigator = SourceAppNavigator(
            source_app_base_url=sd_servers.source_app_base_url,
            # Who is using Tor Browser for Android instead of the desktop Tor Browser
            web_driver=tor_browser_android_web_driver,
        )

        # When they access the source app's home page
        navigator.source_visits_source_homepage()

        # Then they see a warning
        warning_banner = navigator.driver.find_element(By.ID, "browser-android")
        assert warning_banner.is_displayed()
        if navigator.accept_languages in [None, "en_US"]:
            assert "use the desktop version of Tor Browser" in warning_banner.text

        # And they are able to dismiss the warning
        warning_dismiss_button = navigator.driver.find_element(By.ID, "browser-android-close")
        warning_dismiss_button.click()

        def warning_banner_is_hidden():
            assert warning_banner.is_displayed() is False

        navigator.nav_helper.wait_for(warning_banner_is_hidden)

    def test_warning_high_security(self, sd_servers, tor_browser_web_driver):
        # Given a user
        navigator = SourceAppNavigator(
            source_app_base_url=sd_servers.source_app_base_url,
            # Who is using the Tor browser
            web_driver=tor_browser_web_driver,
        )

        # When they access the source app's home page
        navigator.source_visits_source_homepage()

        # Then they see a warning
        banner = navigator.driver.find_element(By.ID, "browser-security-level")
        assert banner.is_displayed()
        if navigator.accept_languages in [None, "en_US"]:
            assert "Security Level is too low" in banner.text
