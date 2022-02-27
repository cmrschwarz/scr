# screp

Commandline utility for webpage scraping written in Python.

The name "screp" comes from merging "scrape" and "grep".

## Examples

### Get text from all paragraphs on a site:
```bash 
screp url=google.com cx='//p/text()'
```

### Get the latest 5 Video Titles from a youtube channel
```bash 
screp url="https://www.youtube.com/feeds/videos.xml?channel_id=UCmtyQOKKmrMVaKuRXz02jbQ" cx="//feed/entry[position()<=5]/title/text()"
```

### Get absolute links to all images on a website:
```bash 
screp url=google.com cx='//img/@src' cl cpf='{link}\n'
```

### Scroll through top reddit posts:
```bash 
screp url=old.reddit.com dx='//span[@class="next-button"]/a/@href' cx='//div[contains(@class,"entry")]//a[contains(@class,"title")]/text()' din dimax=3
```

### Downloading first 3 pdfs from a site:
```bash 
screp url=https://dtc.ucsf.edu/learning-library/resource-materials/ cx=//@href cr='.*?(?P<name>[^/]*\.pdf$)' cl csf='{ci:02}_{name}' v=info cimax=3 
```

### Downloading first 3 pdfs and gifs from a site interactively:
```bash 
screp url=https://dtc.ucsf.edu/learning-library/resource-materials/ cx=//@href cr1='.*?(?P<name>[^/]*\.pdf$)' cr2='.*?(?P<name>[^/]*\.gif$)' csf='{ci:02}_{name}' v=info cin cl cimax=3   
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
```
screp [OPTIONS]
    Extract content from urls or files by specifying content matching chains
    (xpath -> regex -> python format string).

    Content to Write out:
        cx=<xpath>           xpath for content matching
        cr=<regex>           regex for content matching
        cf=<format string>   content format string (args: <cr capture groups>, content, di, ci)
        cm=<bool>            allow multiple content matches in one document instead of picking the first (defaults to true)
        cimin=<number>       initial content index, each successful match gets one index
        cimax=<number>       max content index, matching stops here
        cicont=<bool>        don't reset the content index for each document
        cpf=<format string>  print the result of this format string for each content, empty to disable
                             defaults to "{content}\n" if cpf and csf are both unspecified
                             (args: content, label, content_enc, encoding, document, escape, [di], [ci], [link], <lr capture groups>, <cr capture groups>)
        csf=<format string>  save content to file at the path resulting from the format string, empty to enable
                             (args: content, label, content_enc, encoding, document, escape, [di], [ci], [link], <lr capture groups>, <cr capture groups>)
        cwf=<format string>  format to write to file. defaults to "{content}"
                             (args: content, label, content_enc, encoding, document, escape, [di], [ci], [link], <lr capture groups>, <cr capture groups>)
        csin<bool>           giva a promt to edit the save path for a file
        cin=<bool>           give a prompt to ignore a potential content match
        cl=<bool>            treat content match as a link to the actual content
        cesc=<string>        escape sequence to terminate content in cin mode
        cienc=<encoding>     default encoding to assume that content is in
        cfienc=<encoding>    encoding to always assume that content is in, even if http(s) says differently
        cenc=<encoding>      encoding to use for content_enc

    Labels to give each matched content (becomes the filename):
        lx=<xpath>          xpath for label matching
        lr=<regex>          regex for label matching
        lf=<format string>  label format string (args: <lr capture groups>, label, di, ci)
        lic=<bool>          match for the label within the content match instead of the hole document
        las=<bool>          allow slashes in labels
        lm=<bool>           allow multiple label matches in one document instead of picking the first
        lam=<bool>          allow missing label (default is to skip content if no label is found)
        lfd=<format string> default label format string to use if there's no match (args: di, ci)
        lin=<bool>          give a prompt to edit the generated label

    Further documents to scan referenced in already found ones:
        dx=<xpath>          xpath for document matching
        dr=<regex>          regex for document matching
        df=<format string>  document format string (args: <dr capture groups>, document)
        dimin=<number>      initial document index, each successful match gets one index
        dimax=<number>      max document index, matching stops here
        dm=<bool>           allow multiple document matches in one document instead of picking the first
        din=<bool>          give a prompt to ignore a potential document match
        denc=<encoding>     default document encoding to use for following documents, default is utf-8
        dfenc=<encoding>    force document encoding for following documents, even if http(s) says differently
        dsch=<scheme>       default scheme for urls derived from following documents, defaults to "https"
        dpsch=<bool>        use the parent documents scheme if available, defaults to true unless dsch is specified
        dfsch=<scheme>      force this scheme for urls derived from following documents
        doc=<chain spec>    chains that matched documents should apply to, default is the same chain    

    Initial Documents:
        url=<url>           fetch a document from a url, derived document matches are (relative) urls
        file=<path>         fetch a document from a file, derived documents matches are (relative) file pathes
        rfile=<path>        fetch a document from a file, derived documents matches are urls

    Chain Syntax:
        Any option above can restrict the matching chains is should apply to using opt<chainspec>=<value>.
        Use "-" for ranges, "," for multiple specifications, and "^" to except the following chains.
        Examples:
            lf1,3-5=foo     sets "lf" to "foo" for chains 1, 3, 4 and 5.
            lf2-^4=bar      sets "lf" to "bar" for all chains larger than or equal to 2, except chain 4

    Global Options:
        bfs=<bool>          traverse the matched documents in breadth first order instead of depth first
        v=<verbosity>       output verbosity levels (default: warn, values: info, warn, error)
        ua=<string>         user agent to pass in the html header for url GETs
        uar=<bool>          use a rangom user agent
        cookiefile=<path>   path to a netscape cookie file. cookies are passed along for url GETs
        sel=<browser>       use selenium to load urls into an interactive browser session
                            (default: disabled, values: tor, chrome, firefox, disabled)
        selstrat=<browser>  matching strategy for selenium (default: first, values: first, interactive, deduplicate)
        tbdir=<path>        root directory of the tor browser installation, implies sel=tor
                            (default: environment variable TOR_BROWSER_DIR)
  ```
