from scr.selenium import selenium_options

try:
    from selenium.webdriver.remote.webdriver import WebDriver
except ImportError:
    class WebDriver:  # type: ignore
        pass


class SeleniumContext:
    variant: 'selenium_options.SeleniumVariant'
    driver: 'WebDriver'

    def __init__(self, variant: 'selenium_options.SeleniumVariant') -> None:
        self.variant = variant

    def destroy(self) -> None:
        raise NotImplementedError
