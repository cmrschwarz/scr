# SCR

Command-line Utility for Web scring

## Core Features
* Matches web content using XPath-, Regex- and Python Format Expressions 
* Crawls through complex graphs of webpages using expressive match chains and forwarding rules
* Selenium support, explicitly also with the Tor Browser
* REPL mode for building up complex commands
* **dd** style Command-line Interface
* Multithreaded Downloads
* Interactive modes for rejecting false matches, adjusting filenames etc. 


## Examples

### Get text from all paragraphs on a site:
```bash 
scr url=google.com cx='//p/text()'
```

### Open up a REPL to explore, using firefox selenium 
```bash 
scr repl sel=firefox url=example.org
scr> cr="some regex to match in the open firefox tab" cpf="print regex result on stdout: {cr}"
scr> exit
```

### Interactively scroll through top reddit posts (max to page 42) :
```bash 
scr url=old.reddit.com dx='//span[@class="next-button"]/a/@href' cx='//div[contains(@class,"entry")]//a[contains(@class,"title")]/text()' din dimax=42
```

### Download the first 10 pdfs from a site and add their number (zero padded) before the filename:
```bash 
scr url=https://dtc.ucsf.edu/learning-library/resource-materials/ cx=//@href cr='.*\.pdf$' cl csf='{ci:02}_{fn}' cimax=10
```

### Downloading first 3 pdfs and 5 gifs from a site, use selenium tor for the fetch:
```bash 
scr url=https://dtc.ucsf.edu/learning-library/resource-materials/ cx=//@href cr0='.*\.pdf$' cr1='.*\.gif' cl csf='{fn}' cin=1 cimax0=3 cimax1=5 sel=tor
```

## Setup

SCR can be installed from pypi using

```bash
pip install scr
```

To use the selenium feature,
you need to have a driver for the selected browser installed.

### Setting up Firefox for selenium 

The geckodriver executable can be downloaded from
https://github.com/mozilla/geckodriver/releases
It must be in a folder on the PATH for scr to find it.

### Setting up Tor Browser for selenium
Once the Tor Browser have bin installed in any directory, add a 
TOR_BROWSER_DIR environment variable for scr to find it.
(Alternatively pass it explicitly using ```tbdir=<folder path>```)
Since Tor Browser is based on Firefox, the geckodriver executable
is also needed.

### Setting up Chrome for Selenium

Simply install the `chromium-driver` (debian +deriviates),
`chromium-chromedriver` (alpine) or `chromedriver` (arch aur)
package for your distribution. 
(A pullrequest with instructions for windows here would be appreciated.)

## Options List
```
scr [OPTIONS]
    Extract content from urls or files by specifying content matching chains
    (xpath -> regex -> python format string).

    Content to Write out:
        cx=<xpath>           xpath for content matching
        cr=<regex>           regex for content matching
        cf=<format string>   content format string (args: <cr capture groups>, xmatch, rmatch, di, ci)
        cmm=<bool>           allow multiple content matches in one document instead of picking the first (defaults to true)
        cimin=<number>       initial content index, each successful match gets one index
        cimax=<number>       max content index, matching stops here
        cicont=<bool>        don't reset the content index for each document
        csf=<format string>  save content to file at the path resulting from the format string, empty to enable
        cwf=<format string>  format to write to file. defaults to "{c}"
        cpf=<format string>  print the result of this format string for each content, empty to disable
                             defaults to "{c}\n" if cpf, csf and cfc are unspecified
        cfc=<chain spec>     forward content match as a virtual document
        cff=<format string>  format of the virtual document forwarded to the cfc chains. defaults to "{c}"
        csin<bool>           give a promt to edit the save path for a file
        cin=<bool>           give a prompt to ignore a potential content match
        cl=<bool>            treat content match as a link to the actual content
        cesc=<string>        escape sequence to terminate content in cin mode, defaults to "<END>"
        cenc=<encoding>      default encoding to assume that content is in
        cfenc=<encoding>     encoding to always assume that content is in, even if http(s) says differently

    Labels to give each matched content (mostly useful for the filename in csf):
        lx=<xpath>          xpath for label matching
        lr=<regex>          regex for label matching
        lf=<format string>  label format string
        lic=<bool>          match for the label within the content match instead of the hole document
        las=<bool>          allow slashes in labels
        lmm=<bool>          allow multiple label matches in one document instead of picking the first (for all content matches)
        lam=<bool>          allow missing label (default is to skip content if no label is found)
        lfd=<format string> default label format string to use if there's no match
        lin=<bool>          give a prompt to edit the generated label

    Further documents to scan referenced in already found ones:
        dx=<xpath>          xpath for document matching
        dr=<regex>          regex for document matching
        df=<format string>  document format string
        dimin=<number>      initial document index, each successful match gets one index
        dimax=<number>      max document index, matching stops here
        dmm=<bool>           allow multiple document matches in one document instead of picking the first
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

    Other:
        selstrat=<strategy> matching strategy for selenium (default: first, values: first, interactive, deduplicate)
        seldl=<dl strategy> download strategy for selenium (default: external, values: external, internal, fetch)
        owf=<bool>          allow to overwrite existing files, defaults to true

    Format Args:
        Named arguments for <format string> arguments.
        Some only become available later in the pipeline (e.g. {cm} is not available inside cf).

        {cx}                content xpath match
        {cr}                content regex match, equal to {cx} if cr is unspecified
        <cr capture groups> the named regex capture groups (?P<name>...) from cr are available as {name},
                            the unnamed ones (...) as {cg<unnamed capture group number>}
        {cf}                content after applying cf
        {cm}                final content match after link normalization (cl) and user interaction (cin)

        {lx}                label xpath match
        {lr}                label regex match, equal to {lx} if lr is unspecified
        <lr capture groups> the named regex capture groups (?P<name>...) from cr are available as {name},
                            the unnamed ones (...) as {lg<unnamed capture group number>}
        {lf}                label after applying lf
        {l}                 final label after user interaction (lin)

        {dx}                document link xpath match
        {dr}                document link regex match, equal to {dx} if dr is unspecified
        <dr capture groups> the named regex capture groups (?P<name>...) from dr are available as {name},
                            the unnamed ones (...) as {dg<unnamed capture group number>}
        {df}                document link after applying df
        {d}                 final document link after user interaction (din)

        {di}                document index
        {ci}                content index
        {dl}                document link (even for df, this still refers to the parent document)
        {cenc}              content encoding, deduced while respecting cenc and cfenc
        {cesc}              escape sequence for separating content, can be overwritten using cesc

        {c}                 content, downloaded from cm in case of cl, otherwise equal to cm

    Chain Syntax:
        Any option above can restrict the matching chains is should apply to using opt<chainspec>=<value>.
        Use "-" for ranges, "," for multiple specifications, and "^" to except the following chains.
        Examples:
            lf1,3-5=foo     sets "lf" to "foo" for chains 1, 3, 4 and 5.
            lf2-^4=bar      sets "lf" to "bar" for all chains larger than or equal to 2, except chain 4

    Global Options:
        timeout=<seconds>   seconds before a web request timeouts (default 30)
        bfs=<bool>          traverse the matched documents in breadth first order instead of depth first
        v=<verbosity>       output verbosity levels (default: warn, values: info, warn, error)
        ua=<string>         user agent to pass in the html header for url GETs
        uar=<bool>          use a rangom user agent
        selkeep=<bool>      keep selenium instance alive after the command finished
        cookiefile=<path>   path to a netscape cookie file. cookies are passed along for url GETs
        sel=<browser>       use selenium to load urls into an interactive browser session
                            (default: disabled, values: tor, chrome, firefox, disabled)
        tbdir=<path>        root directory of the tor browser installation, implies sel=tor
                            (default: environment variable TOR_BROWSER_DIR)
        mt=<int>            maximum threads for background downloads, 0 to disable. defaults to cpu core count.
        repl=<bool>         accept commands in a read eval print loop
        exit=<bool>         exit the repl (with the result of the current command)
  ```
