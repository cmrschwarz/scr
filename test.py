#!/usr/bin/env python3
from tbselenium.tbdriver import TorBrowserDriver
import os

import lxml.html
from io import StringIO

tor_path = "/opt/tor"

# use bundled gecko driver from same directory
geckodriver_dir = os.path.dirname(os.path.abspath(__file__))

# make geckodriver available in PATH
os.environ["PATH"] += ":"  + geckodriver_dir


d = TorBrowserDriver(tor_path, tbb_logfile_path=os.devnull)

from selenium.webdriver.support import expected_conditions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions

site ="http://stackoverflow.com"
site_xpath = '/html/body/header/div/ol[1]/li[1]/a'
d.get(site)
WebDriverWait(d, 10).until(expected_conditions.presence_of_element_located((By.XPATH,site_xpath)))

doc = lxml.html.parse(StringIO(d.page_source))

elements = doc.xpath(site_xpath)

for e in elements:
    print(lxml.html.tostring(e))

accept_next_alert = True

d.save_screenshot("screenshot.png")
d.quit()


