"""Execute the production Swift request method against a rotating-token HTTP fixture."""
import json,subprocess,tempfile,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
root=Path(__file__).resolve().parents[1]
counts={'post':0,'handshake':0}
class H(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  if self.path=='/api/state':counts['handshake']+=1;self.send(200,{'token':'fresh'})
  elif self.headers.get('X-App-Token')=='fresh':self.send(200,{'value':'updated'})
  else:self.send(403,{'error':'Invalid request'})
 def do_POST(self):counts['post']+=1;self.send(403,{'error':'Invalid request'})
 def send(self,status,data):
  body=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',0),H);threading.Thread(target=server.serve_forever,daemon=True).start()
source=(root/'desktop/Sources/CareerApp.swift').read_text()
method=source[source.index(' func request('):source.index(' func start()')]
swift='''import Foundation
typealias Obj=[String:Any]
func str(_ o:Obj,_ key:String,_ fallback:String="")->String{o[key] as? String ?? fallback}
@MainActor final class Client {
 var token="stale"
 let base=URL(string:"http://127.0.0.1:PORT")!
METHOD
}
@main struct Probe {
 @MainActor static func main() async throws {
  let c=Client()
  let result=try await c.request("/get",timeout:5)
  precondition(str(result,"value")=="updated")
  c.token="stale-again"
  do {_ = try await c.request("/post",["action":"send"],timeout:5);fatalError("write replayed")}
  catch {precondition(c.token=="fresh")}
  print("GET recovered; POST not replayed")
 }
}
'''.replace('PORT',str(server.server_port)).replace('METHOD',method)
try:
 with tempfile.TemporaryDirectory() as tmp:
  p=Path(tmp);(p/'Probe.swift').write_text(swift)
  subprocess.run(['swiftc','-parse-as-library',str(p/'Probe.swift'),'-o',str(p/'probe')],check=True)
  subprocess.run([str(p/'probe')],check=True)
 assert counts=={'post':1,'handshake':2},counts
 print('PASS: production client token rotation')
finally:server.shutdown()
