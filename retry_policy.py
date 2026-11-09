"""Bounded retry for pure reads/model calls, never for external sends."""
import time

def transient(exc):
 text=str(exc).lower()
 if any(x in text for x in ('auth_required','auth_or_risk','captcha','验证码','security_verification','访问受限','操作过于频繁')):return False
 return isinstance(exc,TimeoutError) or any(x in text for x in ('model_failed','timed out','timeout','connection reset','connection refused','page_request_failed','request_timeout','temporarily unavailable'))

def retry(fn,on_retry=lambda *a:None,keep_running=lambda:True,sleep=time.sleep):
 for attempt in range(1,4):
  try:return fn()
  except Exception as exc:
   if attempt==3 or not transient(exc) or not keep_running():raise
   delay=(5,15)[attempt-1];on_retry(attempt,delay)
   for _ in range(delay):
    if not keep_running():raise
    sleep(1)
