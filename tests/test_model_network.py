import unittest
from unittest.mock import patch
from model_network import model_env
class NetworkTests(unittest.TestCase):
 def test_preserve_explicit_proxy(self):
  with patch.dict('os.environ',{'HTTPS_PROXY':'http://user-proxy:123'},clear=True):self.assertEqual(model_env()['HTTPS_PROXY'],'http://user-proxy:123')
 def test_existing_system_proxy(self):
  with patch.dict('os.environ',{},clear=True),patch('sys.platform','darwin'),patch('subprocess.check_output',return_value='HTTPSEnable : 1\nHTTPSProxy : 127.0.0.1\nHTTPSPort : 65532\n'):
   e=model_env();self.assertEqual(e['HTTPS_PROXY'],'http://127.0.0.1:65532');self.assertIn('localhost',e['NO_PROXY'])
 def test_no_proxy_no_change(self):
  with patch.dict('os.environ',{},clear=True),patch('sys.platform','darwin'),patch('subprocess.check_output',return_value='HTTPSEnable : 0'):
   self.assertEqual(model_env(),{})
