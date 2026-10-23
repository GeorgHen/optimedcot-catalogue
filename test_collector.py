import unittest,datetime as dt,json,pathlib,tempfile
from unittest.mock import patch
import collector as c
NOW=dt.datetime(2026,10,22,tzinfo=dt.timezone.utc)
SOURCE={'format':'rss','id':'has','name':'HAS','kind':'OFFICIAL','url':'https://www.has-sante.fr/feed','rights_url':'https://www.has-sante.fr/legal','publication':'REFERENCE_ONLY','rights_scope':'Original notice only'}
def item(url='https://www.has-sante.fr/one',title='Vaccination',date='Thu, 22 Oct 2026 08:00:00 GMT'):
 return f'<rss><channel><item><title>{title}</title><link>{url}</link><pubDate>{date}</pubDate></item></channel></rss>'.encode()
class CollectorTests(unittest.TestCase):
 def test_source_restrictions(self):
  for url in ['http://www.has-sante.fr/a','https://evil.fr/a','https://u:p@www.has-sante.fr/a']:
   with self.assertRaises(ValueError):c.canonical(url,'www.has-sante.fr')
 def test_xml_external_and_wrong_format(self):
  for raw in [b'<!DOCTYPE rss><rss/>',b'<!ENTITY a SYSTEM "file:///x"><rss/>',b'<html/>']:
   with self.assertRaises(ValueError):c.rss(raw,SOURCE,NOW)
 def test_dates_are_not_invented(self):
  for date in ['', '2026-10-23','2020-01-01','Thu, 22 Oct 2026 08:00:00']:
   self.assertEqual([],c.rss(item(date=date),SOURCE,NOW))
  self.assertEqual(1,len(c.rss(item(),SOURCE,NOW)))
 def test_stable_identity_revision_and_content(self):
  m=c.rss(item(),SOURCE,NOW)[0];e=c.make_entry(SOURCE,m,NOW,'a'*64)
  e2=c.make_entry(SOURCE,m,NOW,'a'*64)
  self.assertEqual(e,e2)
  changed=c.rss(item(title='Vaccination : actualisation'),SOURCE,NOW)[0]
  e3=c.make_entry(SOURCE,changed,NOW,'a'*64)
  self.assertEqual(e['rev'][0],e3['rev'][0]);self.assertNotEqual(e['rev'][1],e3['rev'][1])
 def test_codec_checksums_and_repeat(self):
  e=c.make_entry(SOURCE,c.rss(item(),SOURCE,NOW)[0],NOW,'a'*64)
  blob=c.encode(1,NOW,{e['rev'][0]:e['rev'][1]},[e]);self.assertEqual(1,c.decode(blob)[0]);self.assertEqual('2026-10-22',c.decode(blob)[2][0]['published'])
  broken=bytearray(blob);broken[-1]^=1
  with self.assertRaises(ValueError):c.decode(bytes(broken))
  with self.assertRaises(ValueError):c.decode(blob[:-1])
 def test_source_publication_date_is_not_receipt(self):
  m=c.rss(item(date='Wed, 21 Oct 2026 08:00:00 GMT'),SOURCE,NOW)[0]
  e=c.make_entry(SOURCE,m,NOW,'a'*64)
  b=c.encode(1,NOW,{e['rev'][0]:e['rev'][1]},[e])
  self.assertEqual('2026-10-21',c.decode(b)[2][0]['published'])
 def test_failure_preserves_last_catalogue(self):
  e=c.make_entry(SOURCE,c.rss(item(),SOURCE,NOW)[0],NOW,'a'*64)
  blob=c.encode(1,NOW,{e['rev'][0]:e['rev'][1]},[e])
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);(root/'catalogue.snapshot').write_bytes(blob)
   with patch.object(c,'fetch',side_effect=ValueError('Unavailable')):
    out,status,_=c.collect(root,[SOURCE],NOW)
   self.assertEqual(blob,out);self.assertEqual(0,status['newOrModifiedReferences'])
 def test_duplicate_reference_does_not_duplicate_catalogue(self):
  m=c.rss(item(),SOURCE,NOW)[0];e=c.make_entry(SOURCE,m,NOW,'a'*64)
  blob=c.encode(1,NOW,{e['rev'][0]:e['rev'][1]},[e])
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);(root/'catalogue.snapshot').write_bytes(blob)
   with patch.object(c,'fetch',side_effect=[item(),b'librement 321-1']):out,status,_=c.collect(root,[SOURCE],NOW)
   self.assertEqual(blob,out);self.assertEqual(0,status['newOrModifiedReferences'])
 def test_twenty_five_new_references_are_not_capped_at_six(self):
  old=c.make_entry(SOURCE,c.rss(item(url='https://www.has-sante.fr/old'),SOURCE,NOW)[0],NOW,'a'*64)
  blob=c.encode(1,NOW,{old['rev'][0]:old['rev'][1]},[old])
  entries=''.join(f'<item><title>SYNTHETIC Vaccination {n}</title><link>https://www.has-sante.fr/new-{n}</link><pubDate>Thu, 22 Oct 2026 08:00:00 GMT</pubDate></item>' for n in range(25))
  rss=('<rss><channel>'+entries+'</channel></rss>').encode()
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);(root/'catalogue.snapshot').write_bytes(blob)
   with patch.object(c,'fetch',side_effect=[rss,b'librement 321-1']):out,status,_=c.collect(root,[SOURCE],NOW)
   self.assertEqual(25,status['newOrModifiedReferences']);self.assertEqual(26,len(c.decode(out)[1]))
 def test_has_metadata_is_exact_and_other_sources_stay_link_only(self):
  source={**SOURCE,'publication':'HAS_METADATA'}
  xml=item(title='SYNTHETIC Vaccination note de cadrage').replace(b'</item>',b'<description>Consultation en cours. Aucun avis final.</description></item>')
  m=c.rss(xml,source,NOW)[0]
  self.assertEqual('SYNTHETIC Vaccination note de cadrage',m['officialTitle'])
  self.assertEqual('Consultation en cours. Aucun avis final.',m['officialAbstract'])
  e=c.make_entry(source,m,NOW,'a'*64)
  self.assertEqual(m['officialTitle'],e['title'])
  self.assertNotIn('officialTitle',c.rss(xml,SOURCE,NOW)[0])
if __name__=='__main__':unittest.main()
