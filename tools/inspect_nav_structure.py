"""Read-only structure diagnostic; never print market numbers or source bodies."""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from tools.collect_nav import Tables, decode_html

class Scripts(HTMLParser):
    def __init__(self):super().__init__();self.sources=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('src'):self.sources.append(dict(attrs)['src'])

def main(directory):
    d=Path(directory)
    if not (d/'probe.json').exists():return
    for r in json.loads((d/'probe.json').read_text())['results']:
        if not r.get('raw_response_archived'):continue
        try:
            html,_=decode_html((d/r['raw_file']).read_bytes(),r.get('header_charset'),r.get('content_encoding'))
        except (ValueError,UnicodeError):continue
        p=Tables();p.feed(html);s=Scripts();s.feed(html)
        headers=[]
        for t in p.tables[:12]:
            labels=[]
            for row in t[:3]:
                for cell in row:
                    # Keep only short purely textual headings, no NAV/amount/date cells.
                    if 0<len(cell)<=40 and not re.search(r'[0-9<>%]',cell):labels.append(cell)
            headers.append({'rows':len(t),'labels':labels[:12]})
        assets=[]
        for src in s.sources[:30]:
            u=urlsplit(urljoin(r['url'],src))
            if u.hostname==urlsplit(r['url']).hostname and not u.username and not u.password:
                assets.append(u.scheme+'://'+u.netloc+u.path)
        dates=sorted(set(re.findall(r'\b20\d\d-\d\d-\d\d\b',html)))
        print(json.dumps({'code':r['code'],'table_count':len(p.tables),'table_structure':headers,
                         'same_host_scripts':assets,'dates_present_count':len(dates),
                         'last_date_string':dates[-1] if dates else None},ensure_ascii=False))

if __name__=='__main__':main(sys.argv[1])
