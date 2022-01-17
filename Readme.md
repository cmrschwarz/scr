# dl.py


## Examples

### Get relative links to all images on a website:
```bash 
dl.py url=google.com cx=//img/@src
```

### Get absolute links to all images on a website:
```bash 
dl.py url=google.com cx=//img/@src cl=1 cpf={link}\\n
```

### Scrolling Top Reddit Posts:
```bash 
dl.py url=old.reddit.com dx=//span[@class=\"next-button\"]/a/@href cx='//div[contains(@class,"entry")]//a[contains(@class,"title")]/text()' din=1 dmax=3
```

### Downloading pdfs from a site:
```bash 
dl.py url=https://dtc.ucsf.edu/learning-library/resource-materials/ cx=//@href cr='.*?(?P<name>[^/]*\.pdf$)' cl=1 "csf={ci:02}_{name}" v=info cimax=5
```

## Setup

### setting up geckodriver for selenium (firefox/tor)
geckodriver  (to be placed in the root directory)
can be downloaded from
https://github.com/mozilla/geckodriver/releases
