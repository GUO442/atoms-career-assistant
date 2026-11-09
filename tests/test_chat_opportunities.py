import json,tempfile,unittest,sqlite3
from pathlib import Path
from unittest.mock import patch
from chat_opportunities import *
from chat_intents import validate,IntentError
def msg(mid,role,at,text=None,**extra):return {'mid':str(mid),'role':role,'at':at,**({'text':text} if text else {}),**extra}
class ConversationTests(unittest.TestCase):
 def test_company_origin_source_card_beats_system_sender(self):
  ms=[msg(1,'company',1,job={'bottomText':'10月1日 由你发起的沟通'}),msg(2,'self',2,'你好，可以聊聊么')]
  result=classify_conversation(ms,True,[])
  self.assertEqual(result['contact_initiator'],'self');self.assertEqual(result['chat_phase'],'self_greeted_no_resume')
 def test_company_unanswered_and_two_way_without_resume(self):
  ms=[msg(1,'company',1,job={'bottomText':'向你发起的沟通'}),msg(2,'company',2,'有新的机会考虑吗')]
  self.assertEqual(classify_conversation(ms,True,[])['chat_phase'],'company_unanswered')
  ms.append(msg(3,'self',3,'在考虑'))
  self.assertEqual(classify_conversation(ms,True,[])['chat_phase'],'contacted_no_resume')
  self.assertEqual(classify_conversation(ms,True,[])['needs_reply'],'no')
 def test_incomplete_history_never_asserts_no_resume_or_initial_contact(self):
  result=classify_conversation([msg(1,'company',10,'你好')],False,[])
  self.assertEqual(result['chat_phase'],'unknown');self.assertEqual(result['resume_observed'],'unknown');self.assertEqual(result['contact_initiator'],'unknown')
 def test_resume_request_and_hr_text_after_it_exclude_system_cards(self):
  ms=[msg(1,'self',10,action={'aid':40}),msg(2,'company',11,attachment_name='a.docx')]
  self.assertEqual(classify_conversation(ms,True,[])['chat_phase'],'resume_waiting')
  ms.append(msg(3,'company',12,'已收到'))
  self.assertEqual(classify_conversation(ms,True,[])['chat_phase'],'resume_hr_replied')
 def test_known_local_delivery_survives_short_remote_window(self):
  app={'status':'sent','created':'2026-10-01T00:00:00+00:00'}
  result=classify_conversation([msg(1,'company',1793328422,'谢谢')],False,[app])
  self.assertEqual(result['chat_phase'],'resume_hr_replied')
 def test_sanitizer_keeps_evidence_and_drops_secrets(self):
  m={'mid':123,'time':1000,'type':3,'securityId':'secret','from':{'uid':2},'to':{'uid':1},'body':{'type':12,'hyperLink':{'text':'file.docx','url':'https://example/?token=secret','extraJson':json.dumps({'requestDialogMid':42,'resumeNewUrl':'bosszp://x?encryptResumeId=opaque&securityId=secret'})}}}
  s=sanitized_message(m,1,2);raw=json.dumps(s)
  self.assertNotIn('secret',raw);self.assertNotIn('https:',raw);self.assertEqual(s['attachment_id'],'opaque');self.assertNotIn('text',s)
 def test_store_deduplicates_messages_and_keeps_hr_separate(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=ChatStore(tmp);r={'job_id':'job','recruiter_id':'a'}
   self.assertEqual(store.contact(r,[msg(1,'self',1,'你好')],'run'),(True,1))
   self.assertEqual(store.contact(r,[msg(1,'self',1,'你好')],'run'),(False,0))
   store.contact(r|{'recruiter_id':'b'},[msg(1,'company',1,'你好')],'run')
   with store.connect() as c:
    self.assertEqual(c.execute('SELECT count(*) FROM contacts').fetchone()[0],2)
    self.assertEqual(c.execute('SELECT count(*) FROM messages').fetchone()[0],2)
 def test_pagination_nonprogress_keeps_partial_scope(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=ChatStore(tmp);raw={'messages':[{'mid':1,'time':1000,'type':3,'from':{'uid':1},'body':{'type':1,'text':'你好'}}],'hasMore':True,'minMsgId':1}
   with patch('chat_opportunities.boss_web.request',return_value=raw) as request:
    ms,complete=fetch_history({'uid':2,'encryptJobId':'job','encryptBossId':'boss','securityId':'not-saved'},1,store,'run')
   self.assertFalse(complete);self.assertEqual(len(ms),1);self.assertEqual(request.call_count,2)
 def test_strict_chat_filter_schema(self):
  self.assertEqual(validate({'tool':'chat.scan','arguments':{}})['tool'],'chat.scan')
  validate({'tool':'chat.list','arguments':{'filters':{'chat_phase':'company_unanswered'}}})
  with self.assertRaises(IntentError):validate({'tool':'chat.list','arguments':{'filters':{'send':True}}})

class OpportunityIntegrationTests(unittest.TestCase):
 def test_current_direct_policy_allows_matching_without_jd_and_repeat_reuses_it(self):
  import io
  from docx import Document
  from resume_library import Library
  from career_tracking import Tracker
  from discovery import Discovery
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);lib=Library(root/'data/resumes');tracker=Tracker(root/'data/tracking')
   d=Document();d.add_paragraph('Agent测试开发');out=io.BytesIO();d.save(out);lib.add('base.docx',out.getvalue())
   (root/'data/workspace.json').write_text(json.dumps({'preferences':'Agent测试开发，深圳'}))
   discovery=Discovery(root/'data',lambda *a:None,None)
   model=lambda *_:json.dumps({'assessments':[{'job_id':'job','recruiter_id':'2','decision':'recommend','reason':'Agent测试方向相关'}]})
   service=ChatOpportunityService(root,discovery,tracker,lib,model)
   c={'encryptJobId':'job','uid':2,'jobId':3,'name':'某女士','brandName':'公司','securityId':'secret'}
   messages=[msg(1,'company',1,job={'title':'AI Agent测试开发工程师','company':'公司','city':'深圳','salary':'30-40K','jobId':'3','bottomText':'向你发起的沟通'}),msg(2,'company',2,'你好')]
   def run(key):
    r={'id':key,'status':'running','processed':0,'new_contacts':0,'new_messages':0}
    service.collect(r);return r
   with patch('chat_opportunities.list_contacts',return_value=([c],'1',{'label':'30天','count':1})),patch('chat_opportunities.fetch_history',return_value=(messages,True)):
    r=run('first')
    self.assertEqual(r['matched'],1)
    self.assertEqual(service.status()['contacts'][0]['chat_phase'],'company_unanswered')
    self.assertEqual(len(discovery.history()['jobs']),1)
    with patch.object(service,'model',side_effect=AssertionError('no duplicate model call')):
     r=run('second')
    self.assertEqual(r['new_contacts'],0);self.assertEqual(r['new_messages'],0);self.assertEqual(r['reused_assessments'],1)
    self.assertEqual(len(discovery.history()['jobs']),1)
    self.assertEqual(lib.load()['applications'],[])
    self.assertEqual(tracker.listing()['actions'],[])

class ChatToolFacadeTests(unittest.TestCase):
 def test_sync_and_status_route_to_service_without_sending(self):
  from boss_tools import execute
  with patch('boss_tools.resume_tool',return_value={'ok':True,'sent':False}) as call:
   self.assertFalse(execute('chat-opportunities-sync',{})['sent'])
   call.assert_called_with('chat-opportunities-sync',{})
   execute('chat-opportunities-status',{'filters':{'chat_phase':'company_unanswered'}})
   call.assert_called_with('chat-opportunities-status',{'filters':{'chat_phase':'company_unanswered'}})
