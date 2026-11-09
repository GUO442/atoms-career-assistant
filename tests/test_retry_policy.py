import unittest
from retry_policy import retry
class RetryTests(unittest.TestCase):
 def test_transient_then_success(self):
  calls=[];events=[]
  def fn():
   calls.append(1)
   if len(calls)<3:raise RuntimeError('model_failed')
   return 'ok'
  self.assertEqual(retry(fn,lambda *a:events.append(a),sleep=lambda _:None),'ok')
  self.assertEqual(events,[(1,5),(2,15)])
 def test_bounded(self):
  calls=[]
  def fn():calls.append(1);raise TimeoutError()
  with self.assertRaises(TimeoutError):retry(fn,sleep=lambda _:None)
  self.assertEqual(len(calls),3)
 def test_risk_not_retried(self):
  events=[]
  with self.assertRaises(ValueError):retry(lambda:(_ for _ in ()).throw(ValueError('AUTH_OR_RISK_REQUIRED')),lambda *a:events.append(a))
  self.assertEqual(events,[])
