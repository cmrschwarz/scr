# SCR

Command-line Utility for Web Scraping


[![GitHub Workflow Status (branch)](https://github.com/cmrschwarz/scr/workflows/tests/badge.svg)](https://github.com/cmrschwarz/scr/actions/workflows/tests.yml)
[![Supported Versions](https://img.shields.io/pypi/v/scr?color=blue)](https://pypi.org/project/scr)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/scr)](https://pypi.org/project/scr)
![Lines of code](https://img.shields.io/tokei/lines/github/cmrschwarz/scr?label=lines%20of%20code)
[![PyPI - License](https://img.shields.io/pypi/l/scr?color=dark-green)](./LICENSE)

## Core Features
* Extract web content based on XPath-, Regex-, (Javascript-), and Python Format Expressions
* Crawls through complex graphs of webpages using expressive match chains and forwarding rules
* Selenium support, explicitly also for headless mode and for the Tor Browser
* REPL mode for quick and dirty jobs / debugging larger commands
* **dd** style Command-line Interface
* Multithreaded downloads with optional progress output on the console
* Interactive modes for rejecting false matches, adjusting filenames etc.

## Setup

SCR can be installed from pypi.org using

```bash
pip install scr
```

Selenium drivers for Firefox/Tor (``geckodriver``), and chrome/chromium
(``chromedriver``) can be installed e.g. using
```
scr selinstall=firefox
``` 
(and later updated e.g. using ``scr selupdate=chrome``).
You still need to have the browser installed, though.


## Examples

### Download and enumerate all images from a website into the current working directory:
```bash
scr url=google.com cx='//img/@src' cl csf="img_{ci}{fe}" 
```

### Open up a REPL, remote controlling a Firefox Browser using selenium
```bash
scr repl sel=firefox url="https://en.wikipedia.org/wiki/web_scraping"
scr> 'cx=//span[text()="Edit"]/parent::*/parent::*/@id' cjs="document.getElementById(cx).children[0].click()"
scr> exit
```

### Interactively scroll through top reddit posts, following the 'next page' buttons:
```bash
scr url=old.reddit.com dx='//span[@class="next-button"]/a/@href' cx='//div[contains(@class,"entry")]//a[contains(@class,"title")]/text()' din mt=0
```

### Downloading first 3 pdfs and first 5 gifs from a site, use a headless selenium tor browser for the fetch:
```bash
scr url=https://dtc.ucsf.edu/learning-library/resource-materials/ cx=//@href cr0='.*\.pdf$' cr1='.*\.gif$' cl csf='{fn}' cin=1 cimax0=3 cimax1=5 sel=tor selh
```


## Options List
```
scr [OPTIONS]

    Matching chains are evaluated in the following order, skipping unspecified steps:
    xpath -> regex -> (javascript) -> python format string

    Content to Write out:
        cx=<xpath>            xpath for content matching
        cr=<regex>            regex for content matching
        cjs=<js string>       javascript to execute on the page, format args are available as js variables (selenium only)
        cf=<format string>    content format string (args: <cr capture groups>, xmatch, rmatch, di, ci)
        cmm=<bool>            allow multiple content matches in one document instead of picking the first (defaults to true)
        cimin=<number>        initial content index, each successful match gets one index
        cimax=<number>        max content index, matching stops here
        cicont=<bool>         don't reset the content index for each document
        csf=<format string>   save content to file at the path resulting from the format string, empty to enable
        cwf=<format string>   format to write to file. defaults to "{c}"
        cpf=<format string>   print the result of this format string for each content, empty to disable
                              defaults to "{c}\n" if cpf, csf and cfc are unspecified
        cfc=<chain spec>      forward content match as a virtual document
        cff=<format string>   format of the virtual document forwarded to the cfc chains. defaults to "{c}"
        csin<bool>            give a promt to edit the save path for a file
        cin=<bool>            give a prompt to ignore a potential content match
        cl=<bool>             treat content match as a link to the actual content
        cesc=<string>         escape sequence to terminate content in cin mode, defaults to "<END>"
        cenc=<encoding>       default encoding to assume that content is in
        cfenc=<encoding>      encoding to always assume that content is in, even if http(s) says differently

    Labels to give each matched content (mostly useful for the filename in csf):
        lx=<xpath>           xpath for label matching
        lr=<regex>           regex for label matching
        ljs=<js string>      javascript to execute on the page, format args are available as js variables (selenium only)
        lf=<format string>   label format string
        lic=<bool>           match for the label within the content match instead of the hole document
        las=<bool>           allow slashes in labels
        lmm=<bool>           allow multiple label matches in one document instead of picking the first (for all content matches)
        lam=<bool>           allow missing label (default is to skip content if no label is found)
        lfd=<format string>  default label format string to use if there's no match
        lin=<bool>           give a prompt to edit the generated label

    Further documents to scan referenced in already found ones:
        dx=<xpath>           xpath for document matching
        dr=<regex>           regex for document matching
        djs=<js string>      javascript to execute on the page, format args are available as js variables (selenium only)
        df=<format string>   document format string
        dimin=<number>       initial document index, each successful match gets one index
        dimax=<number>       max document index, matching stops here
        dmm=<bool>           allow multiple document matches in one document instead of picking the first
        din=<bool>           give a prompt to ignore a potential document match
        denc=<encoding>      default document encoding to use for following documents, default is utf-8
        dfenc=<encoding>     force document encoding for following documents, even if http(s) says differently
        dsch=<scheme>        default scheme for urls derived from following documents, defaults to "https"
        dpsch=<bool>         use the parent documents scheme if available, defaults to true unless dsch is specified
        dfsch=<scheme>       force this scheme for urls derived from following documents
        doc=<chain spec>     chains that matched documents should apply to, default is the same chain

    Initial Documents:
        url=<url>            fetch a document from a url, derived document matches are (relative) urls
        file=<path>          fetch a document from a file, derived documents matches are (relative) file pathes
        rfile=<path>         fetch a document from a file, derived documents matches are urls

    Other:
        selstrat=<strategy>  matching strategy for selenium (default: plain, values: anymatch, plain, interactive, deduplicate)
        seldl=<dl strategy>  download strategy for selenium (default: external, values: external, internal, fetch)
        owf=<bool>           allow to overwrite existing files, defaults to true

    Format Args:
        Named arguments for <format string> arguments.
        Some only become available later in the pipeline (e.g. {cm} is not available inside cf).

        {cx}                 content xpath match
        {cr}                 content regex match, equal to {cx} if cr is unspecified
        <cr capture groups>  the named regex capture groups (?P<name>...) from cr are available as {name},
                             the unnamed ones (...) as {cg<unnamed capture group number>}
        {cf}                 content after applying cf
        {cjs}                output of cjs
        {cm}                 final content match after link normalization (cl) and user interaction (cin)
        {c}                  content, downloaded from cm in case of cl, otherwise equal to cm

        {lx}                 label xpath match
        {lr}                 label regex match, equal to {lx} if lr is unspecified
        <lr capture groups>  the named regex capture groups (?P<name>...) from cr are available as {name},
                             the unnamed ones (...) as {lg<unnamed capture group number>}
        {lf}                 label after applying lf
        {ljs}                output of ljs
        {l}                  final label after user interaction (lin)

        {dx}                 document link xpath match
        {dr}                 document link regex match, equal to {dx} if dr is unspecified
        <dr capture groups>  the named regex capture groups (?P<name>...) from dr are available as {name},
                             the unnamed ones (...) as {dg<unnamed capture group number>}
        {df}                 document link after applying df
        {djs}                output of djs
        {d}                  final document link after user interaction (din)

        {di}                 document index
        {ci}                 content index
        {dl}                 document link (inside df, this refers to the parent document)
        {cenc}               content encoding, deduced while respecting cenc and cfenc
        {cesc}               escape sequence for separating content, can be overwritten using cesc
        {chain}              id of the match chain that generated this content

        {fn}                 filename from the url of a cm with cl
        {fb}                 basename component of {fn} (extension stripped away)
        {fe}                 extension component of {fn}, including the dot (empty string if there is no extension)


    Chain Syntax:
        Any option above can restrict the matching chains is should apply to using opt<chainspec>=<value>.
        Use "-" for ranges, "," for multiple specifications, and "^" to except the following chains.
        Examples:
            lf1,3-5=foo        sets "lf" to "foo" for chains 1, 3, 4 and 5.
            lf2-^4=bar         sets "lf" to "bar" for all chains larger than or equal to 2, except chain 4

    Miscellaneous:
        help                   prints this help
        selinstall=<browser>   installs selenium driver for the specified browser in the directory of this script
        seluninstall=<browser> uninstalls selenium driver for the specified browser in the directory of this script
        selupdate=<browser>    updates (or installs) the local selenium driver for the specified browser
        version                print version information

    Global Options:
        timeout=<seconds>      seconds before a web request timeouts (default 30)
        bfs=<bool>             traverse the matched documents in breadth first order instead of depth first
        v=<verbosity>          output verbosity levels (default: warn, values: info, warn, error)
        ua=<string>            user agent to pass in the html header for url GETs
        uar=<bool>             use a rangom user agent
        selkeep=<bool>         keep selenium instance alive after the command finished
        cookiefile=<path>      path to a netscape cookie file. cookies are passed along for url GETs
        sel=<browser|bool>     use selenium (default is firefox) to load urls into an interactive browser session
                               (default: disabled, values: tor, chrome, firefox, disabled)
        selh=<bool>            use selenium in headless mode, implies sel
        tbdir=<path>           root directory of the tor browser installation, implies sel=tor
                               (default: environment variable TOR_BROWSER_DIR)
        mt=<int>               maximum threads for background downloads, 0 to disable. defaults to cpu core count
        repl=<bool>            accept commands in a read eval print loop
        exit=<bool>            exit the repl (with the result of the current command)
```
