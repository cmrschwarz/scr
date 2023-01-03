from scr.selenium import selenium_options


def install_selenium_driver(variant: 'selenium_options.SeleniumVariant') -> None:
    raise NotImplementedError


def update_selenium_driver(variant: 'selenium_options.SeleniumVariant') -> None:
    raise NotImplementedError
