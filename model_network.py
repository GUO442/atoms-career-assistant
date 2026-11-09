"""Let local model subprocesses use the user's existing macOS proxy settings."""
import os,sys,re,subprocess

def model_env():
 env=dict(os.environ)
 if any(env.get(k) for k in ('HTTPS_PROXY','https_proxy','ALL_PROXY','all_proxy')):return env
 if sys.platform!='darwin':return env
 try:text=subprocess.check_output(['scutil','--proxy'],text=True,timeout=3)
 except (OSError,subprocess.SubprocessError):return env
 def setting(key):
  m=re.search(r'^\s*'+key+r'\s*:\s*(\S+)\s*$',text,re.M)
  return m.group(1) if m else ''
 if setting('HTTPSEnable')!='1':return env
 host=setting('HTTPSProxy');port=setting('HTTPSPort')
 if not re.fullmatch(r'[A-Za-z0-9.-]+',host) or not port.isdigit() or not 1<=int(port)<=65535:return env
 env['HTTPS_PROXY']='http://'+host+':'+port
 if setting('HTTPEnable')=='1' and setting('HTTPProxy')==host and setting('HTTPPort')==port:env.setdefault('HTTP_PROXY',env['HTTPS_PROXY'])
 env['NO_PROXY']=','.join(filter(None,[env.get('NO_PROXY',env.get('no_proxy','')),'127.0.0.1','localhost']))
 return env
