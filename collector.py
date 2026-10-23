#!/usr/bin/env python3
"""Bounded institutional publication-reference collector. No clinical or billing interpretation.
The only automatically qualified scope is the existence/date/topic of an official RSS reference.
Complementary and unqualified content never reaches the Android VERIFIED-content catalogue.
"""
import argparse,base64,datetime as dt,email.utils,hashlib,html,json,os,pathlib,re,shutil,struct,subprocess,tempfile,time,unicodedata,urllib.parse,xml.etree.ElementTree as ET
MAX_BYTES=8*1024*1024; MAX_SOURCE=2_000_000; MAX_TOTAL=12_000_000; MAX_ENTRIES=512
MAGIC=b'OMCADV01'; total=0
TOPICS=[('surveillance respiratoire',r'grippe|bronchiolit|respiratoire|bpco|pneum'),('surveillance des arboviroses',r'chikungunya|dengue|zika'),('recours aux urgences',r'oscour'),('surveillance de la mortalité',r'mortalité'),('santé mentale',r'santé mentale|depress|dépress|psych'),('vaccination',r'vaccin'),('diabète',r'diab'),('prévention cardiovasculaire',r'cardiovasc|hypertension'),('prévention des infections',r'infection|antibio|rougeole|coqueluche'),('dépistage',r'dépist|depist'),('parcours de soins',r'parcours de soins|médecine générale|soins primaires')]
EXCLUDE=re.compile(r'candidature|recrut|emploi|chef de projet|certification|commission|essms|offre d|congrès|webinaire',re.I)
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(u,host):
 p=urllib.parse.urlsplit(u)
 if p.scheme!='https' or p.username or p.password or (p.hostname or '').lower()!=host:raise ValueError('URL hors source ou non HTTPS')
 query=urllib.parse.urlencode([(k,v) for k,v in urllib.parse.parse_qsl(p.query) if not k.lower().startswith(('utm_','fbclid'))])
 return urllib.parse.urlunsplit(('https',p.netloc,p.path,query,''))
def fetch(url):
 global total
 if urllib.parse.urlsplit(url).scheme!='https':raise ValueError('HTTPS requis')
 executable=shutil.which('curl.exe' if os.name=='nt' else 'curl')
 if not executable:raise ValueError('Client TLS système absent')
 cmd=[executable,'--fail','--silent','--show-error','--max-time','20','--connect-timeout','8','--max-filesize',str(MAX_SOURCE),'--proto','=https','--max-redirs','0','--user-agent','OptiMedCot-Collector/1.0',url]
 with subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as p:
  raw=p.stdout.read(MAX_SOURCE+1)
  if len(raw)>MAX_SOURCE:p.kill();raise ValueError('Source trop volumineuse')
  error=p.stderr.read(2048);code=p.wait(timeout=25)
  if code:raise ValueError('Accès impossible '+error.decode(errors='replace')[:180])
 total+=len(raw)
 if total>MAX_TOTAL:raise ValueError('Budget global dépassé')
 return raw
class Reader:
 def __init__(self,b):self.b=b;self.p=0
 def take(self,n):
  if n<0 or self.p+n>len(self.b):raise ValueError('Troncature')
  v=self.b[self.p:self.p+n];self.p+=n;return v
 def i(self):return struct.unpack('>i',self.take(4))[0]
 def l(self):return struct.unpack('>q',self.take(8))[0]
 def text(self):
  n=self.i()
  if not 0<=n<=1048576:raise ValueError('Texte trop grand')
  return self.take(n).decode('utf-8',errors='strict')
 def flag(self):
  b=self.take(1)
  if b not in (b'\0',b'\1'):raise ValueError('Booléen invalide')
  return b==b'\1'
 def nullable(self,fn):return fn() if self.flag() else None
 def items(self,fn):
  n=self.i()
  if not 0<=n<=2048:raise ValueError('Liste trop grande')
  return [fn() for _ in range(n)]
 def instant(self):return self.l(),self.i()
 def rev(self):return self.text(),self.text()
 def producer(self):return self.text(),self.text(),self.text()
 def evidence(self):return self.text(),self.text(),self.text()
 def document(self):
  self.text();self.producer();self.text();self.nullable(self.text);self.nullable(self.text);self.nullable(self.text);self.nullable(self.instant)
 def review(self):self.text();self.nullable(self.rev);self.nullable(self.instant);self.items(self.evidence)
 def justification(self):self.nullable(self.text);self.text();self.items(self.evidence)
 def target(self):
  tag=self.text()
  if tag=='only':self.items(self.text)
  elif tag not in ('all','unknown'):raise ValueError('Ciblage non supporté')
 def geography(self,depth=0):
  if depth>4:raise ValueError('Profondeur')
  tag=self.text()
  if tag in ('unknown','national'):return
  if tag=='departments':self.items(self.text)
  elif tag=='region':self.text();self.nullable(lambda:self.items(self.text));self.items(self.evidence)
  elif tag=='other':self.text();self.text()
  elif tag=='foreign':self.text();self.nullable(self.justification);self.geography(depth+1)
  else:raise ValueError('Géographie')
 def entry(self):
  start=self.p;rev=self.rev();self.text();title=self.text();self.text();self.text();self.nullable(self.producer);self.items(self.document);published=self.nullable(self.l);self.review()
  validity=self.text()
  if validity=='during':self.l();self.nullable(self.l)
  elif validity not in ('unknown','unbounded-stated'):raise ValueError('Validité')
  for _ in range(3):self.target()
  self.geography();self.nullable(self.justification);self.nullable(lambda:(self.text(),self.nullable(self.justification)))
  rightsrev=self.rev();self.text();self.nullable(self.instant);self.text();self.text();self.text();self.nullable(self.text);self.nullable(self.text);self.text();self.items(self.text)
  if rightsrev!=rev:raise ValueError('Droits mal liés')
  return {'rev':rev,'title':title,'raw':self.b[start:self.p],'published':(dt.date(1970,1,1)+dt.timedelta(days=published)).isoformat() if published is not None else None}
def decode(blob):
 if not 48<=len(blob)<=MAX_BYTES or blob[:8]!=MAGIC:raise ValueError('Format')
 version,n=struct.unpack('>ii',blob[8:16]);body=blob[48:]
 if version!=1 or n!=len(body) or hashlib.sha256(body).digest()!=blob[16:48]:raise ValueError('Intégrité/version')
 r=Reader(body);generation=r.l();r.instant();r.text();revs=r.items(r.rev);current=dict(r.items(r.rev));entries=r.items(r.entry)
 if r.p!=len(body) or not 0<len(entries)<=MAX_ENTRIES or len(set(revs))!=len(revs) or set(revs)!={x['rev'] for x in entries} or any((k,v) not in revs for k,v in current.items()):raise ValueError('Inventaire')
 return generation,current,entries
class Writer:
 def __init__(self):self.b=bytearray()
 def i(self,v):self.b+=struct.pack('>i',v)
 def l(self,v):self.b+=struct.pack('>q',v)
 def text(self,v):
  b=v.encode('utf-8');assert len(b)<=1048576;self.i(len(b));self.b+=b
 def flag(self,v):self.b+=b'\1' if v else b'\0'
 def nullable(self,v,fn):self.flag(v is not None);fn(v) if v is not None else None
 def items(self,values,fn):self.i(len(values));[fn(v) for v in values]
 def instant(self,v):self.l(int(v.timestamp()));self.i(v.microsecond*1000)
 def rev(self,v):self.text(v[0]);self.text(v[1])
 def producer(self,s):self.text(s['id']);self.text(s['name']);self.text('VERIFIED_INSTITUTIONAL')
 def evidence(self,v):self.text(v[0]);self.text(v[1]);self.text(v[2])
 def justification(self,text,evidence):self.nullable(text,self.text);self.text('VERIFIED');self.items([evidence],self.evidence)
def encode(generation,now,current,entries):
 if not 0<len(entries)<=MAX_ENTRIES:raise ValueError('Limite de révisions ; conserver le catalogue précédent')
 w=Writer();w.l(generation);w.instant(now);w.text('Europe/Paris');w.items(sorted(x['rev'] for x in entries),w.rev);w.items(sorted(current.items()),w.rev);w.i(len(entries))
 for item in entries:w.b+=item['raw']
 body=bytes(w.b);blob=MAGIC+struct.pack('>ii',1,len(body))+hashlib.sha256(body).digest()+body
 if len(blob)>MAX_BYTES:raise ValueError('Catalogue trop grand')
 decode(blob);return blob
def parse_date(v):
 if not v:return None
 try:
  try:d=dt.datetime.fromisoformat(v.strip().replace('Z','+00:00'))
  except ValueError:d=email.utils.parsedate_to_datetime(v.strip())
  if d.tzinfo is None:
   return d.date() if re.fullmatch(r'\d{4}-\d{2}-\d{2}',v.strip()) else None
  return d.astimezone(dt.timezone.utc)
 except (ValueError,TypeError,OverflowError):return None
def rss(raw,source,now):
 if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('XML externe interdit')
 root=ET.fromstring(raw)
 if root.tag.split('}')[-1]!='rss':raise ValueError('Réponse non RSS')
 items=[];page_checks=0;host=urllib.parse.urlsplit(source['url']).hostname
 nodes=root.findall('./channel/item')
 if len(nodes)>MAX_ENTRIES:raise ValueError('Budget des références RSS dépassé')
 for node in nodes:
  title=html.unescape(node.findtext('title') or '').strip();url=node.findtext('link') or ''
  date=parse_date(node.findtext('pubDate') or node.findtext('{http://purl.org/dc/elements/1.1/}date'))
  if not title or '\ufffd' in title:continue
  try:url=canonical(url,host)
  except ValueError:continue
  folded=unicodedata.normalize('NFKC',title).lower()
  topic=next((name for name,pattern in TOPICS if re.search(pattern,folded)),None)
  if not topic or EXCLUDE.search(folded):continue
  if date is None and source['id']=='spf' and page_checks<6:
   page_checks+=1
   page=fetch(url).decode('utf-8',errors='strict')
   match=re.search(r'<time\s+datetime="([^"]+)"[^>]*>\s*Publi(?:é|&eacute;) le',page,re.I)
   if match:date=parse_date(match.group(1))
  if date is None:continue
  day=date.date() if isinstance(date,dt.datetime) else date
  if day>now.date() or (now.date()-day).days>120:continue
  metadata={'url':url,'date':date.isoformat(),'topic':topic,'issuer':source['id'],'type':source['kind'],'profile':'reference-only-v2','descriptionDigest':sha((node.findtext('description') or '').encode('utf-8'))}
  # HAS metadata only, under its explicit public-information reuse terms. Never SPF text.
  if source.get('publication')=='HAS_METADATA':
   description=node.findtext('description') or ''
   description=re.sub(r'<(script|style)\b[^>]*>.*?</\1>','',description,flags=re.I|re.S)
   description=' '.join(html.unescape(re.sub(r'<[^>]+>',' ',description)).split())
   if re.search(r'copyright|tous droits|droits r.serv.s|©',title+' '+description,re.I):continue
   if len(title)>2000 or len(description)>8000:continue
   metadata['officialTitle']=title;metadata['officialAbstract']=description
   metadata['profile']='has-rss-metadata-v1'
  # Sources restricted to links never redistribute their titles/abstracts.
  metadata['digest']=sha(json.dumps({'title':title,**metadata},ensure_ascii=False,sort_keys=True).encode())
  items.append(metadata)
 return items

def make_entry(s,m,now,rights_digest):
 identity='fr.optimedcot.notice.'+sha(m['url'].encode())[:24];revision='metadata-'+m['digest'][:24];rev=(identity,revision);docid='rss-reference';w=Writer()
 title=s['name']+' — '+m['topic'].capitalize()+' : publication à consulter'
 title=m.get('officialTitle') or title
 summary=m.get('officialAbstract') or title
 body=('Notice documentaire originale OptiMedCot. Source officielle — '+s['name']+'.\nSujet : '+m['topic']+'.\nDate fournie par le flux : '+m['date'][:10]+'.\n'+
 'Vérification : origine HTTPS, référence, sujet et métadonnées du flux contrôlés le '+now.date().isoformat()+'. Le contenu clinique, les tarifs et les conditions de facturation ne sont pas évalués par cette collecte. Cette notice ne constitue ni une recommandation clinique ni une autorisation de facturer.\n'+
 ('Métadonnées éditoriales du flux HAS, sans validation clinique. Source et date indiquées ; document intégral chez son éditeur.\n' if m.get('officialTitle') else 'Lien documentaire seulement ; aucun contenu clinique reproduit.\n')+'Source officielle : '+m['url'])
 if m.get('officialAbstract'):body=m['officialAbstract']+'\n\n'+body
 evidence=(docid,m['digest'],'Métadonnées de la référence dans le RSS officiel '+s['url']+' ; empreinte du relevé, pas du document intégral. Vérification limitée à la référence, sans validation clinique.')
 w.rev(rev);w.text('PROFESSIONAL_PRACTICE');w.text(title);w.text(summary);w.text(body);w.flag(True);w.producer(s);w.i(1)
 w.text(docid);w.producer(s);w.text('Référence bibliographique officielle sur '+m['topic']);w.nullable(m['url'],w.text);w.nullable('has-rss-metadata-v1' if m.get('officialTitle') else 'rss-reference-v1',w.text);w.nullable(m['digest'],w.text);w.nullable(now,w.instant)
 date=dt.date.fromisoformat(m['date'][:10]);w.nullable((date-dt.date(1970,1,1)).days,w.l)
 w.text('VERIFIED');w.nullable(rev,w.rev);w.nullable(now,w.instant);w.items([evidence],w.evidence);w.text('unbounded-stated')
 w.text('only');w.items(['doctor'],w.text);w.text('all');w.text('all');w.text('national');w.flag(True);w.justification('Repère de veille documentaire pour la médecine générale sur '+m['topic']+' ; pertinence éditoriale nationale, sans portée clinique ou territoriale inférée.',evidence);w.flag(False)
 w.rev(rev);w.text('VERIFIED');w.nullable(now,w.instant);w.text('ESTABLISHED');w.text('ESTABLISHED');w.text(s['rights_scope']+' ; vérification limitée aux métadonnées, aucune validation clinique ni redistribution du document intégral.')
 w.nullable(s['rights_url'],w.text);w.nullable(rights_digest,w.text);w.text('Mentions de l’éditeur : réutilisation des informations publiques ou établissement de liens ; scope REFERENCE_ONLY, sans reproduction du document.');w.items([docid],w.text)
 return {'rev':rev,'title':title,'raw':bytes(w.b)}

def collect(root,sources,now):
 old=(root/'catalogue.snapshot').read_bytes();generation,current,entries=decode(old);byrev={x['rev']:x for x in entries};status=[];discovery=[];added=0
 for s in sources:
  try:
   raw=fetch(s['url'])
   if s['format']!='rss':raise ValueError('HTML non qualifié pour publication automatique ; source enregistrée, aucune synthèse générée')
   candidates=rss(raw,s,now);result={'source':s['id'],'kind':s['kind'],'state':'COLLECTED','references':len(candidates),'published':0}
   rights_digest=None
   if s.get('publication') in ('REFERENCE_ONLY','HAS_METADATA') and candidates:
    rights=fetch(s['rights_url']);text=rights.decode('utf-8',errors='strict').lower()
    if not ((s['id']=='has' and 'librement' in text and '321-1' in text) or (s['id']=='spf' and 'tablissement de liens' in text and 'sans autorisation' in text)):raise ValueError('Base de droits absente ou modifiée')
    rights_digest=sha(rights)
   for m in candidates:
    itemstate='COMPLEMENTARY_UNVERIFIED' if s['kind']=='COMPLEMENTARY' else 'PENDING_QUALIFICATION'
    if rights_digest:
     identity='fr.optimedcot.notice.'+sha(m['url'].encode())[:24]
     item=make_entry(s,m,now,rights_digest);identity,version=item['rev']
     if current.get(identity)==version:itemstate='UNCHANGED_REFERENCE'
     else:
      byrev[item['rev']]=item;current[identity]=version;added+=1;result['published']+=1;itemstate='VERIFIED_REFERENCE_ONLY'
    discovery.append({**m,'verification':itemstate,'clinicalVerification':'NOT_ASSESSED'})
   status.append(result)
  except Exception as e:status.append({'source':s['id'],'kind':s['kind'],'state':'UNAVAILABLE_OR_QUARANTINED','reason':str(e)[:220]})
 if added:blob=encode(generation+1,now,current,list(byrev.values()))
 else:blob=old
 return blob,{'checkedAt':now.isoformat(),'newOrModifiedReferences':added,'generation':decode(blob)[0],'sources':status,'notice':'Only original publication-reference notices are eligible; no clinical/billing rule automatically qualified.'},discovery

def sign(blob,root,keyfile,openssl):
 with tempfile.TemporaryDirectory(prefix='optimedcot-sign-') as directory:
  path=pathlib.Path(directory);payload=path/'catalogue.snapshot';sig=path/'catalogue.sig';payload.write_bytes(blob)
  if keyfile:key=pathlib.Path(keyfile)
  else:
   material=base64.b64decode(os.environ['OPTIMEDCOT_SIGNING_KEY_B64'],validate=True)
   if len(material)>8192:raise ValueError('Clé invalide')
   key=path/'private.pkcs8';key.write_bytes(material);key.chmod(0o600)
  subprocess.run([openssl,'dgst','-sha256','-keyform','DER','-sign',str(key),'-out',str(sig),str(payload)],check=True,capture_output=True)
  public=path/'public.der';public.write_bytes(base64.b64decode((root/'public-key.txt').read_text().strip(),validate=True))
  subprocess.run([openssl,'dgst','-sha256','-keyform','DER','-verify',str(public),'-signature',str(sig),str(payload)],check=True,capture_output=True)
  return sig.read_bytes()
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=pathlib.Path,default=pathlib.Path('.'));p.add_argument('--sources',type=pathlib.Path,default=pathlib.Path('sources.json'));p.add_argument('--key');p.add_argument('--openssl',default='openssl');a=p.parse_args()
 now=dt.datetime.now(dt.timezone.utc);sources=json.loads(a.sources.read_text(encoding='utf-8-sig'))
 blob,status,discovery=collect(a.root,sources,now)
 if status['newOrModifiedReferences']:
  signature=sign(blob,a.root,a.key,a.openssl)
  # Publish only after complete validation/signature. The CI commits these together, Pages deploys the commit.
  (a.root/'catalogue.next').write_bytes(blob);(a.root/'signature.next').write_bytes(signature)
  os.replace(a.root/'catalogue.next',a.root/'catalogue.snapshot');os.replace(a.root/'signature.next',a.root/'catalogue.sig')
 (a.root/'collector-status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (a.root/'discovery.json').write_text(json.dumps(discovery,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(status,ensure_ascii=False))
if __name__=='__main__':main()
