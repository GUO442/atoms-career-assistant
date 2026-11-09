# -*- coding: utf-8 -*-
"""Small, public progress snapshots; no prompts or internal reasoning."""
import time

def snapshot(trace):
 events=trace.get('events',[])
 message=events[-1]['message'] if events else '请求已接收'
 if message.startswith('开始：'):message='正在调用 '+message[3:]
 elif message.startswith('完成：'):message='已完成 '+message[3:]
 status=trace['status']
 if status=='completed':message='已完成'
 elif status=='cancelled':message='已停止'
 elif status in ('failed','interrupted'):message='执行失败' if status=='failed' else '执行中断'
 return {'id':trace['id'],'status':status,'message':message,'elapsed':max(0,int((trace.get('ended') or time.time())-trace['started']))}
