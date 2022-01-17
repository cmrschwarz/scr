# dl.py


## Examples

### Get text from all paragraphs on a site:
```bash 
dl.py url=google.com cx='//p/text()'
```

### Get absolute links to all images on a website:
```bash 
dl.py url=google.com cx='//img/@src' cl=1 cpf='{link}\n'
```

### Scroll through top reddit posts:
```bash 
dl.py url=old.reddit.com dx='//span[@class="next-button"]/a/@href' cx='//div[contains(@class,"entry")]//a[contains(@class,"title")]/text()' din=1 dimax=3
```

### Downloading pdfs from a site (interactively):
```bash 
dl.py url=https://dtc.ucsf.edu/learning-library/resource-materials/ cx=//@href cr='.*?(?P<name>[^/]*\.pdf$)' cl=1 csf='{ci:02}_{name}' csin=1 v=info cimax=5 
```

## Setup

### Setting up geckodriver for selenium (firefox/tor)

The geckodriver executable (to be placed in the root directory)
can be downloaded from
https://github.com/mozilla/geckodriver/releases
 
### Python packages

The required non standard pip packages can be installed using:
 ```bash
 pip3 install tbselenium lxml readline selenium random_user_agent
 ```
  
