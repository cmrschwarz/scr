# screp

Commandline utility for webpage scraping written in Python.

The name "screp" comes from merging "scrape" and "grep".

## Examples

### Get text from all paragraphs on a site:
```bash 
screp url=google.com cx='//p/text()'
```

### Get absolute links to all images on a website:
```bash 
screp url=google.com cx='//img/@src' cl=1 cpf='{link}\n'
```

### Scroll through top reddit posts:
```bash 
screp url=old.reddit.com dx='//span[@class="next-button"]/a/@href' cx='//div[contains(@class,"entry")]//a[contains(@class,"title")]/text()' din=1 dimax=3
```

### Downloading pdfs from a site (interactively):
```bash 
screp url=https://dtc.ucsf.edu/learning-library/resource-materials/ cx=//@href cr='.*?(?P<name>[^/]*\.pdf$)' cl=1 csf='{ci:02}_{name}' csin=1 v=info cimax=5 
```

## Setup

### Python packages

The required non standard pip packages can be installed using:
 ```bash
 pip3 install tbselenium lxml selenium random_user_agent readline
 ```

### Setting up Selenium

To use the selenium feature,
you need to have a driver for the selected browser installed.

#### Setting up geckodriver for selenium (firefox/tor)

The geckodriver executable (to be placed in the root directory next to screp)
can be downloaded from
https://github.com/mozilla/geckodriver/releases
 
#### Setting up chromium driver for selenium (chrome)

Simply install the `chromium-driver` (debian +deriviates),
`chromium-chromedriver` (alpine) or `chromedriver` (arch aur)
package for your distribution. 
(A pullrequest with instructions for windows here would be appreciated.)

## Options


  
